#!/usr/bin/env python3
"""Stateful kubectl stand-in for executing the deploy buildspec in tests.

Models what the GitOps deploy depends on: the Argo CD Application finrisk/finrisk-inference (spec and
status, with the per-object sync status of its four chart objects), an Argo CD controller that reacts to
a changed image.digest parameter one poll at a time, the Deployment and HPA it syncs (as the deploy's poll
reads them), the HPA's status as the load test reads it, the load test's Job, the deploy runner's
authorization, and the two in-pod scripts (infra/k8s/smoke.py and promql.py, as the buildspec unpacks
them). The Application starts as the bootstrap leaves it (the test writes it into FAKE_STATE). Any call it
does not model fails, so a new call in the buildspec cannot pass unnoticed; every call that reaches the API
server must be bounded: kq's --request-timeout, rollout status --timeout, or exec under `timeout` (the stub
exports FAKE_TIMEOUT).

Authorization: AmazonEKSEditPolicy in finrisk (no RBAC objects, nothing of Argo CD's) plus the Role of
infra/k8s/inference-app.yaml (get, watch, patch on applications/finrisk-inference in finrisk). Calls are
enforced (Forbidden) and `auth can-i` answers from the same rules. FAKE_RBAC changes them:
  no-group        the access entry lacks the group: nothing on the Application
  extra-delete    the Role also grants delete
  any-name        the Role has no resourceNames
  argocd-secrets  the runner can read Secrets in argocd
  no-hpa          Edit without get on HorizontalPodAutoscalers
  no-deployment   Edit without get on Deployments

Controller, per poll of the Application after its digest changed (FAKE_CONTROLLER):
  normal (default)  refresh (OutOfSync, an automated operation Running), sync (Succeeded, Deployment
                    updated, Progressing), then Healthy when the image becomes ready
  degraded          as normal, but Degraded for two polls before Healthy (the HPA's metrics lag)
  frozen            never reacts: the status keeps describing the previous digest
The operation is shaped as Argo CD v3.5.3's autoSync builds it (controller/appcontroller.go): sync.source is
a copy of spec.source, sync.revision the resolved commit, initiatedBy.automated; it is the Application's
top-level `operation` while it runs, and syncResult.source copies its source (controller/sync.go).
FAKE_REFRESH_AFTER=n polls before the controller notices the change (default 1); -1: it noticed and synced
before the build's first poll, so no poll sees the operation Running. The sync of a digest in
FAKE_SYNC_FAILS fails (operationState Failed, a SyncError). Images whose digest is in FAKE_BAD_IMAGES never
become ready: Progressing, then the Deployment's ProgressDeadlineExceeded after FAKE_DEADLINE_POLLS polls
(default 6) and Degraded. FAKE_OBSERVE_LAG=n: the deployment controller observes a changed template n polls
late (observedGeneration behind, the previous Progressing condition still shown). FAKE_APP_GET_FAIL=1 makes
reading the Application fail.

FAKE_SKEW=<name> falsifies one thing in every answer about the digest FAKE_SKEW_DIGEST once it is synced,
so each convergence check in the deploy buildspec's `ok` is shown to matter on its own: sync (OutOfSync,
no object listed out of sync), unknown (OutOfSync, the HPA listed OutOfSync and the Deployment Unknown),
revision, operation_revision, synced_revision (another commit), compared (no digest compared), operation
(still Running), synced (another digest synced), automated (started by a user), source (the operation's
own source has an extra parameter), sources and manifests (operation overrides), health (Degraded), image
(the Deployment runs another digest), sidecar and init (its template also runs another image, in a
container or an init container), observed (observedGeneration behind), ready (no ready replica), updated
(a replica of the previous template left), scaled (spec.replicas 2, one replica so far), unavailable (the
replica ready but not available), hpa (the HPA is gone).

After the sync of FAKE_SKEW_DIGEST succeeded, as Argo CD v3.5.3 can report it. An entry is a chart object
by kind, or group/Kind/namespace/name for another object (group empty for the core group):
  FAKE_OUT_OF_SYNC=entry,...  those objects stay OutOfSync, and so the Application, though all is as
                              synced; self-heal re-syncs with backoff (SELF_HEAL_POLLS: a Running operation
                              without a result)
  FAKE_MISSING=Kind           that chart object is gone: listed OutOfSync, the health still Healthy (Argo CD
                              3.4+ ignores missing objects, and keeps no per-object health in the Application
                              by default); without the ServiceMonitor, Prometheus has no target for the app;
                              without the HPA, the load test's read of it finds none
  FAKE_DRIFT=previous         something else keeps the Deployment on the previous image: the Application
                              alternates OutOfSync (the Deployment listed) and Synced

The load test: the HPA finrisk/finrisk-inference (kubectl get hpa) and the Job finrisk-load, which the
deploy may create (from stdin, one Job only) and delete. Pod Security restricted is enforced on the Job's
Pod template (infra/tests/pod_security.py): a Job whose Pod it rejects is created, but runs no Pod, as the
Job controller's FailedCreate. While a Job runs Pods, each HPA read advances the HPA (FAKE_HPA):
  scales (default)  current 1 for FAKE_HPA_AFTER reads (default 2), then desired 3, then current 3
  never             current and desired stay 1 under load (CPU below target)
  at-two            the HPA is already at 2 replicas before any load
FAKE_JOB: create-fails (Forbidden) | exists (a Job of that name is left over) | delete-fails (Forbidden) |
stuck (its Pod never terminates) | list-fails (listing Jobs and Pods times out). A deleted Job's Pod is gone
after one more read. A list by label (-l key=value) shows the Job by its own labels and its Pod by the Pod
template's, as the API server selects them. The namespace's events answer what the Job and the HPA did (for
the build's diagnosis of a failed load test).

exec runs the piped script with Python (python -I -S, the standard library only, as in the image), with
the arguments after `python -`:
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
    Over the load interval ([<n>s] of kube-state-metrics' own series, job="kube-state-metrics"), it shows
    the HPA's largest current and desired replicas while the Job ran, and the app 80 successful
    predictions/s (the Job's rate) while its Pod runs. Each n is recorded with the true load interval at that
    query (the build's clock since the Job was created plus the script's own fake clock, which it passes
    along with each query). A window reaching back before the Job sees an earlier load test's scale-out
    (3 replicas) still in Prometheus. FAKE_PROM_LOAD: ok (default) | ksm-unscaled (no scale-up scraped) |
    outage (no replica available for a moment) | no-requests (no successful prediction)

FAKE_STALE_DEADLINE: after a template change the Deployment reports it observed (observedGeneration
current) but can still show the previous rollout's Progressing condition, as the deployment controller can
for a moment after a re-patch: a comma list with one 1 or 0 per read from the change on, 1 where that read
shows the previous condition ("1": the first read only; "1,0,1": the first and third).
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
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pod_security import restricted  # noqa: E402

STATE = os.environ["FAKE_STATE"]
state = json.load(open(STATE))
state.setdefault("calls", [])
state.setdefault("deployment", None)
state.setdefault("requests", 0)
state.setdefault("progress", 0)
state.setdefault("polls", 0)
state.setdefault("job", None)
state.setdefault("hpa", {"current": 1, "desired": 1, "reads": 0, "max_current": 1, "max_desired": 1})
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
HPA_JSONPATH = ("jsonpath={.status.currentReplicas} {.status.desiredReplicas} "
                "{.status.currentMetrics[*].resource.current.averageUtilization}")
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
    if a in ("-n", "--namespace", "-o", "-p", "-c", "-f", "-l"):
        if a in ("-n", "--namespace"):
            namespace = args[i + 1]
        elif a == "-o":
            output = args[i + 1]
        elif a == "-p":
            patch = args[i + 1]
        else:
            flags.append(f"{a}={args[i + 1]}")
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
    if action == "get" and resource in {"no-hpa": ("hpa", "horizontalpodautoscalers.autoscaling"),
                                        "no-deployment": ("deployment", "deployments.apps")}.get(RBAC, ()):
        return False
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


# The chart's objects, as Argo CD lists them in status.resources.
CHART = [("apps", "v1", "Deployment"), ("", "v1", "Service"), ("autoscaling", "v2", "HorizontalPodAutoscaler"),
         ("monitoring.coreos.com", "v1", "ServiceMonitor")]


def resources(out_of_sync):
    """status.resources: the core group is omitted (omitempty), as Argo CD writes it."""
    return [{**({"group": g} if g else {}), "version": v, "kind": k, "namespace": NS, "name": APP,
             "status": "OutOfSync" if k in out_of_sync else "Synced"} for g, v, k in CHART]


def entry(text):
    """A FAKE_OUT_OF_SYNC or FAKE_MISSING entry as a status.resources item: a chart object by kind, or
    group/Kind/namespace/name."""
    if "/" in text:
        group, kind, namespace, name = text.split("/")
        return {**({"group": group} if group else {}), "version": "v1", "kind": kind, "namespace": namespace, "name": name,
                "requiresPruning": True}
    group, version, kind = next(c for c in CHART if c[2] == text)
    return {**({"group": group} if group else {}), "version": version, "kind": kind, "namespace": NS, "name": APP}


def identity(resource):
    return tuple(resource.get(k) or "" for k in ("group", "kind", "namespace", "name"))


def tick():
    """One poll's worth of controller progress toward the Application's current digest."""
    app = state["app"]
    spec, status = app["spec"], app.setdefault("status", {})
    want = digest_of(spec["source"])
    mode = env("FAKE_CONTROLLER", "normal")
    dep = state["deployment"]
    if dep and dep.get("lag"):
        dep["lag"] -= 1
    if dep and dep.get("stale"):
        dep["stale"].pop(0)
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
                  "destination": spec["destination"]}}, conditions=[],
                  resources=resources({k for _, _, k in CHART} if dep is None else {"Deployment"}))
    if step == 1:
        app["operation"] = operation
        status["operationState"] = {"phase": "Running", "operation": operation}
        status["health"] = {"status": "Progressing"}
        return
    current = status.get("operationState") or {}
    # The running operation completes; one that started and completed between two polls is this new one.
    operation = current["operation"] if current.get("phase") == "Running" else operation
    app.pop("operation", None)  # a completed operation is cleared (setOperationState)
    result = {"revision": revision, "source": copy.deepcopy(operation["sync"]["source"])}
    if want in env("FAKE_SYNC_FAILS", "").split(","):
        status["operationState"] = {"phase": "Failed", "operation": operation, "message": "one or more objects failed to apply",
                                    "syncResult": result}
        status["conditions"] = [{"type": "SyncError", "message": "Failed sync attempt: one or more objects failed to apply"}]
        return
    status["operationState"] = {"phase": "Succeeded", "operation": operation, "syncResult": result}
    status["sync"]["status"] = "Synced"
    status["resources"] = resources(set())
    image = spec["source"]["helm"]["valuesObject"]["image"]["repository"] + "@" + want
    if dep is None:
        dep = state["deployment"] = {"image": image, "revision": 1, "since": step, "generation": 1}
    elif dep["image"] != image:
        # The template changes now; the deployment controller observes it FAKE_OBSERVE_LAG polls later.
        dep.update(image=image, previous=dep["image"], revision=dep["revision"] + 1, since=step, generation=dep.get("generation", 1) + 1,
                   lag=int(env("FAKE_OBSERVE_LAG", "0")), stale=[r == "1" for r in env("FAKE_STALE_DEADLINE", "").split(",") if r],
                   shown=progressing(dep), deadline=False)
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


def workload():
    """The Deployment and HPA, as the get the deploy polls with returns them."""
    dep = state["deployment"]
    generation, lag = dep.get("generation", 1), dep.get("lag", 0)
    meta = {"name": APP, "namespace": NS}
    shown = dep["shown"] if lag or (dep.get("stale") or [False])[0] else progressing(dep)
    return [{"apiVersion": "apps/v1", "kind": "Deployment", "metadata": dict(meta, generation=generation,
             annotations={"deployment.kubernetes.io/revision": str(dep["revision"])}),
             "spec": {"replicas": 1, "template": {"spec": {"containers": [{"name": c, "image": dep["image"]} for c in CONTAINERS]}}},
             "status": {"observedGeneration": generation - 1 if lag else generation, "replicas": 1, "updatedReplicas": 1,
                        "availableReplicas": ready(), "readyReplicas": ready(),
                        "conditions": [{"type": "Progressing", "reason": shown}]}},
            {"apiVersion": "autoscaling/v2", "kind": "HorizontalPodAutoscaler", "metadata": meta,
             "spec": {"minReplicas": 1, "maxReplicas": 3}, "status": {"currentReplicas": 1}}]


OTHER_COMMIT = "f" * 40
OTHER_DIGEST = "sha256:" + "0" * 64
BUSYBOX = "public.ecr.aws/docker/library/busybox@" + OTHER_DIGEST


# Self-heal re-syncs an Application that stays OutOfSync with v3.5.3's default backoff (2 s, factor 3, cap
# 300 s): at 2, 8, 26, 80 and 242 s, so these 5-second polls after the sync.
SELF_HEAL_POLLS = (1, 2, 6, 16, 49)


def after_sync(app, items):
    """FAKE_OUT_OF_SYNC, FAKE_MISSING, FAKE_DRIFT: once the sync of FAKE_SKEW_DIGEST succeeded."""
    status, scoped = app["status"], env("FAKE_SKEW_DIGEST")
    op = status.get("operationState") or {}
    if op.get("phase") != "Succeeded" or digest_of((op.get("syncResult") or {}).get("source")) != scoped \
            or digest_of(app["spec"]["source"]) != scoped:
        return
    listed = [entry(e) for e in filter(None, env("FAKE_OUT_OF_SYNC", "").split(","))]
    if env("FAKE_MISSING"):
        items[:] = [i for i in items if i["kind"] != env("FAKE_MISSING")]
        listed.append(entry(env("FAKE_MISSING")))
    if env("FAKE_DRIFT") == "previous":
        previous = state["deployment"].get("previous") or "none"
        next(i for i in items if i["kind"] == "Deployment")["spec"]["template"]["spec"]["containers"][0]["image"] = previous
        status["summary"] = {"images": [previous]}
        listed += [entry("Deployment")] if state["polls"] % 2 else []
    if not listed:
        return
    status["sync"]["status"] = "OutOfSync"
    entries = {identity(r): r for r in status.get("resources") or []}
    for resource in listed:
        entries.setdefault(identity(resource), resource)["status"] = "OutOfSync"
    status["resources"] = list(entries.values())
    since = state.setdefault("synced_at", {}).setdefault(scoped, state["polls"])
    if env("FAKE_OUT_OF_SYNC") and state["polls"] - since in SELF_HEAL_POLLS:
        app["operation"] = copy.deepcopy(op["operation"])
        status["operationState"] = {"phase": "Running", "operation": copy.deepcopy(op["operation"])}


def skew(app, items):
    """FAKE_SKEW: one falsehood in an answer whose Application has a sync result and a Deployment."""
    name, status = env("FAKE_SKEW", ""), app["status"]
    op = status.get("operationState") or {}
    dep = next((i for i in items if i["kind"] == "Deployment"), None)
    if not name or "syncResult" not in op or not dep or digest_of(app["spec"]["source"]) != env("FAKE_SKEW_DIGEST"):
        return
    sync, result = op["operation"]["sync"], op["syncResult"]
    extra = {"name": "replicaCount", "value": "0"}
    template = dep["spec"]["template"]["spec"]
    unknown = {"HorizontalPodAutoscaler": "OutOfSync", "Deployment": "Unknown"}
    {
        "sync": lambda: status["sync"].update(status="OutOfSync"),
        "unknown": lambda: [status["sync"].update(status="OutOfSync")] + [
            r.update(status=unknown[r["kind"]]) for r in status["resources"] if r["kind"] in unknown],
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
        "image": lambda: template["containers"][0].update(image=template["containers"][0]["image"].split("@")[0] + "@" + OTHER_DIGEST),
        "sidecar": lambda: template["containers"].append({"name": "proxy", "image": BUSYBOX}),
        "init": lambda: template.update(initContainers=[{"name": "setup", "image": BUSYBOX}]),
        "observed": lambda: dep["status"].update(observedGeneration=dep["metadata"]["generation"] - 1),
        "ready": lambda: dep["status"].update(readyReplicas=0),
        "updated": lambda: dep["status"].update(replicas=2, availableReplicas=2),
        "scaled": lambda: dep["spec"].update(replicas=2),
        "unavailable": lambda: dep["status"].update(availableReplicas=0),
        "hpa": lambda: items.remove(next(i for i in items if i["kind"] == "HorizontalPodAutoscaler")),
    }[name]()


def clock():
    """The build's fake clock (the date and sleep stubs keep it), or 0 outside the runtime test."""
    return int(Path(env("FAKE_CLOCK")).read_text()) if env("FAKE_CLOCK") else 0


# --- load test ----------------------------------------------------------------------------------------
def running():
    job = state["job"] or {}
    return bool(job.get("pods")) and not job.get("deleted")


def hpa_read():
    """One read of the HPA's status: "<current> <desired> <cpu %>", advanced while the load Job runs."""
    hpa, mode = state["hpa"], env("FAKE_HPA", "scales")
    if mode == "at-two":
        hpa.update(current=max(hpa["current"], 2), desired=max(hpa["desired"], 2))
    if running() and mode == "scales":
        hpa["reads"] += 1
        after = int(env("FAKE_HPA_AFTER", "2"))
        if hpa["reads"] == after:
            hpa["desired"] = 3
        elif hpa["reads"] > after:
            hpa["current"] = hpa["desired"] = 3
    hpa["max_current"], hpa["max_desired"] = max(hpa["max_current"], hpa["current"]), max(hpa["max_desired"], hpa["desired"])
    cpu = (45 if mode == "never" else 240 // hpa["current"]) if running() else 3
    return f'{hpa["current"]} {hpa["desired"]} {cpu}'


def create_job(text):
    """kubectl create -f - of the load Job; Pod Security restricted decides whether its Pod can run."""
    docs = [d for d in yaml.safe_load_all(text) if d]
    if [d.get("kind") for d in docs] != ["Job"] or docs[0]["metadata"].get("name") != "finrisk-load" \
            or docs[0]["metadata"].get("namespace", NS) != NS:
        unsupported()
    if not allowed("create", "jobs.batch", "", namespace) or env("FAKE_JOB") == "create-fails":
        forbidden("create", "jobs.batch")
    labels = {"labels": docs[0]["metadata"].get("labels") or {}, "pod_labels": docs[0]["spec"]["template"].get("metadata", {}).get(
        "labels") or {}}
    if env("FAKE_JOB") == "exists" and not state["job"]:
        state["job"] = {"image": "left over by an earlier build", "pods": 1, "created": clock(), **labels}
    if state["job"] and not state["job"].get("gone"):
        done(1, err='Error from server (AlreadyExists): jobs.batch "finrisk-load" already exists\n')
    template = docs[0]["spec"]["template"]
    admitted = all(restricted(template).values())
    state["job"] = {"image": template["spec"]["containers"][0]["image"], "pods": int(admitted), "created": clock(),
                    "spec": docs[0]["spec"], **labels}
    done(out="job.batch/finrisk-load created\n")


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
    # Without the ServiceMonitor, Prometheus has no target for the app.
    scenario = "unscraped" if env("FAKE_MISSING") == "ServiceMonitor" else env("FAKE_PROM", "ok")

    def log_message(self, *_):
        pass

    def answer(self, query, now):
        served = state["requests"]
        app = 'service="finrisk-inference"' in query or "http_target" in query or "finrisk_" in query
        if self.scenario == "unscraped" and app:
            return None
        if re.search(r"\[(\d+)s\]\)\)$", query):
            return self.over_load_interval(query, now)
        if query.startswith("sum(rate(http_server_duration_milliseconds_count{") and 'http_status_code="200"}[1m]))' in query:
            return 80 if running() and env("FAKE_PROM_LOAD") != "no-requests" else 0
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
        if query in (KSM % ("deployment_status_replicas_available", "deployment"),
                     KSM % ("horizontalpodautoscaler_status_current_replicas", "horizontalpodautoscaler")):
            return None if self.scenario == "no-ksm" else 1
        return None

    def over_load_interval(self, query, now):
        """kube-state-metrics over [<n>s]: the HPA as the load drove it, replicas available throughout; a
        window reaching back before the Job also holds an earlier load test's 3 replicas."""
        hpa, mode = state["hpa"], env("FAKE_PROM_LOAD", "ok")
        series = {("horizontalpodautoscaler_status_current_replicas", "horizontalpodautoscaler"):
                  1 if mode == "ksm-unscaled" else hpa["max_current"],
                  ("horizontalpodautoscaler_status_desired_replicas", "horizontalpodautoscaler"):
                  1 if mode == "ksm-unscaled" else hpa["max_desired"],
                  ("deployment_status_replicas_available", "deployment"): hpa["max_current"]}
        m = re.fullmatch(r"(max|min)\(\1_over_time\((.*)\[(\d+)s\]\)\)", query)
        found = next((key for key in series if m and m[2] == KSM % key), None)
        if not found:
            return None
        # The true load interval at this query: the build's seconds since the Job was created, plus the
        # script's own time since it started.
        interval = LOAD["base"] + now
        state.setdefault("windows", []).append([int(m[3]), interval])
        if m[1] == "min":
            return 0 if mode == "outage" else 1
        return max(series[found], 3) if int(m[3]) > interval + 1 else series[found]

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path != "/api/v1/query":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(url.query)
        value = self.answer(params["query"][0], float(params.get("fake_now", ["0"])[0]))
        result = [] if value is None else [{"metric": {}, "value": [1.7e9, str(value)]}]
        data = json.dumps({"status": "success", "data": {"resultType": "vector", "result": result}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(data)


# The PromQL script's clock: sleep advances it, so its polling bound is exercised without waiting. Each
# query carries the script's time (fake_now) for the stand-in to check the load interval's window against.
FAKE_CLOCK = ("import time as _t\n_now = [0.0]\n_t.monotonic = lambda: _now[0]\n_t.sleep = lambda s: _now.__setitem__(0, _now[0] + s)\n"
              "import urllib.request as _u\n_open = _u.urlopen\n"
              "_u.urlopen = lambda url, *a, **k: _open(url + '&fake_now=%r' % _now[0], *a, **k)\n")
# kube-state-metrics' series for the release, as its scrape job labels them.
KSM = 'kube_%s{job="kube-state-metrics",namespace="finrisk",%s="finrisk-inference"}'
LOAD = {"base": 0}


def run_in_pod(script, argv):
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
        reachable = SERVICES.get(service[1], {}).get(str(url.port or 80), False) and env("FAKE_MISSING") != "Service"
        handler = InferenceApi
    else:
        reachable = url.scheme == "http" and url.netloc == PROMETHEUS and not url.path and env("FAKE_PROM") != "unreachable"
        handler = PrometheusApi
        script = FAKE_CLOCK + script
        if argv:  # the load test's window: the seconds since the Job was created, by the build's clock
            LOAD["base"] = clock() - (state["job"] or {}).get("created", clock())
            state.setdefault("load_args", []).append((argv, LOAD["base"]))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        address = "http://127.0.0.1:%d" % (server.server_address[1] if reachable else closed_port())
        script = script.replace(line[0], f'{line[0].split(" = ")[0]} = "{address}"', 1)
        # No proxy may see the request; no_proxy=* also stops urllib using macOS system proxies.
        run_env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
        run_env["no_proxy"] = "*"
        result = subprocess.run([sys.executable, "-I", "-S", "-", *argv], input=script, env=run_env, capture_output=True,
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
if positional == ["get", f"applications.argoproj.io/{APP}", f"deployment/{APP}", f"hpa/{APP}"] \
        and output == "json" and "--ignore-not-found" in flags:
    for resource in ("applications.argoproj.io", "deployments.apps", "horizontalpodautoscalers.autoscaling"):
        if not allowed("get", resource, APP, namespace):
            forbidden("get", resource, APP)
    state["polls"] += 1
    tick()
    app = copy.deepcopy(state["app"])
    items = [app] + (workload() if state["deployment"] else [])
    after_sync(app, items)
    skew(app, items)
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
if verb == "exec" and args[command_end + 1:command_end + 3] == ["python", "-"]:
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
    run_in_pod(sys.stdin.read(), args[command_end + 3:])
if positional == ["get", "hpa", APP] and namespace == NS and output == HPA_JSONPATH:
    if not allowed("get", "hpa", APP, namespace):
        forbidden("get", "horizontalpodautoscalers.autoscaling", APP)
    synced = ((state["app"].get("status") or {}).get("operationState") or {}).get("syncResult") or {}
    missing = env("FAKE_MISSING") == "HorizontalPodAutoscaler" and digest_of(synced.get("source")) == env("FAKE_SKEW_DIGEST")
    if state["deployment"] is None or missing:
        done(1, err=f'Error from server (NotFound): horizontalpodautoscalers.autoscaling "{APP}" not found\n')
    done(out=hpa_read())
if positional == ["create"] and option("-f") == "-":
    create_job(sys.stdin.read())
if positional == ["delete", "job", "finrisk-load"] and namespace == NS and {"--ignore-not-found", "--wait=false"} <= set(flags):
    if not allowed("delete", "jobs.batch", "finrisk-load", namespace) or env("FAKE_JOB") == "delete-fails":
        forbidden("delete", "jobs.batch", "finrisk-load")
    job = state["job"]
    if not job or job.get("deleted") or job.get("gone"):
        done()
    job["deleted"] = True
    done(out='job.batch "finrisk-load" deleted\n')
if positional == ["get", "events"] and namespace == NS and option("--sort-by") == ".lastTimestamp":
    # The load test's diagnosis when it fails: why the Job runs no Pod, or what the HPA saw.
    job = state["job"] or {}
    events = ["Warning  FailedCreate  job/finrisk-load  Error creating: pods \"finrisk-load-7xk2p\" is forbidden: "
              "violates PodSecurity \"restricted:latest\"" if job and not job.get("pods") else
              "Normal  SuccessfulCreate  job/finrisk-load  Created pod: finrisk-load-7xk2p" if job else ""]
    events.append("Normal  SuccessfulRescale  horizontalpodautoscaler/finrisk-inference  New size: 3"
                  if state["hpa"]["max_current"] > 1 else "")
    done(out="LAST SEEN  TYPE  REASON  OBJECT  MESSAGE\n" + "".join(e + "\n" for e in events if e))
if positional == ["get", "jobs,pods"] and namespace == NS and re.fullmatch(r"[\w./-]+=[\w.-]+", option("-l") or "") \
        and output == "name":
    if env("FAKE_JOB") == "list-fails":
        done(1, err="Unable to connect to the server: net/http: request canceled (Client.Timeout exceeded while awaiting headers)\n")
    job = state["job"]
    if not job or job.get("gone"):
        done()
    key, _, value = option("-l").partition("=")
    pod = "pod/finrisk-load-7xk2p\n" if job.get("pods") and job.get("pod_labels", {}).get(key) == value else ""
    if not job.get("deleted"):
        done(out=("job.batch/finrisk-load\n" if job.get("labels", {}).get(key) == value else "") + pod)
    # The Job object goes at once; its Pod terminates by the next read (never, when stuck).
    job["reads"] = job.get("reads", 0) + 1
    if env("FAKE_JOB") != "stuck" and (job["reads"] > 1 or not job.get("pods")):
        job["gone"] = True
        done()
    done(out=pod)
unsupported()
