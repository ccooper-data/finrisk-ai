#!/usr/bin/env python3
# Executes the rendered deploy buildspec against a stateful fake kubectl (fakes/kubectl.py: the Argo CD
# Application, its controller, the Deployment and HPA it syncs, the load Job, the runner's authorization)
# to check the GitOps deploy, rollback, retention, load-test and abort paths end to end (substring checks
# cannot catch control-flow bugs). The fake runs the in-pod smoke and PromQL scripts (infra/k8s, embedded
# in the buildspec as Terraform embeds them) for real, against stand-ins for the inference API and
# Prometheus. Time is a fake clock that only `sleep` advances, so every wait's bound is exercised exactly
# and fast. Each convergence check is shown to matter alone: the fake falsifies one thing (FAKE_SKEW) and the
# buildspec without that one check (a negative control) deploys. Argo CD reporting OutOfSync after a sync
# that succeeded (FAKE_OUT_OF_SYNC) deploys only for the chart's HPA and ServiceMonitor, by group, kind,
# namespace and name, and every other check still stops a skew, a missing HPA or the previous image under it.
# sha256sum checks for real, so the embedded files must match the plan-time sha256 values the buildspec carries.
import base64
import copy
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
TEMPLATE = (ROOT / "infra/terraform/deploy/deploy-buildspec.yml.tftpl").read_text()
FAKE_KUBECTL = ROOT / "infra/tests/fakes/kubectl.py"
INFERENCE_APP = (ROOT / "infra/k8s/inference-app.yaml").read_text()
TF = (ROOT / "infra/terraform/deploy_path.tf").read_text()
BUILD_TIMEOUT = int(re.search(r'resource "aws_codebuild_project" "k8s_deploy" \{.*?build_timeout\s+= (\d+)', TF, re.S)[1])
K8S = ROOT / "infra/k8s"
# The embedded files as deploy_path.tf bundles them: a "#==> <file>" line before each.
DEPLOY_FILES = re.findall(r'"([^"]+)"', re.search(r"k8s_deploy_files\s+= \[(.*)\]", TF)[1])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def embedded(**replaced):
    """The deploy's k8s_bundle_b64 and each file's sha256, as Terraform computes them from infra/k8s; a
    replaced file's text (for a negative control) gets its own matching sha256, as a reviewed plan would show."""
    texts = {f: replaced.get(f, (K8S / f).read_text()) for f in DEPLOY_FILES}
    text = "".join(f"#==> {f}\n" + texts[f] for f in DEPLOY_FILES)
    return {"k8s_bundle_b64": base64.b64encode(gzip.compress(text.encode())).decode(),
            **{f"{f.split('.')[0].replace('-', '_')}_sha256": sha(texts[f].encode()) for f in DEPLOY_FILES}}


def file_change(name, old, new):
    """embedded() with one replacement in one file, or None when `old` is not in it."""
    text = (K8S / name).read_text()
    return embedded(**{name: text.replace(old, new, 1)}) if old in text else None


REPOSITORY = "780976819607.dkr.ecr.us-east-1.amazonaws.com/finrisk-ai-inference"
GOOD, BAD, NEXT = (f"{REPOSITORY}@sha256:" + c * 64 for c in "abc")
DIGEST = {uri: uri.split("@")[1] for uri in (GOOD, BAD, NEXT)}
REVISION = "0123456789abcdef0123456789abcdef01234567"
MODEL_SHA256 = "f" * 64
START = 1_000_000

values = {
    "cluster_name": "finrisk-ai-portfolio", "region": "us-east-1", "account_id": "780976819607",
    "repository": "finrisk-ai-inference", "namespace": "finrisk", "argocd_namespace": "argocd", "app": "finrisk-inference",
    # The curl stub downloads an empty kubectl.
    "kubectl_version": "v1.35.9", "kubectl_sha256": sha(b""), "model_sha256": MODEL_SHA256, "gitops_revision": REVISION,
    "repo_url": "https://github.com/ccooper-data/finrisk-ai.git", "chart_path": "charts/finrisk-inference",
    **embedded(),
}


def render(template=TEMPLATE, **override):
    rendered = template
    for key, value in dict(values, **override).items():
        rendered = rendered.replace("${" + key + "}", value)
    rendered = rendered.replace("$${", "${")
    script = yaml.safe_load(rendered)["phases"]["build"]["commands"][0]
    # The build runs in a scratch directory with its absolute paths made relative to it, so no
    # scratch or checkout path is ever pasted into shell source. That holds only without cd.
    return re.sub(r"(?<=[\s\"'<>])/tmp/", "tmp/", script.replace("/opt/finrisk/bin", "bin"))


def bootstrapped():
    """The Application as the bootstrap leaves it: placeholders filled in, no digest, so Argo CD reports a
    ComparisonError (the chart's values schema requires image.digest)."""
    text = INFERENCE_APP.replace("GITOPS_REVISION", REVISION).replace("IMAGE_REPOSITORY", REPOSITORY)
    app = next(d for d in yaml.safe_load_all(text) if d and d["kind"] == "Application")
    app["status"] = {"sync": {"status": "Unknown", "comparedTo": {"source": copy.deepcopy(app["spec"]["source"]),
                                                                  "destination": app["spec"]["destination"]}},
                     "conditions": [{"type": "ComparisonError", "message": "image.digest is required"}],
                     "health": {"status": "Missing"}}
    return {"app": app, "calls": []}


default = render()
checks = {
    "buildspec runs in the scratch directory (no cd, no absolute path left)": "/tmp/" not in default
        and "/opt/" not in default and re.search(r"(^|[\s;&|(])(cd|pushd|popd)(\s|$)", default, re.M) is None,
}


def report_checks():
    """Prints every check; returns the failure message, or None."""
    failed = [k for k, v in checks.items() if not v]
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'}: {k}")
    return "Deploy buildspec runtime acceptance failed: " + ", ".join(failed) if failed else None


def stub(name, body):
    path = stubs / name
    path.write_text("#!/usr/bin/env bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def deploy(name, image, start=None, script=None, change=None, **env):
    """Runs the buildspec from `start` (a finished scenario's state, or the bootstrap's), with `change`
    applied to that state first. Returns exit code, output, final state and fake-clock seconds."""
    cwd = work / name
    (cwd / "tmp").mkdir(parents=True)
    state, clock = cwd / "state.json", cwd / "clock"
    begin = json.loads((work / start / "state.json").read_text()) if start else bootstrapped()
    # A later run: the earlier load test's Job is gone and the HPA has scaled back down.
    begin.update(calls=[], patches=[], unbounded=[], job=None, windows=[], load_args=[])
    begin.pop("hpa", None)
    if change:
        change(begin)
    state.write_text(json.dumps(begin))
    clock.write_text(str(START))
    (cwd / "deploy.sh").write_text(script or default)
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
    run_env.update(PATH=f"{stubs}{os.pathsep}{os.environ['PATH']}", FAKE_STATE=str(state), FAKE_CLOCK=str(clock),
                   FAKE_PYTHON=sys.executable, FAKE_KUBECTL=str(FAKE_KUBECTL), FAKE_MODEL_SHA256=MODEL_SHA256,
                   FINRISK_IMAGE_URI=image, **env)
    result = subprocess.run(["bash", "deploy.sh"], cwd=cwd, env=run_env, capture_output=True, text=True, timeout=600)
    return result.returncode, result.stdout + result.stderr, json.loads(state.read_text()), int(clock.read_text()) - START


def evidence(out):
    return re.findall(r"^FINRISK_EVIDENCE (.*)$", out, re.M)


def exact_windows(state):
    """Each load PromQL window against the true load interval at its query (the fake records both): not
    shorter by a second or more, never longer."""
    windows = state.get("windows") or []
    return bool(windows) and all(0 <= interval - window < 1 for window, interval in windows)


def result(out):
    lines = evidence(out)
    return lines[-1] if lines and lines[-1].startswith("result=") else None


def digest(state):
    params = state["app"]["spec"]["source"]["helm"].get("parameters") or []
    return [p["value"] for p in params]


def image(state):
    return state["deployment"] and state["deployment"]["image"]


def only_digest_patches(state, *digests):
    """The only writes: merge patches by finrisk-digest that set exactly the image.digest parameter."""
    return [p for p in state["patches"]] == [{"manager": "finrisk-digest", "patch": {"spec": {"source": {"helm": {
        "parameters": [{"name": "image.digest", "value": d, "forceString": True}]}}}}} for d in digests]


def unchanged(state):
    """Nothing was written: no patch call at all (auth can-i only asks)."""
    return state["patches"] == [] and not any("-n finrisk patch " in c for c in state["calls"])


DIGEST_PATCH = re.compile(r'--request-timeout=10s -n finrisk patch applications\.argoproj\.io finrisk-inference --type=merge '
                          r'--field-manager=finrisk-digest -p \{"spec":\{"source":\{"helm":\{"parameters":\[\{"name":"image\.digest",'
                          r'"value":"sha256:[0-9a-f]{64}","forceString":true\}\]\}\}\}\}')


def stray_calls(state):
    """Calls the fake does not model (it refuses them, but a buildspec could ignore the failure), and any
    patch other than the digest patch."""
    patches = [c for c in state["calls"] if re.search(r"\bpatch\b", c) and not c.startswith("auth can-i")
               and " auth can-i " not in c]
    return state.get("unsupported", []) + [c for c in patches if not DIGEST_PATCH.fullmatch(c)]


AUTHZ = ("authz patch_app=yes get_app=yes get_deployment=yes get_hpa=yes patch_other_app=no create_app=no delete_app=no "
         "patch_appproject=no argocd_secrets=no create_rolebindings=no")
PROMQL = ["promql name=app_up value=1", "promql name=ksm_up value=1", "promql name=requests value=1",
          "promql name=latency_mean_ms value=12.5", "promql name=predictions value=1", "promql name=inference_p95_ms value=20.5",
          "promql name=replicas_available value=1", "promql name=hpa_current_replicas value=1"]
# The load test with FAKE_HPA scales: the HPA at 1 replica, then 3 under load; kube-state-metrics over the
# load interval; the Job deleted.
LOAD_EVIDENCE = ["hpa phase=before current=1 desired=1 cpu_utilization=3", "hpa phase=during current=3 desired=3 cpu_utilization=80",
                 "promql name=hpa_max_current_replicas value=3", "promql name=hpa_max_desired_replicas value=3",
                 "promql name=available_min value=1", "promql name=available_max value=3", "promql name=request_rate value=80",
                 "hpa phase=after current=3 desired=3 cpu_utilization=3",
                 "load job=finrisk-load hpa_scaled=yes max_replicas=3 job_deleted=yes"]
# Words of the deploy's own failure handling; a load-test failure must use none of them.
ROLLBACK_WORDS = re.compile(r"rolled_back|rollback|Re-patching|first_deploy_retained|failure=")
SMOKE = rf"^FINRISK_EVIDENCE smoke=passed model_sha256={MODEL_SHA256} feature_count=4 probability=0\.012300$"
# FAKE_SKEW name (fakes/kubectl.py) -> the one check of the buildspec's `ok` that it fails.
SKEWS = {s: s for s in ("sync", "revision", "operation_revision", "compared", "operation", "synced", "synced_revision", "automated",
                        "health", "image", "observed", "ready", "updated", "hpa")}
SKEWS.update(unknown="sync", source="override", sources="override", manifests="override", sidecar="image", init="image",
             scaled="updated", unavailable="updated")
# The objects whose OutOfSync is tolerated, as the argocd line's out_of_sync= names them (group/kind/namespace/name).
HPA_ID = "autoscaling/HorizontalPodAutoscaler/finrisk/finrisk-inference"
MONITOR_ID = "monitoring.coreos.com/ServiceMonitor/finrisk/finrisk-inference"


def without(*keys):
    """The rendered buildspec with the named checks of `ok` always true, or "exit 99" when one is not found."""
    mutated = TEMPLATE
    for key in keys:
        line = re.compile(rf'^( {{12}}"{key}": ).*,$', re.M)
        if len(line.findall(mutated)) != 1:
            return "exit 99"
        mutated = line.sub(r"\1True,", mutated)
    return render(mutated)


work = Path(tempfile.mkdtemp(prefix="finrisk-deploy-test-"))
try:
    stubs = work / "stubs"
    stubs.mkdir()
    # Downloads, AWS and time are not under test; kubectl is the fake. sha256sum checks for real (GNU's
    # --check --strict form, its "<file>: OK" lines), so a file that differs from its sha256 fails. Paths
    # reach the stubs through the environment, quoted, so spaces in the checkout or TMPDIR cannot split them.
    stub("curl", 'out=""; while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift;; esac; shift; done; : > "$out"')
    stub("sha256sum", 'exec "$FAKE_PYTHON" -c \'import hashlib, sys\n'
                      'assert sys.argv[1:] == ["--check", "--strict"], sys.argv\n'
                      'bad = 0\n'
                      'for line in sys.stdin.read().splitlines():\n'
                      '    want, path = line.split("  ", 1)\n'
                      '    ok = hashlib.sha256(open(path, "rb").read()).hexdigest() == want\n'
                      '    print(path + (": OK" if ok else ": FAILED"))\n'
                      '    bad += not ok\n'
                      'sys.exit(1 if bad else 0)\' "$@"')
    stub("aws", "exit 0")
    stub("install", 'printf \'#!/usr/bin/env bash\\nexec "$FAKE_PYTHON" "$FAKE_KUBECTL" "$@"\\n\' > "${@: -1}"; chmod +x "${@: -1}"')
    stub("python3", 'exec "$FAKE_PYTHON" "$@"')
    stub("date", '[ "$1" = "+%s" ] || exit 1; cat "$FAKE_CLOCK"')
    stub("sleep", 'echo $(( $(cat "$FAKE_CLOCK") + $1 )) > "$FAKE_CLOCK"')
    # Bounds the call it runs; the fake refuses an exec without one.
    stub("timeout", 'export FAKE_TIMEOUT="$1"; shift; exec "$@"')

    # The healthy deploys the update scenarios start from.
    code, out, first, seconds = deploy("first-ok", GOOD)
    lines = evidence(out)
    checks["first deploy succeeds: Argo CD converges on the digest, smoke and PromQL evidence, then result=deployed"] = \
        code == 0 and digest(first) == [DIGEST[GOOD]] and image(first) == GOOD \
        and result(out) == f"result=deployed image_uri={GOOD} revision=1 argocd_revision={REVISION} previous_digest=none"
    checks["the smoke script runs in the pod and reports the pinned model"] = re.search(SMOKE, out, re.M) is not None
    checks["evidence: authz, target revision, argocd, smoke, PromQL, the load test, then the result"] = [
        l.split()[0] for l in lines] == ["authz", "argocd_target_revision=" + REVISION, "argocd", "smoke=passed", *["promql"] * 8,
                                         "hpa", "hpa", *["promql"] * 5, "hpa", "load", lines[-1].split()[0]] \
        and lines[0] == AUTHZ and lines[1] == f"argocd_target_revision={REVISION} previous_digest=none"
    checks["the load test: HPA 1 before, 3 during and after, kube-state-metrics over the load interval, Job deleted"] = \
        lines[12:21] == LOAD_EVIDENCE
    job = first.get("job") or {}
    checks["the load Job runs the image just deployed, by digest, and is gone at the end"] = job.get("image") == GOOD \
        and job.get("pods") == 1 and job.get("deleted") is True and job.get("gone") is True
    # The build passes the seconds since it created the Job; the window grows with each poll from there.
    load_args = first.get("load_args") or []
    checks["the load PromQL covers exactly the load interval: at every query, window = seconds since the Job was created"] = \
        len(load_args) == 1 and load_args[0][0] == [str(load_args[0][1])] and load_args[0][1] > 0 and exact_windows(first)
    unpacked = {f: (work / "first-ok" / "tmp" / f).read_text() for f in DEPLOY_FILES if (work / "first-ok" / "tmp" / f).exists()}
    checks["the embedded files unpack byte-identical to infra/k8s"] = unpacked == {f: (K8S / f).read_text() for f in DEPLOY_FILES}
    verified = [f"tmp/{f}: OK" for f in ("kubectl", *DEPLOY_FILES)]
    checks["kubectl and each embedded file pass a real sha256 check before any API call"] = all(v in out for v in verified) \
        and max(out.index(v) for v in verified) < out.index("FINRISK_EVIDENCE authz")
    checks["argocd evidence: Synced and Healthy at the PLAN's commit and this digest, by an automated sync"] = any(
        l.startswith(f"argocd digest={DIGEST[GOOD]} sync=Synced out_of_sync=none revision={REVISION} compared={DIGEST[GOOD]} "
                     f"operation=Succeeded synced={DIGEST[GOOD]} synced_revision={REVISION} health=Healthy automated=True "
                     f"overrides=none image={GOOD} ready=1 replicas=1/1/1 ")
        and l.endswith(" pending=none") for l in lines)
    # Argo CD v3.5.3's autoSync puts a copy of spec.source in its operation; that is not an override.
    operation = (first["app"].get("status", {}).get("operationState") or {}).get("operation") or {}
    checks["the automated operation carries the Application's own source (as v3.5.3's autoSync builds it)"] = \
        (operation.get("sync") or {}).get("source") == first["app"]["spec"]["source"] \
        and operation.get("initiatedBy") == {"automated": True} and "operation" not in first["app"]
    checks["PromQL evidence: both scrapes up, the smoke prediction counted, latency and replicas recorded"] = lines[4:12] == PROMQL
    checks["the only write is a merge patch of image.digest by finrisk-digest"] = only_digest_patches(first, DIGEST[GOOD])
    checks[f"first deploy within build_timeout on the fake clock ({seconds} s)"] = seconds < BUILD_TIMEOUT * 60
    if code:
        # Every later scenario starts from this deployed state; report what failed instead of crashing on it.
        print(out)
        raise SystemExit(report_checks())

    only_next = {"FAKE_SKEW_DIGEST": DIGEST[NEXT]}
    SYNCED_AT_ONCE = {"FAKE_BAD_IMAGES": DIGEST[BAD], "FAKE_STALE_DEADLINE": "1", "FAKE_REFRESH_AFTER": "-1"}
    DEADLINE_APART = {"FAKE_BAD_IMAGES": DIGEST[BAD], "FAKE_STALE_DEADLINE": "1,0,1", "FAKE_CONTROLLER": "degraded"}
    runs = {
        "update-ok": (NEXT, "first-ok", {}),
        "update-fails": (BAD, "first-ok", {"FAKE_BAD_IMAGES": DIGEST[BAD]}),
        "first-fails": (BAD, None, {"FAKE_BAD_IMAGES": DIGEST[BAD]}),
        "sync-failed": (NEXT, "first-ok", {"FAKE_SYNC_FAILS": DIGEST[NEXT]}),
        "never-ready": (NEXT, "first-ok", {"FAKE_BAD_IMAGES": DIGEST[NEXT], "FAKE_DEADLINE_POLLS": "10000"}),
        "rollback-fails": (BAD, "first-ok", {"FAKE_BAD_IMAGES": f"{DIGEST[BAD]},{DIGEST[GOOD]}"}),
        "degraded": (NEXT, "first-ok", {"FAKE_CONTROLLER": "degraded"}),
        "same-digest": (GOOD, "first-ok", {}),
        "stale-then-refresh": (NEXT, "first-ok", {"FAKE_REFRESH_AFTER": "6"}),
        "frozen": (NEXT, "first-ok", {"FAKE_CONTROLLER": "frozen"}),
        "frozen-first": (GOOD, None, {"FAKE_CONTROLLER": "frozen"}),
        # Two reads of lag: a deadline verdict needs two polls in a row, so one read would not show the
        # observedGeneration check matters.
        "rollback-observe-lag": (BAD, "first-ok", {"FAKE_BAD_IMAGES": DIGEST[BAD], "FAKE_OBSERVE_LAG": "2"}),
        "rollback-stale-deadline": (BAD, "first-ok", {"FAKE_BAD_IMAGES": DIGEST[BAD], "FAKE_STALE_DEADLINE": "1"}),
        # Argo CD synced the re-patch before the first poll, which already shows the stale deadline: the
        # failed update's deadline (two polls, so late was set) must not carry over into the re-patch's wait.
        "rollback-synced-at-once": (BAD, "first-ok", SYNCED_AT_ONCE),
        # The stale deadline on the re-patch's first and third reads, an ordinary wait between them: not two
        # polls in a row.
        "rollback-deadline-apart": (BAD, "first-ok", DEADLINE_APART),
        **{"load-" + m: (NEXT, "first-ok", {"FAKE_HPA": m}) for m in ("never", "at-two")},
        **{"job-" + m: (NEXT, "first-ok", {"FAKE_JOB": m}) for m in ("create-fails", "exists", "delete-fails", "stuck", "list-fails")},
        **{"prom-load-" + m: (NEXT, "first-ok", {"FAKE_PROM_LOAD": m}) for m in ("ksm-unscaled", "outage", "no-requests")},
        **{"skew-" + s: (NEXT, "first-ok", {"FAKE_SKEW": s, "FAKE_SKEW_DIGEST": DIGEST[NEXT]}) for s in SKEWS},
        "app-read-fails": (NEXT, "first-ok", {"FAKE_APP_GET_FAIL": "1"}),
        **{"rbac-" + r: (NEXT, "first-ok", {"FAKE_RBAC": r}) for r in ("no-group", "extra-delete", "any-name", "argocd-secrets",
                                                                      "no-hpa", "no-deployment")},
        **{"prom-" + p: (NEXT, "first-ok", {"FAKE_PROM": p}) for p in ("app-down", "no-ksm", "unscraped", "unreachable")},
        **{"smoke-" + s: (NEXT, "first-ok", {"FAKE_SMOKE": s}) for s in (
            "wrong-sha", "ready-wrong-sha", "predict-wrong-sha", "not-ready", "prob-1.5", "prob-neg", "prob-int")},
        "bad-uri": (GOOD + ";id", "first-ok", {}),
        # Argo CD reports OutOfSync after the sync succeeded (fakes/kubectl.py FAKE_OUT_OF_SYNC, FAKE_MISSING, FAKE_DRIFT).
        "oos-first": (GOOD, None, {"FAKE_OUT_OF_SYNC": "ServiceMonitor", "FAKE_SKEW_DIGEST": DIGEST[GOOD]}),
        "oos-update": (NEXT, "first-ok", {"FAKE_OUT_OF_SYNC": "HorizontalPodAutoscaler,ServiceMonitor", **only_next}),
        "oos-deployment": (NEXT, "first-ok", {"FAKE_OUT_OF_SYNC": "Deployment", **only_next}),
        "oos-service": (NEXT, "first-ok", {"FAKE_OUT_OF_SYNC": "Service", **only_next}),
        "oos-extra-object": (NEXT, "first-ok", {"FAKE_OUT_OF_SYNC": "HorizontalPodAutoscaler,/ConfigMap/finrisk/finrisk-inference-extra",
                                                **only_next}),
        "oos-other-namespace": (NEXT, "first-ok", {
            "FAKE_OUT_OF_SYNC": "HorizontalPodAutoscaler,autoscaling/HorizontalPodAutoscaler/default/finrisk-inference", **only_next}),
        "oos-other-group": (NEXT, "first-ok", {
            "FAKE_OUT_OF_SYNC": "ServiceMonitor,example.com/ServiceMonitor/finrisk/finrisk-inference", **only_next}),
        "missing-service": (NEXT, "first-ok", {"FAKE_MISSING": "Service", **only_next}),
        "missing-hpa": (NEXT, "first-ok", {"FAKE_MISSING": "HorizontalPodAutoscaler", **only_next}),
        "missing-servicemonitor": (NEXT, "first-ok", {"FAKE_MISSING": "ServiceMonitor", **only_next}),
        "drift-previous": (NEXT, "first-ok", {"FAKE_DRIFT": "previous", **only_next}),
        "oos-rollback": (BAD, "first-ok", {"FAKE_BAD_IMAGES": DIGEST[BAD], "FAKE_OUT_OF_SYNC": "ServiceMonitor",
                                           "FAKE_SKEW_DIGEST": DIGEST[GOOD]}),
        # Both at once: the re-patch's first poll shows the failed rollout's deadline, and Argo CD then reports
        # the re-patched digest OutOfSync on the ServiceMonitor.
        "oos-rollback-stale-deadline": (BAD, "first-ok", {"FAKE_BAD_IMAGES": DIGEST[BAD], "FAKE_OUT_OF_SYNC": "ServiceMonitor",
                                                          "FAKE_SKEW_DIGEST": DIGEST[GOOD], "FAKE_STALE_DEADLINE": "1"}),
        **{"oos-skew-" + s: (NEXT, "first-ok", {"FAKE_OUT_OF_SYNC": "HorizontalPodAutoscaler", "FAKE_SKEW": s, **only_next})
           for s in SKEWS if SKEWS[s] != "sync"},
    }

    def spec(change):
        return lambda s: change(s["app"]["spec"])

    def helm(change):
        return lambda s: change(s["app"]["spec"]["source"]["helm"])

    # The Application drifted from what the bootstrap applied: the deploy must stop before writing.
    drift = {
        "another commit": spec(lambda a: a["source"].update(targetRevision="f" * 40)),
        "another project": spec(lambda a: a.update(project="finrisk-monitoring")),
        "another repository": spec(lambda a: a["source"].update(repoURL="https://github.com/someone/fork.git")),
        "another chart path": spec(lambda a: a["source"].update(path="charts/other")),
        "another image repository": spec(lambda a: a["source"]["helm"]["valuesObject"]["image"].update(repository=REPOSITORY + "-x")),
        "another destination": spec(lambda a: a["destination"].update(namespace="argocd")),
        "an extra Helm parameter": spec(lambda a: a["source"]["helm"]["parameters"].append({"name": "image.tag", "value": "latest"})),
        "a values file": spec(lambda a: a["source"]["helm"].update(valueFiles=["values-other.yaml"])),
        "automated sync off": spec(lambda a: a["syncPolicy"]["automated"].update(enabled=False)),
        "a resources finalizer": lambda s: s["app"]["metadata"].update(finalizers=["resources-finalizer.argocd.argoproj.io"]),
        "a second source (spec.sources)": spec(lambda a: a.update(sources=[copy.deepcopy(a["source"])])),
        "a source hydrator": spec(lambda a: a.update(sourceHydrator={"drySource": {"repoURL": a["source"]["repoURL"], "path": "x",
                                                                                     "targetRevision": "main"}})),
        "ignored differences": spec(lambda a: a.update(ignoreDifferences=[{"group": "apps", "kind": "Deployment",
                                                                           "jsonPointers": ["/spec/template"]}])),
        "another sync option": spec(lambda a: a["syncPolicy"].update(syncOptions=["Replace=true"])),
        "no sync options": spec(lambda a: a["syncPolicy"].pop("syncOptions")),
        "another retry policy": spec(lambda a: a["syncPolicy"]["retry"].update(limit=-1)),
        "another release name": helm(lambda h: h.update(releaseName="other")),
        "an extra value": helm(lambda h: h["valuesObject"].update(replicaCount=0)),
        "ServiceMonitor off": helm(lambda h: h["valuesObject"]["serviceMonitor"].update(enabled=False)),
        "a digest parameter without forceString": helm(lambda h: h["parameters"][0].pop("forceString")),
        "a digest that is not a digest": helm(lambda h: h["parameters"][0].update(value="latest")),
        "a pending operation": lambda s: s["app"].update(operation={"sync": {"revision": REVISION, "manifests": ["kind: ConfigMap"]},
                                                                   "initiatedBy": {"username": "someone"}}),
    }
    scripts = {"unset-revision": render(gitops_revision="unset")}
    # A load Job whose Pod Pod Security restricted rejects: created, but no Pod runs (FailedCreate).
    psa = file_change("load-job.yaml", "runAsNonRoot: true", "runAsNonRoot: false")
    scripts["job-psa-rejected"] = render(**psa) if psa else "exit 99"
    # An embedded file that differs from the sha256 the reviewed plan shows; and, as its negative control,
    # the same with the check's failure ignored.
    scripts["tampered"] = render(promql_sha256=sha(b"something else"))
    check = "        sha256sum --check --strict <<EOF\n"
    scripts["tampered-ignored"] = render(TEMPLATE.replace(check, check.replace("<<EOF", "<<EOF || :"), 1),
                                         promql_sha256=sha(b"something else")) if check in TEMPLATE else "exit 99"
    # Negative control: a load PromQL window an hour wider than the load interval.
    wide = file_change("promql.py", 'window = "[%ds]" % (time.monotonic() - started)',
                       'window = "[%ds]" % (time.monotonic() - started + 3600)')
    scripts["wide-window"] = render(**wide) if wide else "exit 99"
    # Negative control: a Pod template without the label the cleanup check lists by.
    unlabelled = file_change("load-job.yaml", "    metadata:\n      labels: {app.kubernetes.io/name: finrisk-load}\n",
                             "    metadata:\n      labels: {app.kubernetes.io/component: load}\n")
    scripts["unlabelled-pod"] = render(**unlabelled) if unlabelled else "exit 99"
    # Negative control: a progress deadline counted on its first sighting fails a good re-patch.
    two_polls = ('            progress_deadline*) [ -z "$late" ] || { failure=progress_deadline; return 0; }; late=1; return 1 ;;\n'
                 '            *) late=""; return 1 ;;\n')
    scripts["deadline-first-sighting"] = render(TEMPLATE.replace("            sync_failed*) failure=sync_failed; return 0 ;;\n", "", 1)
        .replace(two_polls, '            sync_failed*|progress_deadline*) failure="$${state%% *}"; return 0 ;;\n'
                 '            *) return 1 ;;\n', 1)) if two_polls in TEMPLATE else "exit 99"
    # Negative control: a convergence check that trusts Synced and Healthy without the digests (compared,
    # synced, the operation's source, the Deployment's image).
    scripts["trusts-stale-status"] = without("compared", "synced", "override", "image")
    # Negative controls for the load test: the Job deleted only after a passing test, and no check that
    # the HPA starts from 1 replica.
    scripts["cleanup-on-success-only"] = render(TEMPLATE.replace("          load_test || :\n          kq -n", "          load_test && kq -n", 1)) \
        if "          load_test || :\n          kq -n" in TEMPLATE else "exit 99"
    scripts["fixed-window"] = render(TEMPLATE.replace("python - $(( $(date +%s) - start )) <", "python - 900 <", 1)) \
        if "python - $(( $(date +%s) - start )) <" in TEMPLATE else "exit 99"
    scripts["any-start"] = render(TEMPLATE.replace('          [[ "$hpa" == 1\\ * ]] || { load=load_not_started; return 1; }\n', "", 1)) \
        if '          [[ "$hpa" == 1\\ * ]] || { load=load_not_started; return 1; }\n' in TEMPLATE else "exit 99"
    # Negative control: a cleanup check that reads a failed list as "gone".
    gone = '        gone() { left="$(kq -n "$NS" get jobs,pods -l app.kubernetes.io/name=finrisk-load -o name)" && [ -z "$left" ]; }\n'
    scripts["gone-fails-open"] = render(TEMPLATE.replace(gone, '        gone() { [ -z "$(kq -n "$NS" get jobs,pods '
                                                               '-l app.kubernetes.io/name=finrisk-load -o name)" ]; }\n', 1)) \
        if gone in TEMPLATE else "exit 99"
    # Negative control: hpa_scaled and max_replicas from every HPA reading, the one before any Job included.
    every_reading = [('          [ -z "$start" ] || [ "$${c:-0}" -le "$top" ] || top=$c\n', '          [ "$${c:-0}" -le "$top" ] || top=$c\n'),
                     ("wait_for 300 scaled_up && scaled=yes || load=hpa_not_scaled", "wait_for 300 scaled_up || load=hpa_not_scaled"),
                     ('          echo "FINRISK_EVIDENCE load job=', '          [ "$top" -ge 2 ] && scaled=yes || scaled=no\n'
                                                                    '          echo "FINRISK_EVIDENCE load job=')]
    scripts["scaled-from-any-reading"] = render(TEMPLATE.replace(every_reading[0][0], every_reading[0][1], 1).replace(
        *every_reading[1], 1).replace(*every_reading[2], 1)) if all(old in TEMPLATE for old, _ in every_reading) else "exit 99"
    # Negative controls for the progress-deadline rule: late not reset before the re-patch, and not reset
    # by a poll in between.
    reset = '            failure="" late=""\n            if set_digest "$PREV_DIGEST"'
    scripts["late-carried-into-repatch"] = render(TEMPLATE.replace(reset, '            failure=""\n            if set_digest "$PREV_DIGEST"', 1)) \
        if reset in TEMPLATE else "exit 99"
    scripts["late-kept-between-polls"] = render(TEMPLATE.replace('            *) late=""; return 1 ;;\n', '            *) return 1 ;;\n', 1)) \
        if '            *) late=""; return 1 ;;\n' in TEMPLATE else "exit 99"
    # Negative controls: without one check of `ok`, the skew that only it catches deploys.
    mutants = {s: without(SKEWS[s]) for s in SKEWS}
    # Negative control: a progress-deadline verdict that ignores observedGeneration fails a good rollback.
    scripts["deadline-ignores-generation"] = render(TEMPLATE.replace(
        '"ProgressDeadlineExceeded" in progress and ok["image"] and observed:', '"ProgressDeadlineExceeded" in progress and ok["image"]:', 1)) \
        if '"ProgressDeadlineExceeded" in progress and ok["image"] and observed:' in TEMPLATE else "exit 99"
    # Negative control: a second, non-merge patch whose refusal the buildspec ignores.
    scripts["extra-json-patch"] = render(TEMPLATE.replace("        set_digest() {\n", "        set_digest() {\n"
        "          kq -n \"$NS\" patch applications.argoproj.io \"$APP\" --type=json "
        "-p '[{\"op\":\"remove\",\"path\":\"/spec/syncPolicy/automated/selfHeal\"}]' || :\n", 1)) \
        if "        set_digest() {\n" in TEMPLATE else "exit 99"
    jobs = {name: (lambda n=name, a=args: deploy(n, a[0], a[1], **a[2])) for name, args in runs.items()}
    jobs.update({"drift " + name: (lambda n=name, c=change: deploy("drift-" + re.sub(r"\W+", "-", n), NEXT, "first-ok", change=c))
                 for name, change in drift.items()})
    jobs["unset-revision"] = lambda: deploy("unset-revision", NEXT, "first-ok", script=scripts["unset-revision"])
    jobs["trusts-stale-status"] = lambda: deploy("trusts-stale-status", NEXT, "first-ok", script=scripts["trusts-stale-status"],
                                                 FAKE_CONTROLLER="frozen")
    jobs.update({"without " + s: (lambda s=s: deploy("without-" + s, NEXT, "first-ok", script=mutants[s], FAKE_SKEW=s,
                                                     FAKE_SKEW_DIGEST=DIGEST[NEXT])) for s in SKEWS})
    jobs["deadline-ignores-generation"] = lambda: deploy("deadline-ignores-generation", BAD, "first-ok",
                                                         script=scripts["deadline-ignores-generation"],
                                                         FAKE_BAD_IMAGES=DIGEST[BAD], FAKE_OBSERVE_LAG="2")
    jobs["deadline-first-sighting"] = lambda: deploy("deadline-first-sighting", BAD, "first-ok", script=scripts[
        "deadline-first-sighting"], FAKE_BAD_IMAGES=DIGEST[BAD], FAKE_STALE_DEADLINE="1")
    jobs["oos-deadline-first-sighting"] = lambda: deploy("oos-deadline-first-sighting", BAD, "first-ok", script=scripts[
        "deadline-first-sighting"], **runs["oos-rollback-stale-deadline"][2])
    jobs["job-psa-rejected"] = lambda: deploy("job-psa-rejected", NEXT, "first-ok", script=scripts["job-psa-rejected"])
    jobs["cleanup-on-success-only"] = lambda: deploy("cleanup-on-success-only", NEXT, "first-ok", script=scripts[
        "cleanup-on-success-only"], FAKE_HPA="never")
    jobs["fixed-window"] = lambda: deploy("fixed-window", NEXT, "first-ok", script=scripts["fixed-window"])
    jobs["any-start"] = lambda: deploy("any-start", NEXT, "first-ok", script=scripts["any-start"], FAKE_HPA="at-two")
    jobs["extra-json-patch"] = lambda: deploy("extra-json-patch", NEXT, "first-ok", script=scripts["extra-json-patch"])
    jobs["tampered"] = lambda: deploy("tampered", NEXT, "first-ok", script=scripts["tampered"])
    jobs["tampered-ignored"] = lambda: deploy("tampered-ignored", NEXT, "first-ok", script=scripts["tampered-ignored"])
    jobs["wide-window"] = lambda: deploy("wide-window", NEXT, "first-ok", script=scripts["wide-window"], FAKE_PROM_LOAD="ksm-unscaled")
    jobs["unlabelled-pod"] = lambda: deploy("unlabelled-pod", NEXT, "first-ok", script=scripts["unlabelled-pod"], FAKE_JOB="stuck")
    jobs["gone-fails-open"] = lambda: deploy("gone-fails-open", NEXT, "first-ok", script=scripts["gone-fails-open"], FAKE_JOB="list-fails")
    jobs["scaled-from-any-reading"] = lambda: deploy("scaled-from-any-reading", NEXT, "first-ok", script=scripts["scaled-from-any-reading"],
                                                     FAKE_HPA="at-two")
    jobs["late-carried-into-repatch"] = lambda: deploy("late-carried-into-repatch", BAD, "first-ok",
                                                       script=scripts["late-carried-into-repatch"], **SYNCED_AT_ONCE)
    jobs["late-kept-between-polls"] = lambda: deploy("late-kept-between-polls", BAD, "first-ok",
                                                     script=scripts["late-kept-between-polls"], **DEADLINE_APART)

    def mutated(*changes):
        """The rendered buildspec with each (old, new, count) applied; "exit 99" when old does not occur count times."""
        text = TEMPLATE
        for old, new, count in changes:
            if text.count(old) != count:
                return "exit 99"
            text = text.replace(old, new)
        return render(text)

    # Negative controls for the OutOfSync tolerance: PR 2b's Synced-only check hangs on it; without the
    # chart-object or the non-empty condition, an extra object or an empty list passes; tolerating all four
    # chart objects lets drift on the Deployment or Service through; keyed without the namespace or the group,
    # a same-named object elsewhere passes; an image check of the inference container alone misses a sidecar;
    # without the image check the previous image under OutOfSync deploys, and without the hpa check a missing
    # HPA is served (only the load test, which reads the HPA after the release serves, then fails).
    sync_line = '"sync": f["sync"] == "Synced" or f["sync"] == "OutOfSync" and bool(oos) and set(oos) <= chart,'
    image_line = ('image = ",".join(c.get("image") or "none" for k in ("initContainers", "containers") '
                  'for c in dig(dep, "spec", "template", "spec", k) or []) or "none"')
    key = '("group", "kind", "namespace", "name")'
    four = ("chart = {", 'chart = {"apps/Deployment/${namespace}/${app}", "/Service/${namespace}/${app}", ', 1)
    tolerance_controls = {
        "synced-only": (mutated((sync_line, '"sync": f["sync"] == "Synced",', 1)),
                        {"FAKE_OUT_OF_SYNC": "HorizontalPodAutoscaler,ServiceMonitor", **only_next}),
        "any-object": (mutated((" and set(oos) <= chart,", ",", 1)),
                       {"FAKE_OUT_OF_SYNC": "HorizontalPodAutoscaler,/ConfigMap/finrisk/finrisk-inference-extra", **only_next}),
        "nothing-listed": (mutated((" and bool(oos)", "", 1)), {"FAKE_SKEW": "sync", **only_next}),
        "four-objects-deployment": (mutated(four), {"FAKE_OUT_OF_SYNC": "Deployment", **only_next}),
        "four-objects-service": (mutated(four), {"FAKE_OUT_OF_SYNC": "Service", **only_next}),
        "no-namespace": (mutated((key, '("group", "kind", "name")', 1), ("/${namespace}/${app}", "/${app}", 2)),
                         {"FAKE_OUT_OF_SYNC": "HorizontalPodAutoscaler,autoscaling/HorizontalPodAutoscaler/default/finrisk-inference",
                          **only_next}),
        "no-group": (mutated((key, '("kind", "namespace", "name")', 1),
                             ('"autoscaling/HorizontalPodAutoscaler/', '"HorizontalPodAutoscaler/', 1),
                             ('"monitoring.coreos.com/ServiceMonitor/', '"ServiceMonitor/', 1)),
                     {"FAKE_OUT_OF_SYNC": "ServiceMonitor,example.com/ServiceMonitor/finrisk/finrisk-inference", **only_next}),
        "inference-container-only": (mutated((image_line, 'image = next((c.get("image") for c in dig(dep, "spec", "template", "spec", '
                                                          '"containers") or [] if c.get("name") == "inference"), "none")', 1)),
                                     {"FAKE_SKEW": "sidecar", **only_next}),
        "missing-hpa-without-hpa": (without("hpa"), {"FAKE_MISSING": "HorizontalPodAutoscaler", **only_next}),
        "drift-without-image": (without("image"), {"FAKE_DRIFT": "previous", **only_next}),
        # Not a tolerance control: without the HPA preflight, a runner that cannot read the HPA patches, then
        # neither the update nor the re-patch can converge.
        "no-hpa-preflight": (mutated(('        expect get_hpa yes get "hpa/$APP" -n "$NS"\n', "", 1)), {"FAKE_RBAC": "no-hpa"}),
    }
    jobs.update({"control " + n: (lambda n=n, c=c: deploy("control-" + n, NEXT, "first-ok", script=c[0], **c[1]))
                 for n, c in tolerance_controls.items()})
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(zip(jobs, pool.map(lambda f: f(), jobs.values())))
    controls = {"trusts-stale-status", "deadline-ignores-generation", "deadline-first-sighting", "extra-json-patch",
                "cleanup-on-success-only", "any-start", "fixed-window", "tampered-ignored", "wide-window", "unlabelled-pod",
                "gone-fails-open", "scaled-from-any-reading", "late-carried-into-repatch", "late-kept-between-polls",
                "oos-deadline-first-sighting", *("without " + s for s in SKEWS), *("control " + n for n in tolerance_controls)}
    every = [first, *(r[2] for name, r in results.items() if name not in controls)]
    checks["no call reaches the API server without a bound (fake kubectl refuses one)"] = not any(s.get("unbounded") for s in every)
    checks["no call the fake does not model, and no patch but the digest patch, in any scenario"] = not any(map(stray_calls, every))
    code, out, state, _ = results["extra-json-patch"]
    checks["negative control: a second (JSON) patch whose refusal is ignored is caught"] = bool(stray_calls(state)) \
        and result(out) is not None and result(out).startswith("result=deployed")
    checks["no scenario takes longer than build_timeout on the fake clock"] = all(r[3] < BUILD_TIMEOUT * 60 for r in results.values())
    checks["every load PromQL window in every scenario is the load interval at its query, never wider"] = all(
        exact_windows(s) for s in every if s.get("windows"))

    code, out, state, _ = results["tampered"]
    checks["an embedded file that differs from the plan's sha256 stops the build before any API call"] = code != 0 \
        and "tmp/promql.py: FAILED" in out and state["calls"] == ["version --client"] and result(out) is None
    code, out, state, _ = results["tampered-ignored"]
    checks["negative control: with the sha256 check's failure ignored, that file is used and the build deploys"] = code == 0 \
        and "tmp/promql.py: FAILED" in out and result(out).startswith("result=deployed ")

    code, out, state, _ = results["update-ok"]
    checks["update succeeds and records the previous digest"] = code == 0 and digest(state) == [DIGEST[NEXT]] \
        and image(state) == NEXT and result(out).startswith(f"result=deployed image_uri={NEXT} revision=2 ") \
        and result(out).endswith(f"previous_digest={DIGEST[GOOD]}") and only_digest_patches(state, DIGEST[NEXT])

    code, out, state, seconds = results["update-fails"]
    checks["failed update rolls back to the previous image"] = code == 1 and digest(state) == [DIGEST[GOOD]] \
        and image(state) == GOOD and f"failure=progress_deadline digest={DIGEST[BAD]}" in out \
        and result(out) == f"result=rolled_back digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]}" \
        and only_digest_patches(state, DIGEST[BAD], DIGEST[GOOD]) and "smoke=passed" not in out and seconds < 480

    code, out, state, _ = results["first-fails"]
    checks["failed first deploy is retained for diagnosis: result=first_deploy_retained, never called a rollback"] = code == 1 \
        and digest(state) == [DIGEST[BAD]] and image(state) == BAD and state["app"]["metadata"]["name"] == "finrisk-inference" \
        and result(out) == f"result=first_deploy_retained digest={DIGEST[BAD]} previous_digest=none" \
        and only_digest_patches(state, DIGEST[BAD]) and not re.search(r"roll|recover|Re-patching", out, re.I)

    code, out, state, seconds = results["sync-failed"]
    checks["a failed sync stops the wait at once, then the previous digest is re-patched"] = code == 1 \
        and f"failure=sync_failed digest={DIGEST[NEXT]}" in out and seconds < 120 \
        and result(out) == f"result=rolled_back digest={DIGEST[NEXT]} previous_digest={DIGEST[GOOD]}" and digest(state) == [DIGEST[GOOD]]

    code, out, state, seconds = results["never-ready"]
    checks["a digest that never converges fails at the 480 s bound, then rolls back"] = code == 1 \
        and f"failure=timeout digest={DIGEST[NEXT]}" in out and 480 <= seconds < 480 + 120 \
        and result(out).startswith("result=rolled_back") and image(state) == GOOD

    code, out, state, _ = results["rollback-fails"]
    checks["a rollback that does not converge reports result=rollback_failed"] = code == 1 \
        and result(out) == f"result=rollback_failed digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]} failure=progress_deadline"

    code, out, state, _ = results["degraded"]
    checks["a transient application Degraded (HPA metrics) is waited out, not failed"] = code == 0 \
        and result(out).startswith("result=deployed") and image(state) == NEXT

    code, out, state, seconds = results["same-digest"]
    load = (state.get("job") or {}).get("created", START + seconds) - START
    checks["redeploying the running digest is a no-op patch that verifies (then load-tests)"] = code == 0 \
        and digest(state) == [DIGEST[GOOD]] and result(out).endswith(f"previous_digest={DIGEST[GOOD]}") \
        and state["deployment"]["revision"] == 1 and load <= 10

    code, out, state, seconds = results["stale-then-refresh"]
    checks["the previous digest's Synced and Healthy status is not taken for the new one"] = code == 0 \
        and image(state) == NEXT and result(out).startswith("result=deployed") and seconds >= 6 * 5

    code, out, state, _ = results["frozen"]
    checks["a status that never leaves the previous digest never passes (stale-status guard)"] = code == 1 \
        and f"failure=timeout digest={DIGEST[NEXT]}" in out and "result=deployed" not in out and "smoke=passed" not in out
    code, out, state, _ = results["trusts-stale-status"]
    checks["negative control: a convergence check without the digests accepts the stale status"] = code == 0 \
        and "result=deployed" in out

    code, out, state, _ = results["frozen-first"]
    checks["a first deploy Argo CD never syncs is retained after the bound"] = code == 1 \
        and result(out) == f"result=first_deploy_retained digest={DIGEST[GOOD]} previous_digest=none"

    for s, key in SKEWS.items():
        code, out, state, _ = results["skew-" + s]
        checks[f"convergence needs {key} ({s} falsified): never converged, then rolled back"] = code == 1 \
            and f"failure=timeout digest={DIGEST[NEXT]} state=waiting " in out and f"pending={key}\n" in out \
            and "smoke=passed" not in out and image(state) == GOOD \
            and result(out) == f"result=rolled_back digest={DIGEST[NEXT]} previous_digest={DIGEST[GOOD]}"
        code, out, state, _ = results["without " + s]
        checks[f"negative control: without the {key} check, the {s} skew deploys"] = code == 0 \
            and result(out).startswith(f"result=deployed image_uri={NEXT} ")

    def argocd_line(out):
        return next((l for l in evidence(out) if l.startswith("argocd digest=")), "")

    def stopped(name, pending):
        """Never converged (the last poll pending exactly `pending`), never served, then rolled back."""
        code, out, state, _ = results[name]
        return code == 1 and f"failure=timeout digest={DIGEST[NEXT]} state=waiting " in out and f" pending={pending}\n" in out \
            and "smoke=passed" not in out and not argocd_line(out) and image(state) == GOOD \
            and result(out) == f"result=rolled_back digest={DIGEST[NEXT]} previous_digest={DIGEST[GOOD]}"

    code, out, state, _ = results["oos-first"]
    checks["first deploy: OutOfSync on the ServiceMonitor after a successful sync deploys and is recorded"] = code == 0 \
        and result(out) == f"result=deployed image_uri={GOOD} revision=1 argocd_revision={REVISION} previous_digest=none" \
        and argocd_line(out).startswith(f"argocd digest={DIGEST[GOOD]} sync=OutOfSync out_of_sync={MONITOR_ID} ") \
        and argocd_line(out).endswith(" pending=none") and re.search(SMOKE, out, re.M) is not None
    code, out, state, _ = results["oos-update"]
    checks["update: OutOfSync on the HPA and ServiceMonitor deploys after self-heal re-syncs, with both recorded, then "
           "load-tests"] = code == 0 \
        and result(out).startswith(f"result=deployed image_uri={NEXT} revision=2 ") and image(state) == NEXT \
        and f" out_of_sync={HPA_ID},{MONITOR_ID} " in argocd_line(out) \
        and f" image={NEXT} ready=1 replicas=1/1/1 " in argocd_line(out) and only_digest_patches(state, DIGEST[NEXT]) \
        and state["polls"] - state["synced_at"][DIGEST[NEXT]] > 2 \
        and "load job=finrisk-load hpa_scaled=yes max_replicas=3 job_deleted=yes" in out
    checks["OutOfSync on the Deployment is never tolerated (drift other than its image would pass)"] = stopped("oos-deployment", "sync")
    checks["OutOfSync on the Service is never tolerated (the smoke test goes through it)"] = stopped("oos-service", "sync")
    checks["an object outside the chart out of sync is never tolerated"] = stopped("oos-extra-object", "sync")
    checks["an HPA of the same name in another namespace out of sync is never tolerated"] = stopped("oos-other-namespace", "sync")
    checks["a ServiceMonitor kind of another API group out of sync is never tolerated"] = stopped("oos-other-group", "sync")
    checks["a missing Service (OutOfSync, health still Healthy) never converges"] = stopped("missing-service", "sync")
    checks["a missing HPA (OutOfSync, health still Healthy) never converges"] = stopped("missing-hpa", "hpa")
    checks["the previous image kept live, with Argo CD alternating OutOfSync and Synced, never converges"] = stopped(
        "drift-previous", "sync,image")
    code, out, state, _ = results["missing-servicemonitor"]
    checks["a missing ServiceMonitor (OutOfSync, as a changed one) fails the PromQL evidence: observability_failed"] = code == 1 \
        and f" out_of_sync={MONITOR_ID} " in argocd_line(out) and re.search(SMOKE, out, re.M) is not None \
        and "promql failed: app_up, requests, latency_mean_ms, predictions\n" in out and image(state) == NEXT \
        and result(out).startswith(f"result=observability_failed image_uri={NEXT} ") and only_digest_patches(state, DIGEST[NEXT])
    for s, key in SKEWS.items():
        if key != "sync":
            checks[f"under a tolerated OutOfSync, convergence still needs {key} ({s} falsified)"] = stopped("oos-skew-" + s, key)
    code, out, state, _ = results["control synced-only"]
    checks["negative control: PR 2b's Synced-only check waits out the bound on that OutOfSync, then rolls back"] = code == 1 \
        and f"failure=timeout digest={DIGEST[NEXT]} state=waiting sync=OutOfSync " in out and " pending=sync\n" in out \
        and result(out) == f"result=rolled_back digest={DIGEST[NEXT]} previous_digest={DIGEST[GOOD]}"
    for name, what in {"any-object": "tolerating any out-of-sync object, one outside the chart",
                       "nothing-listed": "tolerating OutOfSync with no object listed, the sync skew",
                       "four-objects-deployment": "tolerating the Deployment too, its OutOfSync",
                       "four-objects-service": "tolerating the Service too, its OutOfSync",
                       "no-namespace": "keyed without the namespace, the HPA's name in another namespace",
                       "no-group": "keyed without the group, a ServiceMonitor kind of another group",
                       "inference-container-only": "checking the inference container's image alone, a sidecar",
                       "drift-without-image": "without the image check, the previous image under OutOfSync"}.items():
        code, out, state, _ = results["control " + name]
        checks[f"negative control: {what} deploys"] = code == 0 and result(out).startswith(f"result=deployed image_uri={NEXT} ")
    # The load test reads the HPA too, but only after the release serves: no re-patch, never a rollback.
    code, out, state, _ = results["control missing-hpa-without-hpa"]
    checks["negative control: without the hpa check, a missing HPA under OutOfSync is served, and only the load test fails"] = \
        code == 1 and argocd_line(out).endswith(" pending=none") and re.search(SMOKE, out, re.M) is not None \
        and result(out).startswith(f"result=load_not_started image_uri={NEXT} ") and "hpa phase=before current=none " in out \
        and only_digest_patches(state, DIGEST[NEXT]) and not ROLLBACK_WORDS.search(out)
    code, out, state, _ = results["control no-hpa-preflight"]
    checks["negative control: without the HPA preflight, a runner that cannot read the HPA patches, then cannot re-patch"] = \
        code == 1 and only_digest_patches(state, DIGEST[NEXT], DIGEST[GOOD]) \
        and result(out) == f"result=rollback_failed digest={DIGEST[NEXT]} previous_digest={DIGEST[GOOD]} failure=timeout"
    code, out, state, _ = results["oos-rollback"]
    checks["a re-patch that Argo CD reports OutOfSync on a chart object still completes the rollback"] = code == 1 \
        and f"failure=progress_deadline digest={DIGEST[BAD]}" in out and image(state) == GOOD \
        and result(out) == f"result=rolled_back digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]}"
    code, out, state, _ = results["oos-rollback-stale-deadline"]
    checks["a re-patch that shows the old deadline on its first poll, then OutOfSync on the ServiceMonitor, still rolls back"] = \
        code == 1 and f"failure=progress_deadline digest={DIGEST[BAD]}" in out and image(state) == GOOD \
        and result(out) == f"result=rolled_back digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]}" \
        and only_digest_patches(state, DIGEST[BAD], DIGEST[GOOD])
    code, out, state, _ = results["oos-deadline-first-sighting"]
    checks["negative control: there, a deadline counted on its first poll reports rollback_failed"] = code == 1 \
        and image(state) == GOOD \
        and result(out) == f"result=rollback_failed digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]} failure=progress_deadline"

    code, out, state, _ = results["rollback-observe-lag"]
    checks["a re-patch is not failed on the previous image's progress deadline before the Deployment observes it"] = \
        code == 1 and result(out) == f"result=rolled_back digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]}" and image(state) == GOOD
    code, out, state, _ = results["deadline-ignores-generation"]
    checks["negative control: a deadline verdict without observedGeneration fails that rollback"] = code == 1 \
        and result(out) == f"result=rollback_failed digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]} failure=progress_deadline"
    # The Deployment observed the re-patched template, but its Progressing condition still shows the failed
    # rollout's deadline for one read: the re-patch completed, so it is not a failed rollback.
    code, out, state, _ = results["rollback-stale-deadline"]
    checks["a progress deadline seen on one poll only (just after the re-patch) does not fail the rollback"] = code == 1 \
        and f"failure=progress_deadline digest={DIGEST[BAD]}" in out and image(state) == GOOD \
        and result(out) == f"result=rolled_back digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]}"
    code, out, state, _ = results["deadline-first-sighting"]
    checks["negative control: a deadline counted on its first poll reports rollback_failed for that completed re-patch"] = \
        code == 1 and image(state) == GOOD \
        and result(out) == f"result=rollback_failed digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]} failure=progress_deadline"
    rolled_back = f"result=rolled_back digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]}"
    rollback_failed = f"result=rollback_failed digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]} failure=progress_deadline"
    # The failed update ended on two deadline polls in a row, so late was set when the re-patch began.
    code, out, state, _ = results["rollback-synced-at-once"]
    checks["a re-patch synced before its first poll, which shows the stale deadline, still rolls back (late reset first)"] = \
        code == 1 and f"failure=progress_deadline digest={DIGEST[BAD]}" in out and image(state) == GOOD and result(out) == rolled_back
    code, out, state, _ = results["late-carried-into-repatch"]
    checks["negative control: late carried over from the failed update reports rollback_failed for that re-patch"] = \
        code == 1 and image(state) == GOOD and result(out) == rollback_failed
    code, out, state, _ = results["rollback-deadline-apart"]
    checks["a stale deadline on two polls that are not in a row (deadline, waiting, deadline) does not fail the rollback"] = \
        code == 1 and image(state) == GOOD and result(out) == rolled_back
    code, out, state, _ = results["late-kept-between-polls"]
    checks["negative control: late not reset by the poll in between reports rollback_failed there"] = \
        code == 1 and image(state) == GOOD and result(out) == rollback_failed

    # Load-test failures: the release passed its smoke test and stays (one digest patch, no re-patch, never
    # called a rollback); the Job is deleted on every outcome; the build fails.
    def healthy_after_load(state, out):
        return only_digest_patches(state, DIGEST[NEXT]) and image(state) == NEXT and "smoke=passed" in out \
            and len(re.findall(r"^FINRISK_EVIDENCE promql ", out, re.M)) >= 8 and not ROLLBACK_WORDS.search(out)

    def cleaned(state, out):
        job = state.get("job")
        return (job is None or job.get("gone") is True) and "job_deleted=yes" in out \
            and any(c.endswith("delete job finrisk-load --ignore-not-found --wait=false") for c in state["calls"])

    code, out, state, seconds = results["load-never"]
    checks["an HPA that never scales: result=hpa_not_scaled after the 300 s bound, release left serving, Job deleted"] = \
        code == 1 and result(out) == f"result=hpa_not_scaled image_uri={NEXT} revision=2 argocd_revision={REVISION} " \
        f"previous_digest={DIGEST[GOOD]}" and "hpa phase=during current=1 desired=1 cpu_utilization=45" in out \
        and "load job=finrisk-load hpa_scaled=no max_replicas=1 job_deleted=yes" in out and seconds >= 300 \
        and healthy_after_load(state, out) and cleaned(state, out) and (state["job"] or {}).get("image") == NEXT
    code, out, state, _ = results["cleanup-on-success-only"]
    checks["negative control: a Job deleted only after a passing load test is left behind when the HPA never scales"] = \
        code == 1 and result(out).startswith("result=hpa_not_scaled ") and not (state["job"] or {}).get("deleted") \
        and "job_deleted=no" in out
    code, out, state, _ = results["load-at-two"]
    checks["an HPA already above 1 replica: result=load_not_started, no Job created, nothing claimed scaled"] = code == 1 \
        and result(out).startswith("result=load_not_started ") and "hpa phase=before current=2 " in out \
        and state.get("job") is None and not any(c.endswith(" create -f -") for c in state["calls"]) and healthy_after_load(state, out) \
        and "load job=finrisk-load hpa_scaled=no max_replicas=0 job_deleted=yes" in out
    code, out, state, _ = results["scaled-from-any-reading"]
    checks["negative control: hpa_scaled from every HPA reading claims a scale-out for a load test that never ran"] = code == 1 \
        and result(out).startswith("result=load_not_started ") and "hpa_scaled=yes max_replicas=2 " in out
    code, out, state, _ = results["fixed-window"]
    load_args = state.get("load_args") or []
    checks["negative control: a fixed PromQL window (not the seconds since the Job was created) is caught"] = \
        len(load_args) == 1 and load_args[0][0] == ["900"] and load_args[0][1] != 900
    code, out, state, _ = results["any-start"]
    checks["negative control: without the 1-replica start check, an HPA already at 2 passes the load test"] = code == 0 \
        and result(out).startswith("result=deployed ") and "hpa phase=before current=2 " in out
    code, out, state, _ = results["job-create-fails"]
    checks["a refused Job create: result=load_not_started, cleanup still runs, nothing claimed scaled"] = code == 1 \
        and result(out).startswith("result=load_not_started ") and healthy_after_load(state, out) and cleaned(state, out) \
        and "hpa_scaled=no max_replicas=0 " in out
    code, out, state, _ = results["job-exists"]
    checks["a Job left over by an earlier build: result=load_not_started, and the leftover is deleted"] = code == 1 \
        and result(out).startswith("result=load_not_started ") and healthy_after_load(state, out) and cleaned(state, out) \
        and state["job"]["image"] == "left over by an earlier build" and "hpa_scaled=no max_replicas=0 " in out
    for name, expected in {"job-delete-fails": "job_deleted=no", "job-stuck": "job_deleted=no"}.items():
        code, out, state, _ = results[name]
        checks[f"a Job that is not gone ({name}) fails the build: result=load_cleanup_failed"] = code == 1 \
            and result(out).startswith("result=load_cleanup_failed ") and "hpa_scaled=yes max_replicas=3 " + expected in out \
            and only_digest_patches(state, DIGEST[NEXT]) and not ROLLBACK_WORDS.search(out)
    code, out, state, _ = results["job-list-fails"]
    checks["a failed list of the Job and its Pod is not taken for gone: result=load_cleanup_failed, job_deleted=no"] = code == 1 \
        and result(out).startswith("result=load_cleanup_failed ") and "hpa_scaled=yes max_replicas=3 job_deleted=no" in out \
        and only_digest_patches(state, DIGEST[NEXT]) and not ROLLBACK_WORDS.search(out)
    code, out, state, _ = results["gone-fails-open"]
    checks["negative control: a cleanup check that ignores the list's failure records job_deleted=yes unchecked"] = code == 0 \
        and result(out).startswith("result=deployed ") and "job_deleted=yes" in out
    code, out, state, _ = results["unlabelled-pod"]
    checks["negative control: a Pod without the label the cleanup lists by is reported deleted while it still runs"] = code == 0 \
        and result(out).startswith("result=deployed ") and "job_deleted=yes" in out and (state["job"] or {}).get("gone") is not True
    code, out, state, _ = results["wide-window"]
    checks["negative control: a window wider than the load interval passes on earlier history (ksm-unscaled deploys)"] = \
        code == 0 and result(out).startswith("result=deployed ") and not exact_windows(state)
    for mode, missing in {"ksm-unscaled": "hpa_max_current_replicas", "outage": "available_min", "no-requests": "request_rate"}.items():
        code, out, state, _ = results["prom-load-" + mode]
        checks[f"load evidence missing ({mode}): result=hpa_evidence_failed, release left serving, Job deleted"] = code == 1 \
            and result(out).startswith(f"result=hpa_evidence_failed image_uri={NEXT} ") and f"promql failed: {missing}\n" in out \
            and healthy_after_load(state, out) and cleaned(state, out)
    code, out, state, _ = results["job-psa-rejected"]
    checks["a load Job Pod Security rejects runs no Pod: hpa_not_scaled, the events say why, the Job is deleted"] = \
        code == 1 and result(out).startswith("result=hpa_not_scaled ") and (state["job"] or {}).get("pods") == 0 \
        and 'violates PodSecurity "restricted:latest"' in out and healthy_after_load(state, out) and cleaned(state, out) \
        and "hpa_scaled=no max_replicas=1 " in out

    code, out, state, _ = results["app-read-fails"]
    checks["an Application read error stops before any change"] = code == 1 and unchanged(state) \
        and "not read or not as reviewed; nothing changed" in out and result(out) is None

    for name in drift:
        code, out, state, _ = results["drift " + name]
        checks[f"Application drift ({name}) stops before any change"] = code == 1 and unchanged(state) \
            and "Application not as reviewed" in out and result(out) is None

    for name, answer in {"no-group": "patch_app=no", "extra-delete": "delete_app=yes", "any-name": "patch_other_app=yes",
                         "argocd-secrets": "argocd_secrets=yes", "no-hpa": "get_hpa=no", "no-deployment": "get_deployment=no"}.items():
        code, out, state, _ = results["rbac-" + name]
        checks[f"authorization preflight ({answer}) stops before any change"] = code == 1 and unchanged(state) \
            and answer in out and "unexpected authorization:" in out and result(out) is None

    code, out, state, _ = results["unset-revision"]
    checks["an unset gitops revision is refused before kubectl runs"] = code == 1 and state["calls"] == [] \
        and "gitops revision refused: unset" in out

    for name, missing in {"app-down": "app_up", "no-ksm": "ksm_up", "unscraped": "app_up, requests, latency_mean_ms, predictions",
                          "unreachable": "app_up, ksm_up, requests, latency_mean_ms, predictions"}.items():
        code, out, state, _ = results["prom-" + name]
        checks[f"PromQL evidence missing ({name}): result=observability_failed, no rollback"] = code == 1 \
            and result(out).startswith(f"result=observability_failed image_uri={NEXT} ") and f"promql failed: {missing}\n" in out \
            and only_digest_patches(state, DIGEST[NEXT]) and image(state) == NEXT and "smoke=passed" in out

    # The API stand-in breaks one thing per scenario (see fakes/kubectl.py); each check in the smoke
    # script is needed by one of them, except status == "ready", which every 200 from serving.py has.
    smoke_failures = {
        "wrong-sha": 'smoke test failed: readiness {"status": "ready", "model_sha256": "' + "0" * 64,
        "ready-wrong-sha": 'smoke test failed: readiness {"status": "ready", "model_sha256": "' + "0" * 64,
        "predict-wrong-sha": 'smoke test failed: prediction model {"distress_12m_probability": 0.0123, '
                             '"model_sha256": "' + "0" * 64,
        "not-ready": "urllib.error.HTTPError: HTTP Error 503: Service Unavailable",
        "prob-1.5": 'smoke test failed: prediction {"distress_12m_probability": 1.5,',
        "prob-neg": 'smoke test failed: prediction {"distress_12m_probability": -0.25,',
        "prob-int": 'smoke test failed: prediction {"distress_12m_probability": 1,',
    }
    for scenario, report in smoke_failures.items():
        code, out, state, _ = results["smoke-" + scenario]
        checks[f"smoke failure ({scenario}) is reported and the update rolled back"] = code == 1 and image(state) == GOOD \
            and report in out and "command terminated with exit code 1" in out and "smoke=passed" not in out \
            and f"failure=smoke digest={DIGEST[NEXT]}" in out \
            and result(out) == f"result=rolled_back digest={DIGEST[NEXT]} previous_digest={DIGEST[GOOD]}"

    code, out, state, _ = results["bad-uri"]
    checks["invalid image URI stops before kubectl runs"] = code == 1 and state["calls"] == [] and "FINRISK_IMAGE_URI rejected" in out

    outs = [out for _, out, _, _ in results.values()]
    checks["only the last evidence line of any run carries result="] = all(
        not any("result=" in l for l in evidence(o)[:-1]) for o in outs)
finally:
    shutil.rmtree(work, ignore_errors=True)

failure = report_checks()
if failure:
    raise SystemExit(failure)
