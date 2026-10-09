#!/usr/bin/env python3
"""Stateful kubectl stand-in for executing the deploy buildspec in tests.

Models what the GitOps deploy depends on: the Argo CD Application finrisk/finrisk-inference (spec and
status), an Argo CD controller that reacts to a changed image.digest parameter one poll at a time, the
Deployment it syncs, the deploy runner's authorization, and the two in-pod scripts. The Application
starts as the bootstrap leaves it (the test writes it into FAKE_STATE). Any call it does not model fails,
so a new call in the buildspec cannot pass unnoticed; every call that reaches the API server must be
bounded: kq's --request-timeout, rollout status --timeout, or exec under `timeout` (the stub exports
FAKE_TIMEOUT).

Authorization: AmazonEKSEditPolicy in finrisk (no RBAC objects, nothing of Argo CD's) plus the Role of
infra/k8s/inference-app.yaml (get, watch, patch on applications/finrisk-inference in finrisk). Calls are
enforced (Forbidden) and `auth can-i` answers from the same rules. FAKE_RBAC changes them:
  no-group        the access entry lacks the group: nothing on the Application
  extra-delete    the Role also grants delete
  any-name        the Role has no resourceNames
  argocd-secrets  the runner can read Secrets in argocd

Controller, per poll of the Application after its digest changed (FAKE_CONTROLLER):
  normal (default)  refresh (OutOfSync, an automated operation Running), sync (Succeeded, Deployment
                    updated, Progressing), then Healthy when the image becomes ready
  degraded          as normal, but Degraded for two polls before Healthy (the HPA's metrics lag)
  frozen            never reacts: the status keeps describing the previous digest
The operation is shaped as Argo CD v3.5.3's autoSync builds it (controller/appcontroller.go): sync.source is
a copy of spec.source, sync.revision the resolved commit, initiatedBy.automated; it is the Application's
top-level `operation` while it runs, and syncResult.source copies its source (controller/sync.go).
FAKE_REFRESH_AFTER=n polls before the controller notices the change (default 1). The sync of a digest in
FAKE_SYNC_FAILS fails (operationState Failed, a SyncError). Images whose digest is in FAKE_BAD_IMAGES never
become ready: Progressing, then the Deployment's ProgressDeadlineExceeded after FAKE_DEADLINE_POLLS polls
(default 6) and Degraded. FAKE_OBSERVE_LAG=n: the deployment controller observes a changed template n polls
late (observedGeneration behind, the previous Progressing condition still shown). FAKE_APP_GET_FAIL=1 makes
reading the Application fail.

FAKE_SKEW=<name> falsifies one thing in every answer about the digest FAKE_SKEW_DIGEST once it is synced,
so each convergence check in the deploy buildspec's `ok` is shown to matter on its own: sync (OutOfSync),
revision, operation_revision, synced_revision (another commit), compared (no digest compared), operation
(still Running), synced (another digest synced), automated (started by a user), source (the operation's
own source has an extra parameter), sources and manifests (operation overrides), health (Degraded), image
(the Deployment runs another digest), observed (observedGeneration behind), ready (no ready replica).

exec runs the piped script with Python (python -I -S, the standard library only, as in the image):
  - a script with a BASE line (the smoke test) against a stand-in for the inference API
    (src/finrisk/serving.py) on the chart's Service; FAKE_SMOKE breaks one thing:
      wrong-sha          every endpoint reports another model (the image carries the wrong artifact)
      ready-wrong-sha    only /health/ready reports another model
      predict-wrong-sha  only the prediction reports another model
      not-ready          every endpoint answers 503, as serving.py does when the model cannot load
      prob-1.5, prob-neg the probability is above 1 or below 0
      prob-int           the prediction is a class label (an int), not a probability
  - a script with a PROMETHEUS line (the PromQL evidence) against a stand-in for the Prometheus query
    API, on a fake clock; its answers follow the predictions the smoke test made. FAKE_PROM:
      ok (default) | app-down | no-ksm | unscraped (no app series) | unreachable
"""
import copy
import json
import os
import re
import socket
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = os.environ["FAKE_STATE"]
state = json.load(open(STATE))
state.setdefault("calls", [])
state.setdefault("deployment", None)
state.setdefault("requests", 0)
state.setdefault("progress", 0)
args = sys.argv[1:]
state["calls"].append(" ".join(args))
env = os.environ.get
NS, APP = "finrisk", "finrisk-inference"
PROMETHEUS = "monitoring-prometheus.monitoring.svc.cluster.local:9090"
# The chart's wiring (check_inference_chart.py): Service finrisk-inference port 80 to the container's port.
SERVICES = {"finrisk-inference.finrisk": {"80": True}}
CONTAINERS = ["inference"]
FEATURES = ["debt_to_assets", "current_ratio", "return_on_assets", "log_market_cap"]
OTHER_SHA = "0" * 64
NOT_LOADED = {"detail": "Model artifact not found: /app/model/boosted_tree_model.joblib"}


def done(code=0, out="", err=""):
    json.dump(state, open(STATE, "w"))
    print(out, end="")
    print(err, end="", file=sys.stderr)
    sys.exit(code)


def unsupported():
    state.setdefault("unsupported", []).append(" ".join(args))
    done(2, err="fake kubectl: unsupported call: " + " ".join(args) + "\n")


# --- arguments ---------------------------------------------------------------------------------------
namespace, output, patch, positional, flags, i = "default", "", None, [], [], 0
command_end = args.index("--") if "--" in args else len(args)
while i < command_end:
    a = args[i]
    if a in ("-n", "--namespace", "-o", "-p", "-c"):
        if a in ("-n", "--namespace"):
            namespace = args[i + 1]
        elif a == "-o":
            output = args[i + 1]
        elif a == "-p":
            patch = args[i + 1]
        else:
            flags.append(f"-c={args[i + 1]}")
        i += 2
        continue
    (flags if a.startswith("-") else positional).append(a)
    i += 1
verb = positional[0] if positional else ""


def option(name):
    return next((f.split("=", 1)[1] for f in flags if f.startswith(name + "=")), None)


# --- authorization -----------------------------------------------------------------------------------
RBAC = env("FAKE_RBAC", "")


def allowed(action, resource, name, ns):
    if resource == "applications.argoproj.io":
        verbs = {"get", "watch", "patch"} | ({"delete"} if RBAC == "extra-delete" else set())
        return RBAC != "no-group" and ns == NS and action in verbs and (name == APP or RBAC == "any-name" and bool(name))
    if ns != NS:  # Edit is scoped to finrisk
        return RBAC == "argocd-secrets" and (action, resource) == ("get", "secrets")
    return not resource.startswith(("appprojects", "rolebindings", "roles", "clusterrole"))


def forbidden(action, resource, name=""):
    named = f' "{name}"' if name else ""
    done(1, err=f'Error from server (Forbidden): {resource}{named} is forbidden: User "arn:aws:sts::780976819607:'
                f'assumed-role/finrisk-ai-codebuild-deploy-x/AWSCodeBuild" cannot {action} resource "{resource}" '
                f'in API group "" in the namespace "{namespace}"\n')


# --- bounded calls -----------------------------------------------------------------------------------
if args[:2] == ["version", "--client"]:
    done(out="Client Version: v1.35.9\n")
bounded = "--request-timeout=10s" in flags or (verb == "rollout" and option("--timeout")) or (verb == "exec" and env("FAKE_TIMEOUT"))
if not bounded:
    state.setdefault("unbounded", []).append(" ".join(args))
    done(2, err="fake kubectl: a call to the API server without a bound: " + " ".join(args) + "\n")


# --- Argo CD controller -------------------------------------------------------------------------------
def digest_of(source):
    params = ((source or {}).get("helm") or {}).get("parameters") or []
    return next((p["value"] for p in params if p.get("name") == "image.digest"), None)


def tick():
    """One poll's worth of controller progress toward the Application's current digest."""
    app = state["app"]
    spec, status = app["spec"], app.setdefault("status", {})
    want = digest_of(spec["source"])
    mode = env("FAKE_CONTROLLER", "normal")
    dep = state["deployment"]
    if dep and dep.get("lag"):
        dep["lag"] -= 1
    if want is None or mode == "frozen":
        return
    synced = digest_of(((status.get("operationState") or {}).get("syncResult") or {}).get("source"))
    compared = digest_of(((status.get("sync") or {}).get("comparedTo") or {}).get("source"))
    if synced == want and compared == want and (status.get("health") or {}).get("status") == "Healthy":
        return
    state["progress"] += 1
    step = state["progress"] - int(env("FAKE_REFRESH_AFTER", "1"))
    if step <= 0:
        return  # not noticed yet: the status still describes the previous digest
    source = copy.deepcopy(spec["source"])
    revision = source["targetRevision"]
    policy = spec.get("syncPolicy") or {}
    # autoSync: Source = new(app.Spec.GetSource()), Revision = the compared commit, InitiatedBy.Automated.
    operation = {"sync": {"source": copy.deepcopy(source), "revision": revision, "prune": True},
                 "initiatedBy": {"automated": True}, "retry": policy.get("retry") or {"limit": 5}}
    if policy.get("syncOptions"):
        operation["sync"]["syncOptions"] = policy["syncOptions"]
    status.update(sync={"status": "OutOfSync", "revision": revision, "comparedTo": {"source": source,
                  "destination": spec["destination"]}}, conditions=[])
    if step == 1:
        app["operation"] = operation
        status["operationState"] = {"phase": "Running", "operation": operation}
        status["health"] = {"status": "Progressing"}
        return
    operation = (status.get("operationState") or {}).get("operation") or operation
    app.pop("operation", None)  # a completed operation is cleared (setOperationState)
    result = {"revision": revision, "source": copy.deepcopy(operation["sync"]["source"])}
    if want in env("FAKE_SYNC_FAILS", "").split(","):
        status["operationState"] = {"phase": "Failed", "operation": operation, "message": "one or more objects failed to apply",
                                    "syncResult": result}
        status["conditions"] = [{"type": "SyncError", "message": "Failed sync attempt: one or more objects failed to apply"}]
        return
    status["operationState"] = {"phase": "Succeeded", "operation": operation, "syncResult": result}
    status["sync"]["status"] = "Synced"
    image = spec["source"]["helm"]["valuesObject"]["image"]["repository"] + "@" + want
    if dep is None:
        dep = state["deployment"] = {"image": image, "revision": 1, "since": step, "generation": 1}
    elif dep["image"] != image:
        # The template changes now; the deployment controller observes it FAKE_OBSERVE_LAG polls later.
        dep.update(image=image, revision=dep["revision"] + 1, since=step, generation=dep.get("generation", 1) + 1,
                   lag=int(env("FAKE_OBSERVE_LAG", "0")), shown=progressing(dep), deadline=False)
    status["summary"] = {"images": [image]}
    bad = want in set(filter(None, env("FAKE_BAD_IMAGES", "").split(",")))
    age = step - dep["since"]
    if bad:
        late = age >= int(env("FAKE_DEADLINE_POLLS", "6"))
        dep["deadline"] = late
        status["health"] = {"status": "Degraded" if late else "Progressing"}
    elif age == 0:
        status["health"] = {"status": "Progressing"}
    elif mode == "degraded" and age <= 2:
        status["health"] = {"status": "Degraded", "message": "FailedGetResourceMetric"}
    else:
        status["health"] = {"status": "Healthy"}


def ready():
    dep = state["deployment"]
    bad = set(filter(None, env("FAKE_BAD_IMAGES", "").split(",")))
    return 1 if dep and dep["image"].split("@")[1] not in bad else 0


def progressing(dep):
    return "ProgressDeadlineExceeded" if dep.get("deadline") else "NewReplicaSetAvailable" if ready() else "ReplicaSetUpdated"


def deployment_object():
    dep = state["deployment"]
    generation, lag = dep.get("generation", 1), dep.get("lag", 0)
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": APP, "namespace": NS, "generation": generation,
            "annotations": {"deployment.kubernetes.io/revision": str(dep["revision"])}},
            "spec": {"template": {"spec": {"containers": [{"name": c, "image": dep["image"]} for c in CONTAINERS]}}},
            "status": {"observedGeneration": generation - 1 if lag else generation, "readyReplicas": ready(),
                       "conditions": [{"type": "Progressing", "reason": dep["shown"] if lag else progressing(dep)}]}}


OTHER_COMMIT = "f" * 40
OTHER_DIGEST = "sha256:" + "0" * 64


def skew(app, dep):
    """FAKE_SKEW: one falsehood in an answer whose Application has a sync result and a Deployment."""
    name, status = env("FAKE_SKEW", ""), app["status"]
    op = status.get("operationState") or {}
    if not name or "syncResult" not in op or not dep or digest_of(app["spec"]["source"]) != env("FAKE_SKEW_DIGEST"):
        return
    sync, result = op["operation"]["sync"], op["syncResult"]
    extra = {"name": "replicaCount", "value": "0"}
    {
        "sync": lambda: status["sync"].update(status="OutOfSync"),
        "revision": lambda: status["sync"].update(revision=OTHER_COMMIT),
        "operation_revision": lambda: sync.update(revision=OTHER_COMMIT),
        "synced_revision": lambda: result.update(revision=OTHER_COMMIT),
        "compared": lambda: status["sync"]["comparedTo"]["source"]["helm"].pop("parameters", None),
        "operation": lambda: op.update(phase="Running"),
        "synced": lambda: result["source"]["helm"].update(parameters=[{"name": "image.digest", "value": OTHER_DIGEST}]),
        "automated": lambda: op["operation"].update(initiatedBy={"username": "someone"}),
        "source": lambda: [s["helm"].setdefault("parameters", []).append(extra) for s in (sync["source"], result["source"])],
        "sources": lambda: sync.update(sources=[copy.deepcopy(sync["source"])]),
        "manifests": lambda: sync.update(manifests=["apiVersion: v1\nkind: ConfigMap\n"]),
        "health": lambda: status.update(health={"status": "Degraded"}),
        "image": lambda: dep["spec"]["template"]["spec"]["containers"][0].update(image=dep["spec"]["template"]["spec"][
            "containers"][0]["image"].split("@")[0] + "@" + OTHER_DIGEST),
        "observed": lambda: dep["status"].update(observedGeneration=dep["metadata"]["generation"] - 1),
        "ready": lambda: dep["status"].update(readyReplicas=0),
    }[name]()


def merge(target, change):
    """RFC 7386 JSON merge patch: objects merge, everything else (lists too) replaces, null removes."""
    for key, value in change.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


# --- in-pod scripts -----------------------------------------------------------------------------------
def closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class InferenceApi(BaseHTTPRequestHandler):
    """The response shapes of src/finrisk/serving.py for the endpoints the smoke script calls."""
    scenario = env("FAKE_SMOKE", "")
    predictions = 0

    def log_message(self, *_):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def sha(self, endpoint):
        wrong = self.scenario in ("wrong-sha", endpoint + "-wrong-sha")
        return OTHER_SHA if wrong else os.environ["FAKE_MODEL_SHA256"]

    def do_GET(self):
        if self.path not in ("/health/ready", "/v1/model"):
            return self.reply(404, {"detail": "Not Found"})
        if self.scenario == "not-ready":
            return self.reply(503, NOT_LOADED)
        if self.path == "/health/ready":
            return self.reply(200, {"status": "ready", "model_sha256": self.sha("ready"), "feature_count": len(FEATURES)})
        self.reply(200, {"model_family": "hist_gradient_boosting", "model_sha256": self.sha("model"), "features": FEATURES})

    def do_POST(self):
        if self.path != "/v1/risk/predict":
            return self.reply(404, {"detail": "Not Found"})
        raw = self.rfile.read(int(self.headers.get("content-length", 0)))
        json_body = self.headers.get("content-type", "").split(";")[0] == "application/json"
        try:
            body = json.loads(raw) if json_body else None
        except ValueError:
            body = None
        # PredictionRequest: only "features", a mapping of name to number or null.
        values = body.get("features") if isinstance(body, dict) and set(body) == {"features"} else None
        numbers = isinstance(values, dict) and all(v is None or isinstance(v, (int, float)) for v in values.values())
        if not numbers:
            return self.reply(422, {"detail": "request does not match PredictionRequest"})
        missing, unknown = sorted(set(FEATURES) - set(values)), sorted(set(values) - set(FEATURES))
        if missing or unknown:
            return self.reply(422, {"detail": f"Feature contract mismatch; missing={missing}, unknown={unknown}"})
        if self.scenario == "not-ready":
            return self.reply(503, NOT_LOADED)
        probability = {"prob-1.5": 1.5, "prob-neg": -0.25, "prob-int": 1}.get(self.scenario, 0.0123)
        type(self).predictions += 1
        self.reply(200, {"distress_12m_probability": probability, "model_sha256": self.sha("predict")})


class PrometheusApi(BaseHTTPRequestHandler):
    """GET /api/v1/query for the queries the PromQL script makes; one series or none per query."""
    scenario = env("FAKE_PROM", "ok")

    def log_message(self, *_):
        pass

    def answer(self, query):
        served = state["requests"]
        app = 'service="finrisk-inference"' in query or "http_target" in query or "finrisk_" in query
        if self.scenario == "unscraped" and app:
            return None
        if query.startswith("min(up{") and 'service="finrisk-inference"' in query:
            return 0 if self.scenario == "app-down" else 1
        if query == 'min(up{job="kube-state-metrics"})':
            return None if self.scenario == "no-ksm" else 1
        if query.startswith("sum(http_server_duration_milliseconds_sum{"):
            return 12.5 if served else "NaN"
        if query.startswith(("sum(http_server_duration_milliseconds_count{", "sum(finrisk_predictions_total{")):
            return served
        if query.startswith("histogram_quantile(0.95,"):
            return 20.5 if served else "NaN"
        if query.startswith(("kube_deployment_status_replicas_available{", "kube_horizontalpodautoscaler_status_current_replicas{")):
            return None if self.scenario == "no-ksm" else 1
        return None

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path != "/api/v1/query":
            self.send_response(404)
            self.end_headers()
            return
        value = self.answer(urllib.parse.parse_qs(url.query)["query"][0])
        result = [] if value is None else [{"metric": {}, "value": [1.7e9, str(value)]}]
        data = json.dumps({"status": "success", "data": {"resultType": "vector", "result": result}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(data)


# The PromQL script's clock: sleep advances it, so its polling bound is exercised without waiting.
FAKE_CLOCK = "import time as _t\n_now = [0.0]\n_t.monotonic = lambda: _now[0]\n_t.sleep = lambda s: _now.__setitem__(0, _now[0] + s)\n"


def run_in_pod(script):
    """Runs a piped in-pod script against the stand-in its address line names; anything else is refused."""
    base = re.search(r'^BASE = "(.*)"$', script, re.M)
    prometheus = re.search(r'^PROMETHEUS = "(.*)"$', script, re.M)
    if bool(base) == bool(prometheus):
        done(2, err="fake kubectl: the in-pod script has neither or both of BASE and PROMETHEUS\n")
    line = base or prometheus
    url = urllib.parse.urlsplit(line[1])
    if base:
        service = re.fullmatch(r"([a-z0-9-]+\.[a-z0-9-]+)\.svc\.cluster\.local", url.hostname or "")
        # A script that skips the Service would otherwise bypass the stand-in.
        if url.scheme != "http" or url.path or not service:
            done(2, err="fake kubectl: smoke script has no BASE line for a Service\n")
        reachable = SERVICES.get(service[1], {}).get(str(url.port or 80), False)
        handler = InferenceApi
    else:
        reachable = url.scheme == "http" and url.netloc == PROMETHEUS and not url.path and env("FAKE_PROM") != "unreachable"
        handler = PrometheusApi
        script = FAKE_CLOCK + script
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        address = "http://127.0.0.1:%d" % (server.server_address[1] if reachable else closed_port())
        script = script.replace(line[0], f'{line[0].split(" = ")[0]} = "{address}"', 1)
        # No proxy may see the request; no_proxy=* also stops urllib using macOS system proxies.
        run_env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
        run_env["no_proxy"] = "*"
        result = subprocess.run([sys.executable, "-I", "-S", "-"], input=script, env=run_env, capture_output=True,
                                text=True, timeout=120)
    finally:
        server.shutdown()
        server.server_close()
    state["requests"] += InferenceApi.predictions
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        print(f"command terminated with exit code {result.returncode}", file=sys.stderr)
    done(result.returncode)


# --- calls ---------------------------------------------------------------------------------------------
if positional[:2] == ["auth", "can-i"]:
    resource, _, name = positional[3].partition("/")
    yes = allowed(positional[2], resource, name, namespace)
    done(0 if yes else 1, out="yes\n" if yes else "no\n")
if positional == ["get", "serviceaccount", "default"] and namespace == NS:
    done(out="serviceaccount/default\n")
if positional == ["get", "applications.argoproj.io", APP] and output == "json":
    if not allowed("get", "applications.argoproj.io", APP, namespace):
        forbidden("get", "applications.argoproj.io", APP)
    if env("FAKE_APP_GET_FAIL"):
        done(1, err="error: the server is currently unable to handle the request\n")
    if state.get("app") is None:
        done(1, err=f'Error from server (NotFound): applications.argoproj.io "{APP}" not found\n')
    done(out=json.dumps(state["app"], indent=2) + "\n")
if positional == ["get", f"applications.argoproj.io/{APP}", f"deployment/{APP}"] and output == "json" \
        and "--ignore-not-found" in flags:
    if not allowed("get", "applications.argoproj.io", APP, namespace):
        forbidden("get", "applications.argoproj.io", APP)
    tick()
    app, dep = copy.deepcopy(state["app"]), deployment_object() if state["deployment"] else None
    skew(app, dep)
    items = [app] + ([dep] if dep else [])
    done(out=json.dumps({"apiVersion": "v1", "kind": "List", "items": items, "metadata": {}}, indent=2) + "\n")
if positional == ["patch", "applications.argoproj.io", APP]:
    if not allowed("patch", "applications.argoproj.io", APP, namespace):
        forbidden("patch", "applications.argoproj.io", APP)
    if option("--type") != "merge":
        unsupported()
    before = digest_of(state["app"]["spec"]["source"])
    merge(state["app"], json.loads(patch))
    state.setdefault("patches", []).append({"manager": option("--field-manager"), "patch": json.loads(patch)})
    if digest_of(state["app"]["spec"]["source"]) != before:
        state["progress"] = 0
    done(out=f"application.argoproj.io/{APP} patched\n")
if positional == ["get", "deployment", APP] and namespace == NS \
        and output == r"jsonpath={.metadata.annotations.deployment\.kubernetes\.io/revision}":
    if state["deployment"] is None:
        done(1, err=f'Error from server (NotFound): deployments.apps "{APP}" not found\n')
    done(out=str(state["deployment"]["revision"]))
if positional == ["rollout", "status", f"deployment/{APP}"] and namespace == NS:
    if state["deployment"] is None:
        done(1, err=f'Error from server (NotFound): deployments.apps "{APP}" not found\n')
    if not ready():
        done(1, err="error: timed out waiting for the condition\n")
    done(out=f'deployment "{APP}" successfully rolled out\n')
if verb == "exec" and args[command_end + 1:] == ["python", "-"]:
    target = next((p for p in positional if p.startswith("deploy/")), "")
    if namespace != NS or target != f"deploy/{APP}" or state["deployment"] is None:
        done(1, err=f'Error from server (NotFound): deployments.apps "{target.split("/")[-1]}" not found\n')
    if not ready():
        done(1, err="error: unable to upgrade connection: container not found (\"inference\")\n")
    # Without -c, kubectl picks the first container.
    container = option("-c") or CONTAINERS[0]
    if container not in CONTAINERS:
        done(1, err=f"Error from server (BadRequest): container {container} is not valid for pod {APP}-6d4f8b9c7-x2k9p\n")
    if "-i" not in flags and "--stdin" not in flags:
        done(0)
    run_in_pod(sys.stdin.read())
unsupported()
