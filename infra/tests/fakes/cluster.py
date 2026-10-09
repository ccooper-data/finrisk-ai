#!/usr/bin/env python3
"""Stateful kubectl and helm stand-in for executing the bootstrap buildspec in tests.

Invoked as `cluster.py kubectl ARGS` or `cluster.py helm ARGS`. Models what the bootstrap depends on:
namespaces and their labels, the exposure guard (a server-side dry run is admitted until the applied
policy loads, then judged by it), the Argo CD install and its settings, the Pods' images, the
monitoring Application's progress, the generated Prometheus StatefulSet, a Prometheus `up` query
through the API server proxy, and the inference Application read back as applied. Applies that need
CRDs fail before helm has installed Argo CD, and the inference Application fails before its AppProject
exists. The calls
a wait polls with must carry a request timeout (the buildspec's kq). Any kubectl or helm call it does
not model fails, so a new call in the buildspec cannot pass unnoticed. With FAKE_LOG set, every call
is also appended there, so a test can order them against the other stubs.

Scenario knobs (environment):
  FAKE_AUTH_AFTER=n          `auth can-i` answers no for the first n calls
  FAKE_NODE_TYPES=a,b        node instance types (default t3.large)
  FAKE_GUARD                 ok | admits-loadbalancer | admits-external-ips | admits-ingress | admits-pvc |
                             denies-clusterip | never-loads | apiserver-external-ips (DenyServiceExternalIPs
                             denies first)
  FAKE_GUARD_LOAD_AFTER=n    dry-run rounds before the policy takes effect (default 1)
  FAKE_HELM_PENDING=1        a release is left pending by an interrupted install
  FAKE_HELM_FAIL=1           the helm install fails
  FAKE_UNPINNED=<namespace>  one Pod there runs an image by tag
  FAKE_SERVER_REPLICAS=n     argocd-server replicas (default 0); FAKE_EXPOSED=1 adds a LoadBalancer Service;
                             FAKE_INGRESS=1 adds an Ingress
  FAKE_ADMIN=v               argocd-cm admin.enabled (default false)
  FAKE_APP_NAMESPACES=v      argocd-cmd-params-cm application.namespaces (default finrisk)
  FAKE_REDIS_SECRET=v        the Secret argocd-redis reads REDIS_PASSWORD from (default argocd-redis; "" none)
  FAKE_NO_REDIS_SECRET=1     the Secret argocd/argocd-redis does not exist
  FAKE_MONITORING            ok | never | outofsync | degraded | healthy-running | degraded-succeeded;
                             FAKE_MONITORING_AFTER=n polls first (default 3)
  FAKE_LIFECYCLE=1           the generated Prometheus has --web.enable-lifecycle
  FAKE_NO_KSM=1              kube-state-metrics is not up in Prometheus
  FAKE_REPO_OOM=1            the repo-server restarted once after an OOM kill
  FAKE_NO_TOP=1              kubectl top fails (metrics-server not serving)
  FAKE_GITOPS_DRIFT=1        the inference Application reads back with another targetRevision
"""
import fcntl
import json
import os
import re
import sys

STATE = os.environ["FAKE_STATE"]
# The buildspec pipes one kubectl into another, so two of these can run at once. Each reads its
# input first (the upstream one may need the lock to produce it), then holds the state until it exits.
STDIN = sys.stdin.read() if "-" in sys.argv[2:] else ""
LOCK = open(STATE + ".lock", "w")
fcntl.flock(LOCK, fcntl.LOCK_EX)
state = json.load(open(STATE)) if os.path.exists(STATE) else {
    "calls": [], "namespaces": {}, "applied": [], "guard": False, "rounds": 0, "auth": 0, "argocd": False,
    "polls": 0, "crd": 0, "target": None, "gitops": None}
tool, args = sys.argv[1], sys.argv[2:]
state["calls"].append(" ".join([tool, *args]))
env = os.environ.get
if env("FAKE_LOG"):
    with open(env("FAKE_LOG"), "a") as log:
        log.write(state["calls"][-1] + "\n")
ARGOCD = "quay.io/argoproj/argocd:v3.5.3@sha256:" + "d" * 64
REDIS = "public.ecr.aws/docker/library/redis:8.6.4-alpine@sha256:" + "2" * 64
PODS = {
    "argocd": [ARGOCD, ARGOCD, ARGOCD, REDIS, ARGOCD],
    "monitoring": ["quay.io/prometheus-operator/prometheus-operator:v0.94.1@sha256:" + "7" * 64,
                   "registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.20.0@sha256:" + "4" * 64,
                   "quay.io/prometheus-operator/prometheus-config-reloader:v0.94.1@sha256:" + "0" * 64,
                   "quay.io/prometheus/prometheus:v3.15.0-distroless@sha256:" + "b" * 64,
                   "quay.io/prometheus-operator/prometheus-config-reloader:v0.94.1@sha256:" + "0" * 64],
}
DENIED = "ValidatingAdmissionPolicy 'finrisk-no-external-exposure' with binding 'finrisk-no-external-exposure' denied request: "
MESSAGES = {"Service": "Only ClusterIP Services without externalIPs are allowed on this cluster.",
            "Ingress": "Ingress and PersistentVolumeClaim objects are not allowed on this cluster: they can create AWS "
                       "resources outside Terraform state."}


def done(code=0, out="", err=""):
    json.dump(state, open(STATE, "w"))
    print(out, end="")
    print(err, end="", file=sys.stderr)
    sys.exit(code)


def unsupported():
    done(1, err=f"fake {tool}: unsupported call: {' '.join(args)}\n")


if tool == "helm":
    if args == ["version"]:
        done(out='version.BuildInfo{Version:"v4.3.0"}\n')
    if args == ["list", "--namespace", "argocd", "--pending", "--short"]:
        done(out="argocd\n" if env("FAKE_HELM_PENDING") else "")
    expected = ["upgrade", "--install", "argocd", None, "--namespace", "argocd", "--values", None, "--server-side=true",
                "--wait", "--timeout", None, "--history-max", "3"]
    if len(args) != len(expected) or any(e is not None and a != e for a, e in zip(args, expected)):
        unsupported()
    if not (os.path.isfile(args[3]) and os.path.isfile(args[7])):
        done(1, err="Error: chart or values file not found\n")
    if "pod-security.kubernetes.io/enforce" not in state["namespaces"].get("argocd", {}):
        done(1, err="Error: namespace argocd is not ready\n")
    if env("FAKE_HELM_FAIL"):
        done(1, err="Error: UPGRADE FAILED: context deadline exceeded\n")
    state["argocd"] = True
    done(out="Release \"argocd\" has been upgraded. Happy Helming!\n")

# kubectl: flags, then positional words
namespace, output, files, selector, positional, i = "default", "", [], "", [], 0
while i < len(args):
    a = args[i]
    if a in ("-n", "--namespace", "-o", "-f", "-l"):
        value = args[i + 1]
        if a in ("-n", "--namespace"):
            namespace = value
        elif a == "-o":
            output = value
        elif a == "-f":
            files.append(value)
        else:
            selector = value
        i += 2
        continue
    if not a.startswith("-"):
        positional.append(a)
    i += 1
verb = positional[0] if positional else ""
flags = [a for a in args if a.startswith("--")]
# What a wait polls with: without a request timeout, one hung call could hold the wait past its bound.
POLLS = (["auth", "can-i"], ["get", "crd"], ["get", "applications.argoproj.io"])
polled = any(positional[:len(p)] == p for p in POLLS) or "--raw" in flags or "--dry-run=server" in flags
if polled and "--request-timeout=10s" not in flags:
    state.setdefault("refused", []).append(" ".join(args))
    done(1, err=f"fake kubectl: a polled call without --request-timeout: {' '.join(args)}\n")

if verb == "version":
    done(out="Client Version: v1.35.9\n")
if positional == ["auth", "can-i", "create", "namespaces"]:
    state["auth"] += 1
    done(out="yes\n" if state["auth"] > int(env("FAKE_AUTH_AFTER", "0")) else "no\n")
if positional == ["get", "nodes"]:
    types = (env("FAKE_NODE_TYPES") or "t3.large").split(",")
    if "instance-type" in output:
        done(out="".join(t + "\n" for t in types))
    if "allocatable" in output:
        done(out="35 1930m 7268356Ki")
if positional[:2] == ["create", "namespace"] and "--dry-run=client" in flags:
    done(out=f"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {positional[2]}\n")
if verb == "apply" and files == ["-"]:
    name = re.search(r"^  name: (\S+)$", STDIN, re.M)[1]
    state["namespaces"].setdefault(name, {})
    done(out=f"namespace/{name} configured\n")
if positional[:2] == ["label", "namespace"]:
    if positional[2] not in state["namespaces"]:
        done(1, err=f'Error from server (NotFound): namespaces "{positional[2]}" not found\n')
    state["namespaces"][positional[2]].update(kv.split("=", 1) for kv in positional[3:])
    done(out=f"namespace/{positional[2]} labeled\n")
if verb == "apply" and "--server-side" in flags and len(files) == 1:
    name = os.path.basename(files[0])
    text = open(files[0]).read()
    if name != "cluster-guards.yaml" and not state["argocd"]:
        done(1, err="error: resource mapping not found: no matches for kind in version argoproj.io/v1alpha1\n")
    if name == "gitops.yaml" and "argocd-projects.yaml" not in state["applied"]:
        done(1, err='Error from server: applications.argoproj.io "finrisk-inference": project finrisk not found\n')
    state["applied"].append(name)
    if name == "cluster-guards.yaml":
        state["guard"] = True
    target = re.search(r"^    targetRevision: (\S+)$", text, re.M)
    if name == "monitoring-app.yaml":
        state["target"] = target[1]
    if name == "gitops.yaml":
        state["gitops"] = {"text": text, "project": re.search(r"^  project: (\S+)$", text, re.M)[1], "target": target[1].strip('"'),
                           "repository": re.search(r"^          repository: (\S+)$", text, re.M)[1].strip('"')}
    done(out=f"{name} serverside-applied\n")
if positional == ["create"] and "--dry-run=server" in flags and files == ["-"]:
    if namespace not in state["namespaces"]:
        done(1, err=f'Error from server (NotFound): namespaces "{namespace}" not found\n')
    probe = json.loads(STDIN)
    kind, spec = probe["kind"], probe["spec"]
    if probe["apiVersion"] != {"Ingress": "networking.k8s.io/v1"}.get(kind, "v1") or probe["metadata"] != {"name": "finrisk-guard-probe"}:
        done(1, err=f'error: resource mapping not found for kind "{kind}" in version "{probe["apiVersion"]}"\n')
    resource, name = {"Service": ("services", "service"), "Ingress": ("ingresses.networking.k8s.io", "ingress.networking.k8s.io"),
                      "PersistentVolumeClaim": ("persistentvolumeclaims", "persistentvolumeclaim")}[kind]
    guard = env("FAKE_GUARD", "ok")
    if spec.get("type") == "LoadBalancer":
        state["rounds"] += 1
    loaded = state["guard"] and guard != "never-loads" and state["rounds"] > int(env("FAKE_GUARD_LOAD_AFTER", "1"))
    if spec.get("externalIPs") and guard == "apiserver-external-ips":
        done(1, err='Error from server (Forbidden): services "finrisk-guard-probe" is forbidden: '
                    'Use of external IPs is denied by admission control\n')
    if kind == "Service":
        deny = {"LoadBalancer": guard != "admits-loadbalancer"}.get(
            spec["type"], (guard != "admits-external-ips") if spec.get("externalIPs") else guard == "denies-clusterip")
    else:
        deny = guard != {"Ingress": "admits-ingress", "PersistentVolumeClaim": "admits-pvc"}[kind]
    if loaded and deny:
        done(1, err=f'Error from server (Invalid): {resource} "finrisk-guard-probe" is invalid: : {DENIED}{MESSAGES.get(kind, MESSAGES["Ingress"])}\n')
    done(out=f"{name}/finrisk-guard-probe\n")
if positional == ["get", "pods"] and not selector:
    if "restarts=" in output:
        done(out="".join(f"{namespace}-pod-{n} restarts=0 last=\n" for n in range(3)))
    images = list(PODS.get(namespace, [])) if state["argocd"] else []
    if images and env("FAKE_UNPINNED") == namespace:
        images[1] = images[1].split("@")[0]
    done(out="".join(i + "\n" for i in images))
if positional == ["get", "pods"] and selector == "app.kubernetes.io/name=argocd-repo-server":
    oom = env("FAKE_REPO_OOM")
    done(out=("1" if oom else "0") if "restartCount" in output else ("OOMKilled" if oom else ""))
if positional == ["get", "ingresses"] and "--all-namespaces" in flags:
    done(out="ingress.networking.k8s.io/finrisk/exposed\n" if env("FAKE_INGRESS") else "")
if positional == ["get", "services"] and "--all-namespaces" in flags:
    done(out="ClusterIP\nClusterIP\nClusterIP\n" + ("LoadBalancer\n" if env("FAKE_EXPOSED") else ""))
if namespace == "argocd" and state["argocd"] and positional[:1] == ["get"]:
    answers = {("deployment", "argocd-server"): env("FAKE_SERVER_REPLICAS", "0"),
               ("configmap", "argocd-cm"): env("FAKE_ADMIN", "false"),
               ("configmap", "argocd-cmd-params-cm"): env("FAKE_APP_NAMESPACES", "finrisk"),
               ("deployment", "argocd-redis"): env("FAKE_REDIS_SECRET", "argocd-redis"),
               ("secret", "argocd-redis"): "secret/argocd-redis\n",
               ("statefulset", "argocd-application-controller"): ARGOCD}
    if positional[1:3] == ["secret", "argocd-redis"] and env("FAKE_NO_REDIS_SECRET"):
        done(1, err='Error from server (NotFound): secrets "argocd-redis" not found\n')
    if tuple(positional[1:3]) in answers:
        done(out=answers[tuple(positional[1:3])])
if verb == "rollout" and namespace == "argocd" and state["argocd"]:
    done(out=f'{positional[2]} successfully rolled out\n')
if verb == "wait" and "--for=condition=Established" in flags and state["argocd"]:
    done(out="".join(f"{c} condition met\n" for c in positional[1:]))
if positional == ["get", "applications.argoproj.io", "finrisk-monitoring"] and "monitoring-app.yaml" in state["applied"]:
    if "health.status" in output:
        state["polls"] += 1
        ready = state["polls"] > int(env("FAKE_MONITORING_AFTER", "3"))
        done(out={"never": "Progressing|Running|OutOfSync", "degraded": "Degraded|Failed|OutOfSync",
                  "healthy-running": "Healthy|Running|Synced", "degraded-succeeded": "Degraded|Succeeded|Synced",
                  "outofsync": "Healthy|Succeeded|OutOfSync" if ready else "Progressing|Running|OutOfSync"}.get(
            env("FAKE_MONITORING", "ok"), "Healthy|Succeeded|Synced" if ready else "Progressing|Running|OutOfSync"))
    if "conditions" in output:
        done(out='[{"type":"SyncError","message":"one or more objects failed to apply"}]\nretrying\n')
    if output in ("jsonpath={.spec.source.targetRevision}", "jsonpath={.status.operationState.syncResult.revision}"):
        done(out=state["target"])
if positional == ["get", "applications.argoproj.io", "finrisk-inference"] and namespace == "finrisk" and state["gitops"]:
    app = state["gitops"]
    if output == ("jsonpath={.spec.project} {.spec.source.targetRevision} {.spec.source.helm.valuesObject.image.repository} "
                  "{.status.conditions[*].type}"):
        target = "f" * 40 if env("FAKE_GITOPS_DRIFT") else app["target"]
        done(out=f'{app["project"]} {target} {app["repository"]} ComparisonError')
if positional == ["get", "crd", "servicemonitors.monitoring.coreos.com"]:
    # Argo CD applies the chart's CRDs first; one poll after the Application is applied, it is established.
    if "monitoring-app.yaml" in state["applied"]:
        state["crd"] += 1
        if state["crd"] > 1:
            done(out="True")
    done(1, err='Error from server (NotFound): customresourcedefinitions "servicemonitors.monitoring.coreos.com" not found\n')
if namespace == "monitoring" and positional in (["get", "pods,deployments,statefulsets"], ["get", "events"]):
    done(out="NAME  READY  STATUS\nprometheus-monitoring-0  0/2  Pending\n")
if positional == ["get", "statefulset", "prometheus-monitoring"] and namespace == "monitoring" and state["polls"]:
    done(out='["--config.file=/etc/prometheus/config_out/prometheus.env.yaml","--web.listen-address=:9090"'
             + (',"--web.enable-lifecycle"' if env("FAKE_LIFECYCLE") else "") + '] ["--reload-method=signal"]')
if positional[:1] == ["get"] and "--raw" in flags:
    raw = args[args.index("--raw") + 1]
    if raw != "/api/v1/namespaces/monitoring/services/monitoring-prometheus:9090/proxy/api/v1/query?query=up":
        unsupported()
    jobs = ["prometheus", "config-reloader", "monitoring-operator"] + ([] if env("FAKE_NO_KSM") else ["kube-state-metrics"])
    done(out=json.dumps({"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"__name__": "up", "job": j, "namespace": "monitoring"}, "value": [1.0, "1"]} for j in jobs]}}))
if verb == "top":
    if env("FAKE_NO_TOP"):
        done(1, err="error: Metrics API not available\n")
    done(out="NAMESPACE  NAME  CPU(cores)  MEMORY(bytes)\nargocd  argocd-application-controller-0  12m  140Mi\n")
unsupported()
