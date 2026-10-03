#!/usr/bin/env python3
# Executes the rendered deploy buildspec against a stateful fake kubectl to check the deploy,
# rollback and abort paths end to end (substring checks cannot catch control-flow bugs). The fake
# runs the in-pod smoke script for real, against a stand-in for the inference API.
import base64
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (ROOT / "infra/terraform/deploy/deploy-buildspec.yml.tftpl").read_text()
FAKE_KUBECTL = ROOT / "infra/tests/fakes/kubectl.py"
GOOD = "780976819607.dkr.ecr.us-east-1.amazonaws.com/finrisk-ai-inference@sha256:" + "a" * 64
BAD = GOOD[:-64] + "b" * 64
NEXT = GOOD[:-64] + "c" * 64
MANIFEST = (ROOT / "infra/k8s/inference.yaml").read_text()
MODEL_SHA256 = "f" * 64
# The port the inference server listens on in the image; the Service must lead there.
CMD_PORT = re.search(r'"--port", "(\d+)"', (ROOT / "Dockerfile").read_text())
LISTEN_PORT = int(CMD_PORT[1]) if CMD_PORT else 0

values = {
    "cluster_name": "finrisk-ai-portfolio", "region": "us-east-1", "account_id": "780976819607",
    "repository": "finrisk-ai-inference", "namespace": "finrisk", "app": "finrisk-inference",
    "kubectl_version": "v1.35.9", "kubectl_sha256": "0" * 64, "model_sha256": MODEL_SHA256,
}


def render(manifest):
    rendered = TEMPLATE
    for key, value in dict(values, manifest_b64=base64.b64encode(manifest.encode()).decode()).items():
        rendered = rendered.replace("${" + key + "}", value)
    rendered = rendered.replace("$${", "${")
    script = yaml.safe_load(rendered)["phases"]["build"]["commands"][0]
    # The build runs in a scratch directory with its absolute paths made relative to it, so no
    # scratch or checkout path is ever pasted into shell source. That holds only without cd.
    return re.sub(r"(?<=[\s\"'<>])/tmp/", "tmp/", script.replace("/opt/finrisk/bin", "bin"))


script = render(MANIFEST)
shell = script.replace(base64.b64encode(MANIFEST.encode()).decode(), "")
checks = {
    "buildspec runs in the scratch directory (no cd, no absolute path left)": "/tmp/" not in shell
        and "/opt/" not in shell and re.search(r"(^|[\s;&|(])(cd|pushd|popd)(\s|$)", shell, re.M) is None,
    "image listen port found (Dockerfile CMD --port)": CMD_PORT is not None,
}


def stub(name, body):
    path = stubs / name
    path.write_text("#!/usr/bin/env bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def deploy(image, state, script="deploy.sh", **env):
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
    run_env.update(PATH=f"{stubs}{os.pathsep}{os.environ['PATH']}", FAKE_STATE=str(state),
                   FAKE_PYTHON=sys.executable, FAKE_KUBECTL=str(FAKE_KUBECTL), FAKE_MODEL_SHA256=MODEL_SHA256,
                   FAKE_LISTEN_PORT=str(LISTEN_PORT), FINRISK_IMAGE_URI=image, **env)
    result = subprocess.run(["bash", script], cwd=work, env=run_env, capture_output=True, text=True,
                            timeout=300)
    deployment = json.loads(state.read_text())["deployment"] if state.exists() else None
    return result.returncode, result.stdout + result.stderr, deployment


def miswire(change):
    """The manifest with change(inference container, first Service port) applied."""
    docs = [d for d in yaml.safe_load_all(MANIFEST) if d]
    kinds = {d["kind"]: d for d in docs}
    change(kinds["Deployment"]["spec"]["template"]["spec"]["containers"][0], kinds["Service"]["spec"]["ports"][0])
    return yaml.safe_dump_all(docs)


def fresh(name):
    return work / f"{name}.json"


def image(deployment):
    return deployment and deployment["image"]


def updated(name):
    """State in which GOOD is deployed at revision 1."""
    state = fresh(name)
    if base.exists():
        shutil.copy(base, state)
    return state


def unchanged(state, before):
    """Nothing after the server dry run: no apply, rollback or delete."""
    recorded = json.loads(state.read_text()) if state.exists() else {"deployment": None, "calls": [""]}
    return recorded["deployment"] == before and "--dry-run=server" in recorded["calls"][-1]


work = Path(tempfile.mkdtemp(prefix="finrisk-deploy-test-"))
try:
    stubs = work / "stubs"
    stubs.mkdir()
    (work / "tmp").mkdir()
    (work / "deploy.sh").write_text(script)

    # Network, checksum and AWS calls are not under test; kubectl is the fake. Paths reach the
    # stubs through the environment, quoted, so spaces in the checkout or TMPDIR cannot split them.
    stub("curl", 'out=""; while [ $# -gt 0 ]; do case "$1" in -fsSLo|-o) out="$2"; shift;; esac; shift; done; : > "$out"')
    stub("sha256sum", "cat >/dev/null; exit 0")
    stub("aws", "exit 0")
    stub("install", 'printf \'#!/usr/bin/env bash\\nexec "$FAKE_PYTHON" "$FAKE_KUBECTL" "$@"\\n\' > "${@: -1}"; chmod +x "${@: -1}"')
    # GNU and BSD sed differ on -i; the buildspec only uses -i "s#A#B#" FILE.
    stub("sed", 'exec "$FAKE_PYTHON" -c \'import sys; e=sys.argv[2]; f=sys.argv[3]; a,b=e[2:-1].split("#",1); p=open(f).read(); open(f,"w").write(p.replace(a,b))\' "$@"')

    code, out, dep = deploy(GOOD, fresh("first-ok"))
    checks["first deploy succeeds and records the revision"] = code == 0 and image(dep) == GOOD and "result=deployed" in out
    evidence = rf"^FINRISK_EVIDENCE smoke=passed model_sha256={MODEL_SHA256} feature_count=4 probability=0\.012300$"
    checks["smoke script runs in the pod and reports the pinned model"] = re.search(evidence, out, re.M) is not None

    base = fresh("base")
    code, out, before = deploy(GOOD, base)
    checks["update scenarios start from a healthy deploy"] = code == 0 and image(before) == GOOD

    code, out, dep = deploy(BAD, updated("update-fails"), FAKE_BAD_IMAGES=BAD)
    checks["failed update rolls back to the previous image"] = code == 1 and image(dep) == GOOD and "result=rolled_back" in out

    # The API stand-in breaks one thing per scenario (see fakes/kubectl.py); each check in the smoke
    # script is needed by one of them, except status == "ready", which every 200 from serving.py has.
    # The failure must be reported and the update rolled back.
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
        code, out, dep = deploy(NEXT, updated("smoke-" + scenario), FAKE_SMOKE=scenario)
        checks[f"smoke failure ({scenario}) is reported and the update rolled back"] = code == 1 and image(dep) == GOOD \
            and report in out and "command terminated with exit code 1" in out and "smoke=passed" not in out \
            and "result=rolled_back previous_revision=1" in out

    # In the cluster, the smoke test needs the container the manifest defines and reaches the API only
    # through a Service port that leads to the port the image listens on.
    miswired = {
        "container renamed": (lambda c, p: c.update(name=c["name"] + "-renamed"), "is not valid for pod"),
        "Service port": (lambda c, p: p.update(port=p["port"] + 1), "Connection refused"),
        "Service targetPort": (lambda c, p: p.update(targetPort=LISTEN_PORT + 1), "Connection refused"),
    }
    for name, (change, report) in miswired.items():
        (work / "miswired.sh").write_text(render(miswire(change)))
        code, out, dep = deploy(GOOD, fresh("miswired " + name), script="miswired.sh")
        checks[f"miswired manifest ({name}) fails the smoke test and the first deploy is removed"] = code == 1 \
            and dep is None and report in out and "smoke=passed" not in out \
            and "result=rolled_back previous_revision=none" in out

    state = fresh("first-fails")
    code, out, dep = deploy(BAD, state, FAKE_BAD_IMAGES=BAD)
    first_removed = code == 1 and dep is None
    code, out, dep = deploy(NEXT, state, FAKE_BAD_IMAGES=BAD)
    checks["failed first deploy is removed, so the next deploy is healthy"] = first_removed and code == 0 \
        and image(dep) == NEXT and dep["replicas"] >= 1

    # The dry run passes but the real apply fails before the Deployment exists: nothing to remove.
    code, out, dep = deploy(GOOD, fresh("first-apply-fails"), FAKE_FAIL_APPLY="1")
    checks["first deploy whose apply creates nothing reports a clean rollback"] = code == 1 and dep is None \
        and "result=rolled_back previous_revision=none" in out

    # Pod Security enforce rejects Pods, not the Deployment: the dry run only warns, with exit 0.
    state = updated("psa-warning")
    code, out, dep = deploy(NEXT, state, FAKE_PSA_WARNING="1")
    checks["Pod Security warning on the dry run stops before any change"] = code == 1 and unchanged(state, before) \
        and 'would violate PodSecurity "restricted:latest"' in out and "manifest rejected" in out and "result=" not in out

    state = updated("dry-run-fails")
    code, out, dep = deploy(NEXT, state, FAKE_FAIL_DRY_RUN="1")
    checks["failed dry run stops before any change, with its error shown"] = code != 0 and unchanged(state, before) \
        and "unable to return a response" in out and "result=" not in out

    state = updated("transient-get")
    code, out, dep = deploy(BAD, state, FAKE_BAD_IMAGES=BAD, FAKE_FAIL_REVISION_GET="1")
    calls = json.loads(state.read_text())["calls"] if state.exists() else []
    checks["revision lookup error aborts before any change"] = code != 0 and dep == before \
        and not any(c.startswith(("apply", "-n finrisk delete", "-n finrisk scale")) for c in calls[-3:])

    state = fresh("bad-uri")
    code, out, dep = deploy(GOOD + ";id", state)
    checks["invalid image URI stops before kubectl runs"] = code == 1 and not state.exists()
finally:
    shutil.rmtree(work, ignore_errors=True)

failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("Deploy buildspec runtime acceptance failed: " + ", ".join(failed))
