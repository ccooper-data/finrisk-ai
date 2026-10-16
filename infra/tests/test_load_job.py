#!/usr/bin/env python3
# The HPA load test's Job (infra/k8s/load-job.yaml) without tools: Pod Security restricted, bounded in time,
# parallelism and resources, nothing exposed, outside Argo CD's view, and run by the image the deploy build
# just deployed, its Pod selected by none of the release's selectors but by the deploy's cleanup check.
# Every property is also checked against a deliberately broken copy and must fail there. Its script runs
# here against stand-ins for the inference API: it sends only valid prediction requests, at the paced rate,
# and stops on time even when answers are slow. kubeconform validates the Job in check_load_job.py (and
# check_inference_chart.py its labels against the rendered chart), the worker capacity budget counts it in
# check_capacity_budget.py, and the deploy build's use of it (create, wait, PromQL, delete) runs against a
# fake kubectl in test_deploy_buildspec_runtime.py.
import ast
import copy
import json
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from pod_security import restricted

ROOT = Path(__file__).resolve().parents[2]
K8S = ROOT / "infra/k8s"
TEXT = (K8S / "load-job.yaml").read_text()
DOCS = [d for d in yaml.safe_load_all(TEXT) if d]
TF = (ROOT / "infra/terraform/deploy_path.tf").read_text()
DEPLOY = (ROOT / "infra/terraform/deploy/deploy-buildspec.yml.tftpl").read_text()
PROJECTS = [d for d in yaml.safe_load_all((K8S / "argocd-projects.yaml").read_text()) if d]
ARGOCD_VALUES = yaml.safe_load((K8S / "argocd-values.yaml").read_text())
HELPERS = (ROOT / "charts/finrisk-inference/templates/_helpers.tpl").read_text()
CHART = yaml.safe_load((ROOT / "charts/finrisk-inference/Chart.yaml").read_text())


def local(name):
    match = re.search(rf'^  {name}\s+= "([^"]*)"$', TF, re.M)
    return match[1] if match else None


NAMESPACE, APP = local("k8s_app_namespace"), local("k8s_app_name")
SERVICE = f"{APP}.{NAMESPACE}.svc.cluster.local"
# How long the deploy build needs the load: from creating the Job, the wait for the HPA, then the PromQL
# exec, each call bounded by kq's request timeout.
HPA_WAIT = int(re.search(r"wait_for (\d+) scaled_up && scaled=yes \|\| load=hpa_not_scaled", DEPLOY)[1])
PROMQL_EXEC = int(re.search(r'timeout (\d+) "\$K" -n "\$NS" exec -i deploy/"\$APP" -c inference -- python - \$\(\(', DEPLOY)[1])
REQUEST = int(re.search(r'kq\(\) \{ "\$K" --request-timeout=(\d+)s', DEPLOY)[1])
NEEDED = HPA_WAIT + 5 + REQUEST + PROMQL_EXEC
STDLIB = {"json", "socket", "threading", "time", "urllib.request"}
# The label the deploy's cleanup check lists the Job and its Pod by (its gone()).
CLEANUP = re.search(r'gone\(\) \{ left="\$\(kq -n "\$NS" get jobs,pods -l ([\w./-]+)=([\w.-]+) -o name\)"', DEPLOY)
CLEANUP = (CLEANUP[1], CLEANUP[2]) if CLEANUP else ("", "")


def chart_selector():
    """The selector labels of the chart's Service and Deployment (and so the Pods its HPA counts), from
    _helpers.tpl and Chart.yaml; empty when the template is not the plain form this reads."""
    name = re.search(r'define "finrisk-inference\.name" -\}\}\n\{\{ \.Chart\.Name \}\}\n', HELPERS)
    body = re.search(r'define "finrisk-inference\.selectorLabels" -\}\}\n(.*?)\n\{\{- end \}\}', HELPERS, re.S)
    if not (name and body):
        return {}
    text = body[1].replace('{{ include "finrisk-inference.name" . }}', CHART["name"])
    return {} if "{{" in text else yaml.safe_load(text) or {}


SELECTOR = chart_selector()


def script_of(docs):
    container = docs[0]["spec"]["template"]["spec"]["containers"][0]
    return container.get("args", [""])[0] if container.get("command") == ["python", "-c"] else ""


def constants(script):
    match = re.search(r"^SECONDS, WORKERS, RATE = (\d+), (\d+), ([0-9.]+)$", script, re.M)
    return (int(match[1]), int(match[2]), float(match[3])) if match else (0, 0, 0.0)


def pod_labels(job):
    return ((job.get("spec", {}).get("template") or {}).get("metadata") or {}).get("labels") or {}


def labels_and_annotations(job):
    meta = [job.get("metadata") or {}, (job.get("spec", {}).get("template") or {}).get("metadata") or {}]
    return {k: v for m in meta for key in ("labels", "annotations") for k, v in (m.get(key) or {}).items()}


def properties(docs):
    job = docs[0] if docs else {}
    spec = job.get("spec") or {}
    pod = (spec.get("template") or {}).get("spec") or {}
    containers = pod.get("containers") or []
    container = containers[0] if containers else {}
    script = script_of(docs) if docs else ""
    seconds, workers, rate = constants(script)
    request_timeout = max(map(int, re.findall(r"timeout=(\d+)", script)), default=10 ** 6)
    resources = container.get("resources") or {}
    tags = labels_and_annotations(job)
    finrisk = next((p.get("spec", {}) for p in PROJECTS if p["metadata"]["name"] == "finrisk"), {})
    tracking = ARGOCD_VALUES.get("configs", {}).get("cm", {}).get("application.resourceTrackingMethod", "annotation")
    try:
        imports = {n.name for node in ast.walk(ast.parse(script)) if isinstance(node, ast.Import) for n in node.names} | {
            node.module for node in ast.walk(ast.parse(script)) if isinstance(node, ast.ImportFrom)}
    except SyntaxError:
        imports = None
    return {
        "load-job.yaml holds one batch/v1 Job, finrisk-load, created in the app namespace (no other namespace named)":
            [(d.get("apiVersion"), d.get("kind")) for d in docs] == [("batch/v1", "Job")]
            and job["metadata"].get("name") == "finrisk-load" and job["metadata"].get("namespace", NAMESPACE) == NAMESPACE == "finrisk",
        **{f"Pod Security {k}": v for k, v in restricted(spec.get("template") or {"spec": {}}).items()},
        "runs as the image's user 10001, read-only root filesystem, no service account token, no Service links":
            (pod.get("securityContext") or {}).get("runAsUser") == 10001 and len(containers) == 1
            and (container.get("securityContext") or {}).get("readOnlyRootFilesystem") is True
            and pod.get("automountServiceAccountToken") is False and pod.get("enableServiceLinks") is False,
        f"bounded in time: no retry, the script outlasts the build's need for load ({NEEDED} s) and then stops by the clock "
        f"(plus one request's timeout), the Pod is stopped soon after, a finished Job is removed":
            spec.get("backoffLimit") == 0 and pod.get("restartPolicy") == "Never"
            and re.search(r"^    while time\.monotonic\(\) < end:$", script, re.M) is not None
            and NEEDED <= seconds < seconds + request_timeout < (spec.get("activeDeadlineSeconds") or 0) <= seconds + 120
            and 0 < (spec.get("ttlSecondsAfterFinished") or 0) <= 300 and 0 < pod.get("terminationGracePeriodSeconds", 30) <= 10,
        "bounded in size: one Pod, a few paced workers, CPU and memory requested and capped":
            spec.get("parallelism") == spec.get("completions") == 1 and 1 <= workers <= 8 and 0 < rate <= 100
            and all(r in (resources.get(kind) or {}) for kind in ("requests", "limits") for r in ("cpu", "memory")),
        "exposes nothing: no port, no volume (no PersistentVolumeClaim), and only the Job":
            not any(c.get("ports") for c in containers) and not pod.get("volumes") and len(docs) == 1,
        "not Argo CD's: no tracking label or annotation, annotation tracking, and the finrisk AppProject admits no Job":
            "app.kubernetes.io/instance" not in tags and not any(k.startswith("argocd.argoproj.io/") for k in tags)
            and tracking == "annotation"
            and not any(k.get("kind") == "Job" for k in finrisk.get("namespaceResourceWhitelist", [])),
        # The chart's Service and Deployment select its selectorLabels (app: finrisk-inference). A Pod they
        # select would be a Service endpoint and a scrape target, and the HPA would count its CPU (it counts
        # the Pods its target's selector matches, whoever owns them): the load generator could scale itself.
        f"its Pod is selected by none of the release's selectors ({SELECTOR}: Service endpoints, the HPA's Pods)":
            SELECTOR == {"app": APP} and not SELECTOR.items() <= pod_labels(job).items(),
        f"the Job and its Pod carry the label the deploy's cleanup check lists them by ({'='.join(CLEANUP)})":
            all(CLEANUP) and (job.get("metadata", {}).get("labels") or {}).get(CLEANUP[0]) == CLEANUP[1]
            and pod_labels(job).get(CLEANUP[0]) == CLEANUP[1],
        "runs the image the deploy build just deployed: a placeholder the build replaces with the digest-pinned URI":
            container.get("image") == "LOAD_IMAGE" and "imagePullPolicy" not in container
            and [l for l in TEXT.splitlines() if "LOAD_IMAGE" in l and not l.lstrip().startswith("#")] == ["          image: LOAD_IMAGE"]
            and 'sed "s#LOAD_IMAGE#$FINRISK_IMAGE_URI#" /tmp/load-job.yaml | kq -n "$NS" create -f -' in DEPLOY
            and DEPLOY.index("FINRISK_IMAGE_URI rejected") < DEPLOY.index("s#LOAD_IMAGE#"),
        "the script: the standard library only, the Service resolved once, the smoke test's request":
            imports == STDLIB and f'socket.gethostbyname("{SERVICE}")' in script and script.count("gethostbyname") == 1
            and '"/v1/model"' in script and '"/v1/risk/predict"' in script
            and 'json.dumps({"features": dict.fromkeys(json.load(r)["features"])})' in script,
    }


def job(change):
    docs = copy.deepcopy(DOCS)
    change(docs[0], docs[0]["spec"]["template"]["spec"], docs[0]["spec"]["template"]["spec"]["containers"][0])
    return docs


def script_change(old, new):
    def change(j, pod, c):
        c["args"][0] = c["args"][0].replace(old, new) if old in c["args"][0] else "missing: " + old
    return change


CONTROLS = {
    "runAsNonRoot false": (lambda j, pod, c: pod["securityContext"].update(runAsNonRoot=False),
                           "Pod Security restricted: every container runs as non-root, never UID 0"),
    "privilege escalation": (lambda j, pod, c: c["securityContext"].update(allowPrivilegeEscalation=True),
                             "Pod Security restricted: allowPrivilegeEscalation false on every container"),
    "capabilities kept": (lambda j, pod, c: c["securityContext"].pop("capabilities"),
                          "Pod Security restricted: capabilities drop ALL, add at most NET_BIND_SERVICE"),
    "no seccomp profile": (lambda j, pod, c: pod["securityContext"].pop("seccompProfile"),
                           "Pod Security restricted: seccomp RuntimeDefault or Localhost for every container"),
    "the host network": (lambda j, pod, c: pod.update(hostNetwork=True), "Pod Security restricted: no host network, PID or IPC"),
    "a writable root filesystem": (lambda j, pod, c: c["securityContext"].update(readOnlyRootFilesystem=False),
                                   "runs as the image's user 10001, read-only root filesystem, no service account token, no Service links"),
    "a service account token": (lambda j, pod, c: pod.update(automountServiceAccountToken=True),
                                "runs as the image's user 10001, read-only root filesystem, no service account token, no Service links"),
    "retries": (lambda j, pod, c: j["spec"].update(backoffLimit=3), "bounded in time"),
    "no deadline": (lambda j, pod, c: j["spec"].pop("activeDeadlineSeconds"), "bounded in time"),
    "a deadline of an hour": (lambda j, pod, c: j["spec"].update(activeDeadlineSeconds=3600), "bounded in time"),
    "a finished Job kept": (lambda j, pod, c: j["spec"].pop("ttlSecondsAfterFinished"), "bounded in time"),
    "a script that stops before the build has its evidence": (script_change("= 600, 8,", "= 120, 8,"), "bounded in time"),
    "restarts": (lambda j, pod, c: pod.update(restartPolicy="OnFailure"), "bounded in time"),
    "ten Pods": (lambda j, pod, c: j["spec"].update(parallelism=10, completions=10), "bounded in size"),
    "no CPU limit": (lambda j, pod, c: c["resources"]["limits"].pop("cpu"), "bounded in size"),
    "an unpaced rate": (script_change("= 600, 8, 80.0", "= 600, 64, 4000.0"), "bounded in size"),
    "a container port": (lambda j, pod, c: c.update(ports=[{"containerPort": 8080, "hostPort": 8080}]), "exposes nothing"),
    "a volume": (lambda j, pod, c: pod.update(volumes=[{"name": "data", "persistentVolumeClaim": {"claimName": "x"}}]),
                 "exposes nothing"),
    "Argo CD's instance label": (lambda j, pod, c: j["metadata"]["labels"].update({"app.kubernetes.io/instance": "finrisk-inference"}),
                                 "not Argo CD's"),
    "an Argo CD tracking annotation": (lambda j, pod, c: j["metadata"].update(annotations={
        "argocd.argoproj.io/tracking-id": "finrisk-inference:batch/Job:finrisk/finrisk-load"}), "not Argo CD's"),
    "the chart's selector label on the Pod (a Service endpoint the HPA counts)": (
        lambda j, pod, c: j["spec"]["template"]["metadata"]["labels"].update({"app": APP}), "its Pod is selected by none"),
    "a Pod without the cleanup label (the Job keeps it)": (
        lambda j, pod, c: j["spec"]["template"]["metadata"].update(labels={"app.kubernetes.io/component": "load"}),
        "the Job and its Pod carry the label"),
    "a loop that ends on scheduled slots, not the clock": (script_change("while time.monotonic() < end:", "while due < end:"),
                                                           "bounded in time"),
    "an image by tag": (lambda j, pod, c: c.update(image="python:3.12-slim"), "runs the image the deploy build just deployed"),
    "a third-party load tool": (script_change("import json, socket", "import requests, json, socket"),
                                "the script: the standard library only"),
}


def prop(name):
    return next(k for k in properties(DOCS) if k.startswith(name))


# --- The script against a stand-in for the inference API ---------------------------------------------
FEATURES = ["debt_to_assets", "current_ratio", "return_on_assets", "log_market_cap"]


class Api(BaseHTTPRequestHandler):
    """GET /v1/model and POST /v1/risk/predict as src/finrisk/serving.py answers them, each prediction after
    `delay` seconds; counts every request."""
    seen = []
    delay = 0.0

    def log_message(self, *_):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.seen.append(("GET", self.path, None))
        if self.path != "/v1/model":
            return self.reply(404, {"detail": "Not Found"})
        self.reply(200, {"model_family": "hist_gradient_boosting", "features": FEATURES})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length", 0)))
        try:
            body = json.loads(raw) if self.headers.get("content-type") == "application/json" else None
        except ValueError:
            body = None
        values = body.get("features") if isinstance(body, dict) and set(body) == {"features"} else None
        valid = self.path == "/v1/risk/predict" and isinstance(values, dict) and sorted(values) == sorted(FEATURES) \
            and all(v is None or isinstance(v, (int, float)) for v in values.values())
        self.seen.append(("POST", self.path, valid))
        time.sleep(self.delay)
        self.reply(200 if valid else 422, {"distress_12m_probability": 0.0123} if valid else {"detail": "invalid"})


class Server(ThreadingHTTPServer):
    # Room for every worker's connection at once (socketserver's default backlog of 5 drops some for a second).
    request_queue_size = 64


def run_script(script, seconds=2.0, delay=0.0):
    """The script for `seconds`, against the stand-in in place of the Service: (requests, wall seconds, exit code)."""
    Api.seen, Api.delay = [], delay
    server = Server(("127.0.0.1", 0), Api)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    patched = script.replace(f'socket.gethostbyname("{SERVICE}")', '"127.0.0.1:%d"' % server.server_address[1])
    patched = re.sub(r"^SECONDS, WORKERS, RATE = \d+,", f"SECONDS, WORKERS, RATE = {seconds},", patched, flags=re.M)
    started = time.monotonic()
    try:
        result = subprocess.run([sys.executable, "-I", "-S", "-c", patched], capture_output=True, text=True, timeout=30,
                                env={"no_proxy": "*"})
    finally:
        server.shutdown()
        server.server_close()
    return list(Api.seen), time.monotonic() - started, result.returncode


def script_behaves(script):
    """Against a prompt stand-in, for 2 s: one model read, then only valid predictions, about RATE per second
    (an unpaced script sends far more), for the whole 2 s and not much longer."""
    _, workers, rate = constants(script)
    seen, wall, code = run_script(script)
    posts = [s for s in seen if s[0] == "POST"]
    return code == 0 and seen[:1] == [("GET", "/v1/model", None)] and [s for s in seen if s[0] == "GET"] == seen[:1] \
        and posts and all(valid for _, _, valid in posts) and 0.6 * rate * 2 <= len(posts) <= 1.2 * rate * 2 + workers \
        and 1.9 <= wall < 8


SLOW = 0.3


def stops_on_time(script):
    """Against a stand-in that answers each prediction after 0.3 s, slower than the pace, for 2 s: the script
    still stops at 2 s plus the answers in flight, and skips the slots it missed (one request in flight per
    worker, nothing sent late in a burst)."""
    _, workers, _ = constants(script)
    seen, wall, code = run_script(script, delay=SLOW)
    posts = len([s for s in seen if s[0] == "POST"])
    return code == 0 and 0 < posts <= workers * (2 / SLOW + 1) and wall < 2 + SLOW + 1.5


SCRIPT = script_of(DOCS)
# The loop as first written: it ends once every scheduled slot is sent, however late.
CATCH_UP = SCRIPT.replace("while time.monotonic() < end:", "while due < end:").replace(
    "due = max(due + WORKERS / RATE, time.monotonic())", "due += WORKERS / RATE")
found = properties(DOCS)
checks = {
    **found,
    "the script sends one model read, then only valid prediction requests at the paced rate, for its whole run":
        script_behaves(SCRIPT),
    "negative control: a script whose request lacks the features is caught":
        not script_behaves(SCRIPT.replace('dict.fromkeys(json.load(r)["features"])', "{}")),
    "negative control: an unpaced script is caught (it sends far more than the rate)":
        "time.sleep(max(0.0, due - time.monotonic()))" in SCRIPT
        and not script_behaves(SCRIPT.replace("time.sleep(max(0.0, due - time.monotonic()))", "pass")),
    "with slow answers the script still stops on time and skips the slots it missed": stops_on_time(SCRIPT),
    "negative control: a script that catches up on missed slots (its fixed quota) runs on past its deadline":
        CATCH_UP != SCRIPT and not stops_on_time(CATCH_UP),
}
for name, (change, prefix) in CONTROLS.items():
    key = prop(prefix)
    checks[f"negative control: {name} fails '{key[:70]}'"] = found[key] and not properties(job(change))[key]

failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("Load Job acceptance failed: " + ", ".join(failed))
