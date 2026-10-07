#!/usr/bin/env python3
# Executes the rendered bootstrap buildspec against a stateful fake API (fakes/cluster.py, standing in
# for kubectl and helm) to check its control flow end to end: the checksums of downloads and embedded
# files before use, the order of the add-ons, the exposure guard's live proof, every fail-closed
# check (each with a scenario that trips it), the bounded waits and their request timeouts, and the
# evidence lines. Time is a fake clock that only `sleep` advances, so each wait's bound is exercised
# exactly and fast. The embedded infra/k8s files are rendered as Terraform would (base64 of gzip,
# with their sha256).
import base64
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (ROOT / "infra/terraform/deploy/bootstrap-buildspec.yml.tftpl").read_text()
FAKE = ROOT / "infra/tests/fakes/cluster.py"
K8S = ROOT / "infra/k8s"
BUILD_TIMEOUT = int(re.search(r'resource "aws_codebuild_project" "k8s_bootstrap" \{.*?build_timeout\s+= (\d+)',
                              (ROOT / "infra/terraform/deploy_path.tf").read_text(), re.S)[1])
EMBEDDED = {"cluster_guards": "cluster-guards.yaml", "argocd_values": "argocd-values.yaml",
            "argocd_projects": "argocd-projects.yaml", "monitoring_app": "monitoring-app.yaml"}
URLS = {"kubectl": "https://dl.k8s.io/release/v1.35.9/bin/linux/amd64/kubectl",
        "helm": "https://get.helm.sh/helm-v4.3.0-linux-amd64.tar.gz",
        "argocd_chart": "https://github.com/argoproj/argo-helm/releases/download/argo-cd-10.9.6/argo-cd-10.9.6.tgz"}
START = 1_000_000
# As deploy_path.tf builds it: each file after a "#==> <file>" line, gzip, base64.
BUNDLE = base64.b64encode(gzip.compress("".join(f"#==> {f}\n" + (K8S / f).read_text() for f in EMBEDDED.values()).encode())).decode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def render(**override):
    # The fake curl writes each URL as the file's content, so these are the checksums of the downloads.
    values = {"cluster_name": "finrisk-ai-portfolio", "region": "us-east-1", "namespace": "finrisk",
              "argocd_namespace": "argocd", "monitoring_namespace": "monitoring", "node_instance_type": "t3.large",
              "kubectl_version": "v1.35.9", "helm_version": "v4.3.0", "argocd_chart_version": "10.9.6",
              **{f"{k}_sha256": sha(u.encode()) for k, u in URLS.items()}}
    for name, file in EMBEDDED.items():
        values[f"{name}_sha256"] = sha((K8S / file).read_bytes())
    values["k8s_bundle_b64"] = BUNDLE
    values.update(override)
    rendered = TEMPLATE
    for key, value in values.items():
        rendered = rendered.replace("${" + key + "}", value)
    rendered = rendered.replace("$${", "${")
    script = yaml.safe_load(rendered)["phases"]["build"]["commands"][0]
    # Absolute paths made relative to a scratch directory, as test_deploy_buildspec_runtime.py does.
    return re.sub(r"(?<=[\s\"'<>])/tmp/", "tmp/", script.replace("/opt/finrisk/bin", "bin"))


def stub(name, body):
    path = stubs / name
    path.write_text("#!/usr/bin/env bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def bootstrap(name, script=None, state=None, **env):
    """Runs the buildspec; returns exit code, output, the fake's state (with "log": every stubbed tool
    and fake call, in order) and the fake clock's seconds."""
    state = state or work / f"{name}.json"
    clock = work / f"{name}.clock"
    log = work / f"{name}.log"
    clock.write_text(str(START))
    cwd = work / name  # its own bin/ and tmp/, so concurrent scenarios never share a file
    cwd.mkdir()
    (cwd / "bootstrap.sh").write_text(script or default)
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
    run_env.update(PATH=f"{stubs}{os.pathsep}{os.environ['PATH']}", FAKE_STATE=str(state), FAKE_CLOCK=str(clock),
                   FAKE_LOG=str(log), FAKE_PYTHON=sys.executable, FAKE_CLUSTER=str(FAKE), **env)
    result = subprocess.run(["bash", "bootstrap.sh"], cwd=cwd, env=run_env, capture_output=True, text=True, timeout=600)
    recorded = json.loads(state.read_text()) if state.exists() else {"calls": [], "namespaces": {}, "applied": []}
    recorded["log"] = log.read_text().splitlines() if log.exists() else []
    return result.returncode, result.stdout + result.stderr, recorded, int(clock.read_text()) - START


def evidence(out):
    return re.findall(r"^FINRISK_EVIDENCE (.*)$", out, re.M)


def first(calls, prefix):
    return next((i for i, c in enumerate(calls) if c.startswith(prefix)), len(calls) + 1)


def stopped_before(state, prefix):
    """Nothing from `prefix` on happened."""
    return first(state["calls"], prefix) > len(state["calls"])


def verified_before_use(log):
    """Each download and each embedded file passed sha256sum before anything used it."""
    uses = {"tmp/kubectl": "install -m 0755 tmp/kubectl", "tmp/helm.tar.gz": "tar -xzOf tmp/helm.tar.gz",
            "tmp/finrisk/argo-cd.tgz": "helm upgrade --install argocd tmp/finrisk/argo-cd.tgz",
            **{f"tmp/finrisk/{f}": "kubectl --request-timeout=10s auth can-i" for f in EMBEDDED.values()}}
    return all(first(log, f"verified {path}") < first(log, use) < len(log) for path, use in uses.items())


HELM = "helm upgrade --install argocd"
PROJECTS = "kubectl apply --server-side --field-manager=finrisk-bootstrap --force-conflicts -f tmp/finrisk/argocd-projects.yaml"
DRY_RUN = "kubectl --request-timeout=10s -n finrisk create --dry-run=server"
checks = {}
work = Path(tempfile.mkdtemp(prefix="finrisk-bootstrap-test-"))
try:
    stubs = work / "stubs"
    stubs.mkdir()
    default = render()
    shell = default.replace(BUNDLE, "")
    checks["buildspec runs in the scratch directory (no cd, no absolute path left)"] = "/tmp/" not in shell \
        and "/opt/" not in shell and re.search(r"(^|[\s;&|(])(cd|pushd|popd)(\s|$)", shell, re.M) is None

    # Downloads, AWS and time are not under test; kubectl and helm are the fake (stdlib only, so it
    # starts without site packages). sha256sum checks for
    # real (GNU's --check --strict form), so a payload that differs from its embedded hash fails.
    stub("curl", 'out=""; url=""; while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift;; '
                 '--retry|--retry-max-time|--max-time) shift;; -*) ;; *) url="$1";; esac; shift; done; '
                 'printf "%s" "$url" > "$out"')
    stub("sha256sum", 'exec "$FAKE_PYTHON" -c \'import hashlib, os, sys\n'
                      'assert sys.argv[1:] == ["--check", "--strict"], sys.argv\n'
                      'bad = 0\n'
                      'for line in sys.stdin.read().splitlines():\n'
                      '    want, path = line.split("  ", 1)\n'
                      '    ok = hashlib.sha256(open(path, "rb").read()).hexdigest() == want\n'
                      '    print(path + (": OK" if ok else ": FAILED"))\n'
                      '    open(os.environ["FAKE_LOG"], "a").write(("verified " if ok else "mismatch ") + path + "\\n")\n'
                      '    bad += not ok\n'
                      'sys.exit(1 if bad else 0)\' "$@"')
    stub("tar", 'echo "tar $*" >> "$FAKE_LOG"; echo "helm binary"')
    stub("install", 'echo "install $*" >> "$FAKE_LOG"; tool="$(basename "${@: -1}")"; '
                    'printf \'#!/usr/bin/env bash\\nexec "$FAKE_PYTHON" -S "$FAKE_CLUSTER" %s "$@"\\n\' "$tool" > "${@: -1}"; chmod +x "${@: -1}"')
    stub("aws", "exit 0")
    stub("date", '[ "$1" = "+%s" ] || exit 1; cat "$FAKE_CLOCK"')
    stub("sleep", 'echo $(( $(cat "$FAKE_CLOCK") + $1 )) > "$FAKE_CLOCK"')
    stub("python3", 'exec "$FAKE_PYTHON" "$@"')

    # Every scenario has its own script, state and clock, so all but the re-run run concurrently.
    argocd_drift = {"unpinned-argocd": ({"FAKE_UNPINNED": "argocd"}, "Pods in argocd run images not pinned"),
                    "server-up": ({"FAKE_SERVER_REPLICAS": "1"}, "server_replicas=1"),
                    "exposed": ({"FAKE_EXPOSED": "1"}, "non_clusterip_services=1"),
                    "ingress": ({"FAKE_INGRESS": "1"}, "ingresses=1"),
                    "admin": ({"FAKE_ADMIN": "true"}, "admin_enabled=true"),
                    "any-namespace": ({"FAKE_APP_NAMESPACES": "*"}, "application_namespaces=*"),
                    "redis-unauthenticated": ({"FAKE_REDIS_SECRET": ""}, "redis_password_secret=\n"),
                    "no-redis-secret": ({"FAKE_NO_REDIS_SECRET": "1"}, 'secrets "argocd-redis" not found')}
    scenarios = {
        "ok": {}, "guard-slow": {"FAKE_GUARD_LOAD_AFTER": "3"}, "guard-apiserver": {"FAKE_GUARD": "apiserver-external-ips"},
        **{"guard-" + g: {"FAKE_GUARD": g} for g in ("admits-loadbalancer", "admits-external-ips", "admits-ingress",
                                                      "admits-pvc", "denies-clusterip", "never-loads")},
        "unauthorized": {"FAKE_AUTH_AFTER": "1000"}, "node-type": {"FAKE_NODE_TYPES": "t3.large,t3.small"}, "tampered": {},
        "unverified": {}, "no-request-timeout": {}, "helm-pending": {"FAKE_HELM_PENDING": "1"}, "helm-fails": {"FAKE_HELM_FAIL": "1"},
        **{name: env for name, (env, _) in argocd_drift.items()}, "monitoring-never": {"FAKE_MONITORING": "never"},
        **{"monitoring-" + m: {"FAKE_MONITORING": m} for m in ("degraded", "outofsync", "healthy-running", "degraded-succeeded")},
        "lifecycle": {"FAKE_LIFECYCLE": "1"}, "unpinned-monitoring": {"FAKE_UNPINNED": "monitoring"}, "no-ksm": {"FAKE_NO_KSM": "1"},
        "repo-oom": {"FAKE_REPO_OOM": "1"}, "no-top": {"FAKE_NO_TOP": "1"},
    }
    # Deliberately broken buildspecs: an embedded file that differs from its plan-time sha256, downloads
    # used without their checksum, and polled kubectl calls without a request timeout.
    fetch_check = '  echo "$3  $1" | sha256sum --check --strict\n'
    kq = 'kq() { "$K" --request-timeout=10s "$@"; }'
    scripts = {"tampered": render(monitoring_app_sha256=sha(b"something else")),
               "unverified": default.replace(fetch_check, "", 1) if fetch_check in default else "exit 99",
               "no-request-timeout": default.replace(kq, 'kq() { "$K" "$@"; }', 1) if kq in default else "exit 99"}
    with ThreadPoolExecutor(max_workers=8) as pool:
        runs = dict(zip(scenarios, pool.map(lambda n: bootstrap(n, script=scripts.get(n), **scenarios[n]), scenarios)))

    code, out, state, seconds = runs["ok"]
    lines = evidence(out)
    calls = state["calls"]
    checks["installs everything and ends with bootstrap=complete"] = code == 0 and bool(lines) \
        and lines[-1] == "bootstrap=complete namespace=finrisk"
    checks["evidence: node, guard, argocd, monitoring, then the terminal line"] = [l.split()[0] for l in lines] \
        == ["node", "guard", "argocd", "monitoring", "bootstrap=complete"]
    checks["node evidence: the planned type and its allocatable capacity"] = bool(lines) and lines[0] \
        == "node count=1 instance_type=t3.large allocatable_pods=35 allocatable_cpu=1930m allocatable_memory=7268356Ki"
    checks["guard evidence: LoadBalancer, externalIPs, Ingress and PVC denied by the policy, ClusterIP admitted"] = \
        "guard policy=finrisk-no-external-exposure loadbalancer_dry_run=denied external_ips_dry_run=denied " \
        "external_ips_denied_by=policy ingress_dry_run=denied pvc_dry_run=denied clusterip_dry_run=admitted" in lines
    checks["each download and embedded file passes sha256sum before it is used"] = verified_before_use(state["log"])
    checks["every polled kubectl call carries a request timeout (the fake refuses one without)"] = code == 0 \
        and all("--request-timeout=10s" in c for c in calls if " auth can-i " in c or " --raw " in c or "--dry-run=server" in c)
    checks["monitoring evidence: Healthy, Succeeded, the synced digest, signal reload, up series"] = any(
        l.startswith("monitoring app=finrisk-monitoring health=Healthy operation=Succeeded sync=Synced "
                     "oci_target=sha256:04047e500c803dc8d2bc284ecb43e9229bb32b5c36bd13fc89592c8a2f3cdc72 "
                     "synced_revision=sha256:04047e500c803dc8d2bc284ecb43e9229bb32b5c36bd13fc89592c8a2f3cdc72 "
                     "images_digest_pinned=yes reload=ProcessSignal lifecycle_api=off prometheus_up_series=4 "
                     "prometheus_up_ok=4 repo_server_restarts=0 repo_server_last_termination=none") for l in lines)
    checks["every namespace enforces and warns Pod Security restricted"] = all(
        state["namespaces"].get(ns, {}).get(k) == v for ns in ("finrisk", "argocd", "monitoring")
        for k, v in (("pod-security.kubernetes.io/enforce", "restricted"), ("pod-security.kubernetes.io/warn", "restricted"),
                     ("pod-security.kubernetes.io/enforce-version", "latest"), ("pod-security.kubernetes.io/warn-version", "latest")))
    order = ["kubectl label namespace monitoring", "kubectl apply --server-side --field-manager=finrisk-bootstrap "
             "--force-conflicts -f tmp/finrisk/cluster-guards.yaml", DRY_RUN, "helm list --namespace argocd --pending",
             HELM, PROJECTS, "kubectl apply --server-side --field-manager=finrisk-bootstrap --force-conflicts "
             "-f tmp/finrisk/monitoring-app.yaml", "kubectl --request-timeout=10s get --raw"]
    checks["order: namespaces, guard and its proof, Argo CD, projects, monitoring, then the Prometheus query"] = \
        [first(calls, p) for p in order] == sorted(first(calls, p) for p in order) and all(first(calls, p) < len(calls) for p in order)
    checks[f"waits within build_timeout on the fake clock ({seconds} s)"] = code == 0 and seconds < BUILD_TIMEOUT * 60
    baseline = seconds

    code, out, _, _ = bootstrap("rerun", state=work / "ok.json")
    checks["a re-run converges (every step is idempotent)"] = code == 0 and evidence(out)[-1:] == ["bootstrap=complete namespace=finrisk"]

    # Two more dry-run rounds before the policy loads than in the run above: two more 5 s polls. A round
    # stops at the first probe that is not answered as expected; the last round runs all five.
    code, out, state, seconds = runs["guard-slow"]
    checks["a policy that takes a moment to load is waited for"] = code == 0 and seconds == baseline + 10 \
        and len([c for c in state["calls"] if "--dry-run=server" in c]) == 3 + 5

    code, out, state, _ = runs["guard-apiserver"]
    checks["externalIPs denied first by the API server's own plugin is recorded as such"] = code == 0 \
        and "external_ips_denied_by=DenyServiceExternalIPs" in out

    for guard, answer in (("admits-loadbalancer", "service/finrisk-guard-probe"), ("admits-external-ips", "service/finrisk-guard-probe"),
                          ("admits-ingress", "ingress.networking.k8s.io/finrisk-guard-probe"),
                          ("admits-pvc", "persistentvolumeclaim/finrisk-guard-probe"),
                          ("denies-clusterip", "Only ClusterIP Services"), ("never-loads", "service/finrisk-guard-probe")):
        code, out, state, seconds = runs["guard-" + guard]
        checks[f"guard not proven ({guard}): stops before Argo CD, after its 30 s bound, showing the answers"] = code == 1 \
            and "exposure guard not proven" in out and answer in out and stopped_before(state, HELM) \
            and "FINRISK_EVIDENCE guard" not in out and "bootstrap=" not in out and 30 <= seconds <= 40

    code, out, state, seconds = runs["unauthorized"]
    checks["an unauthorized role stops after 60 s, before any namespace"] = code == 1 and "not authorized" in out \
        and not state["namespaces"] and 60 <= seconds <= 70

    code, out, state, _ = runs["node-type"]
    checks["a node of another type stops before any namespace"] = code == 1 and "nodes are not all t3.large" in out \
        and not state["namespaces"]

    code, out, state, _ = runs["tampered"]
    checks["an embedded file that differs from its sha256 stops before anything reaches the cluster"] = code != 0 \
        and "monitoring-app.yaml: FAILED" in out and set(state["calls"]) <= {"kubectl version --client", "helm version"}

    code, out, state, _ = runs["unverified"]
    checks["negative control: a download used without its checksum is caught"] = code == 0 and not verified_before_use(state["log"])

    code, out, state, _ = runs["no-request-timeout"]
    checks["negative control: a polled kubectl call without a request timeout fails"] = code != 0 \
        and bool(state.get("refused")) and stopped_before(state, HELM)

    code, out, state, _ = runs["helm-pending"]
    checks["a release left pending by an interrupted install stops before helm runs, pointing to DESTROY"] = code == 1 \
        and "Helm release argocd is pending from an interrupted bootstrap; DESTROY rather than retry" in out \
        and stopped_before(state, HELM) and "bootstrap=" not in out

    code, out, state, _ = runs["helm-fails"]
    checks["a failed Argo CD install stops before the projects"] = code != 0 and "UPGRADE FAILED" in out \
        and stopped_before(state, PROJECTS) and "bootstrap=" not in out

    for name, (_, report) in argocd_drift.items():
        code, out, state, _ = runs[name]
        checks[f"Argo CD install check ({name}) stops before the projects"] = code == 1 and report in out \
            and stopped_before(state, PROJECTS) and "FINRISK_EVIDENCE argocd" not in out

    code, out, state, seconds = runs["monitoring-never"]
    checks["monitoring never Healthy: fails after its 420 s bound with diagnostics, no monitoring evidence"] = code == 1 \
        and "is not Healthy with a Succeeded sync (health|operation|sync: Progressing|Running|OutOfSync)" in out \
        and "SyncError" in out and "prometheus-monitoring-0" in out and "restarts=" in out \
        and "FINRISK_EVIDENCE monitoring" not in out and "bootstrap=" not in out and 420 <= seconds <= 470

    for name, state_text in (("degraded", "Degraded|Failed|OutOfSync"), ("healthy-running", "Healthy|Running|Synced"),
                             ("degraded-succeeded", "Degraded|Succeeded|Synced")):
        code, out, _, seconds = runs["monitoring-" + name]
        checks[f"monitoring {state_text} (Healthy and Succeeded both required) fails after the bound"] = code == 1 \
            and f"(health|operation|sync: {state_text})" in out and "FINRISK_EVIDENCE monitoring" not in out \
            and "bootstrap=" not in out and seconds >= 420

    code, out, _, _ = runs["monitoring-outofsync"]
    checks["Healthy with a Succeeded sync passes even when OutOfSync, which is recorded"] = code == 0 \
        and "health=Healthy operation=Succeeded sync=OutOfSync" in out

    code, out, _, _ = runs["lifecycle"]
    checks["a Prometheus with the lifecycle API fails the bootstrap"] = code == 1 \
        and "lifecycle API enabled" in out and "bootstrap=" not in out

    code, out, _, _ = runs["unpinned-monitoring"]
    checks["an image by tag in monitoring fails the bootstrap"] = code == 1 and "Pods in monitoring run images not pinned" in out

    code, out, _, seconds = runs["no-ksm"]
    checks["kube-state-metrics not scraped: fails after its 90 s bound"] = code == 1 \
        and "not scraping kube-state-metrics" in out and "bootstrap=" not in out and seconds >= 90

    code, out, _, _ = runs["repo-oom"]
    checks["a repo-server OOM kill is recorded, not hidden"] = code == 0 \
        and "repo_server_restarts=1 repo_server_last_termination=OOMKilled" in out

    code, out, _, _ = runs["no-top"]
    checks["kubectl top unavailable is noted and does not fail the bootstrap"] = code == 0 \
        and "kubectl top unavailable" in out and evidence(out)[-1:] == ["bootstrap=complete namespace=finrisk"]
finally:
    shutil.rmtree(work, ignore_errors=True)

failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("Bootstrap buildspec runtime acceptance failed: " + ", ".join(failed))
