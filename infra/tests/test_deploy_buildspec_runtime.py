#!/usr/bin/env python3
# Executes the rendered deploy buildspec against a stateful fake kubectl (fakes/kubectl.py: the Argo CD
# Application, its controller, the Deployment it syncs, the runner's authorization) to check the GitOps
# deploy, rollback, retention and abort paths end to end (substring checks cannot catch control-flow
# bugs). The fake runs the in-pod smoke and PromQL scripts for real, against stand-ins for the inference
# API and Prometheus. Time is a fake clock that only `sleep` advances, so every wait's bound is exercised
# exactly and fast. Each convergence check is shown to matter alone: the fake falsifies one thing (FAKE_SKEW)
# and the buildspec without that one check (a negative control) deploys.
import copy
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
BUILD_TIMEOUT = int(re.search(r'resource "aws_codebuild_project" "k8s_deploy" \{.*?build_timeout\s+= (\d+)',
                              (ROOT / "infra/terraform/deploy_path.tf").read_text(), re.S)[1])
REPOSITORY = "780976819607.dkr.ecr.us-east-1.amazonaws.com/finrisk-ai-inference"
GOOD, BAD, NEXT = (f"{REPOSITORY}@sha256:" + c * 64 for c in "abc")
DIGEST = {uri: uri.split("@")[1] for uri in (GOOD, BAD, NEXT)}
REVISION = "0123456789abcdef0123456789abcdef01234567"
MODEL_SHA256 = "f" * 64
START = 1_000_000

values = {
    "cluster_name": "finrisk-ai-portfolio", "region": "us-east-1", "account_id": "780976819607",
    "repository": "finrisk-ai-inference", "namespace": "finrisk", "argocd_namespace": "argocd", "app": "finrisk-inference",
    "kubectl_version": "v1.35.9", "kubectl_sha256": "0" * 64, "model_sha256": MODEL_SHA256, "gitops_revision": REVISION,
    "repo_url": "https://github.com/ccooper-data/finrisk-ai.git", "chart_path": "charts/finrisk-inference",
    "prometheus_url": "http://monitoring-prometheus.monitoring.svc.cluster.local:9090",
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
    begin.update(calls=[], patches=[], unbounded=[])
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


AUTHZ = ("authz patch_app=yes get_app=yes patch_other_app=no create_app=no delete_app=no patch_appproject=no "
         "argocd_secrets=no create_rolebindings=no")
PROMQL = ["promql name=app_up value=1", "promql name=ksm_up value=1", "promql name=requests value=1",
          "promql name=latency_mean_ms value=12.5", "promql name=predictions value=1", "promql name=inference_p95_ms value=20.5",
          "promql name=replicas_available value=1", "promql name=hpa_current_replicas value=1"]
SMOKE = rf"^FINRISK_EVIDENCE smoke=passed model_sha256={MODEL_SHA256} feature_count=4 probability=0\.012300$"
# FAKE_SKEW name (fakes/kubectl.py) -> the one check of the buildspec's `ok` that it fails.
SKEWS = {s: s for s in ("sync", "revision", "operation_revision", "compared", "operation", "synced", "synced_revision", "automated",
                        "health", "image", "observed", "ready")}
SKEWS.update(source="override", sources="override", manifests="override")


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
    # Downloads, checksums, AWS and time are not under test; kubectl is the fake. Paths reach the stubs
    # through the environment, quoted, so spaces in the checkout or TMPDIR cannot split them.
    stub("curl", 'out=""; while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift;; esac; shift; done; : > "$out"')
    stub("sha256sum", "cat >/dev/null; exit 0")
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
    checks["evidence: authz, target revision, argocd, smoke, PromQL, then the result"] = [l.split()[0] for l in lines] == [
        "authz", "argocd_target_revision=" + REVISION, "argocd", "smoke=passed", *["promql"] * 8, lines[-1].split()[0]] \
        and lines[0] == AUTHZ and lines[1] == f"argocd_target_revision={REVISION} previous_digest=none"
    checks["argocd evidence: Synced and Healthy at the PLAN's commit and this digest, by an automated sync"] = any(
        l.startswith(f"argocd digest={DIGEST[GOOD]} sync=Synced revision={REVISION} compared={DIGEST[GOOD]} operation=Succeeded "
                     f"synced={DIGEST[GOOD]} synced_revision={REVISION} health=Healthy automated=True overrides=none image={GOOD} ready=1")
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
        "rollback-observe-lag": (BAD, "first-ok", {"FAKE_BAD_IMAGES": DIGEST[BAD], "FAKE_OBSERVE_LAG": "1"}),
        **{"skew-" + s: (NEXT, "first-ok", {"FAKE_SKEW": s, "FAKE_SKEW_DIGEST": DIGEST[NEXT]}) for s in SKEWS},
        "app-read-fails": (NEXT, "first-ok", {"FAKE_APP_GET_FAIL": "1"}),
        **{"rbac-" + r: (NEXT, "first-ok", {"FAKE_RBAC": r}) for r in ("no-group", "extra-delete", "any-name", "argocd-secrets")},
        **{"prom-" + p: (NEXT, "first-ok", {"FAKE_PROM": p}) for p in ("app-down", "no-ksm", "unscraped", "unreachable")},
        **{"smoke-" + s: (NEXT, "first-ok", {"FAKE_SMOKE": s}) for s in (
            "wrong-sha", "ready-wrong-sha", "predict-wrong-sha", "not-ready", "prob-1.5", "prob-neg", "prob-int")},
        "bad-uri": (GOOD + ";id", "first-ok", {}),
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
    # Negative control: a convergence check that trusts Synced and Healthy without the digests (compared,
    # synced, the operation's source, the Deployment's image).
    scripts["trusts-stale-status"] = without("compared", "synced", "override", "image")
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
                                                         FAKE_BAD_IMAGES=DIGEST[BAD], FAKE_OBSERVE_LAG="1")
    jobs["extra-json-patch"] = lambda: deploy("extra-json-patch", NEXT, "first-ok", script=scripts["extra-json-patch"])
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(zip(jobs, pool.map(lambda f: f(), jobs.values())))
    controls = {"trusts-stale-status", "deadline-ignores-generation", "extra-json-patch", *("without " + s for s in SKEWS)}
    every = [first, *(r[2] for name, r in results.items() if name not in controls)]
    checks["no call reaches the API server without a bound (fake kubectl refuses one)"] = not any(s.get("unbounded") for s in every)
    checks["no call the fake does not model, and no patch but the digest patch, in any scenario"] = not any(map(stray_calls, every))
    code, out, state, _ = results["extra-json-patch"]
    checks["negative control: a second (JSON) patch whose refusal is ignored is caught"] = bool(stray_calls(state)) \
        and result(out) is not None and result(out).startswith("result=deployed")
    checks["no scenario takes longer than build_timeout on the fake clock"] = all(r[3] < BUILD_TIMEOUT * 60 for r in results.values())

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
    checks["redeploying the running digest is a no-op patch that verifies"] = code == 0 and digest(state) == [DIGEST[GOOD]] \
        and result(out).endswith(f"previous_digest={DIGEST[GOOD]}") and state["deployment"]["revision"] == 1 and seconds <= 10

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

    code, out, state, _ = results["rollback-observe-lag"]
    checks["a re-patch is not failed on the previous image's progress deadline before the Deployment observes it"] = \
        code == 1 and result(out) == f"result=rolled_back digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]}" and image(state) == GOOD
    code, out, state, _ = results["deadline-ignores-generation"]
    checks["negative control: a deadline verdict without observedGeneration fails that rollback"] = code == 1 \
        and result(out) == f"result=rollback_failed digest={DIGEST[BAD]} previous_digest={DIGEST[GOOD]} failure=progress_deadline"

    code, out, state, _ = results["app-read-fails"]
    checks["an Application read error stops before any change"] = code == 1 and unchanged(state) \
        and "not read or not as reviewed; nothing changed" in out and result(out) is None

    for name in drift:
        code, out, state, _ = results["drift " + name]
        checks[f"Application drift ({name}) stops before any change"] = code == 1 and unchanged(state) \
            and "Application not as reviewed" in out and result(out) is None

    for name, answer in {"no-group": "patch_app=no", "extra-delete": "delete_app=yes", "any-name": "patch_other_app=yes",
                         "argocd-secrets": "argocd_secrets=yes"}.items():
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
