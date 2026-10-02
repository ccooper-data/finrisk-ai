#!/usr/bin/env python3
# Executes the rendered deploy buildspec against a stateful fake kubectl to check the deploy,
# rollback and abort paths end to end (substring checks cannot catch control-flow bugs).
import json
import os
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

values = {
    "cluster_name": "finrisk-ai-portfolio", "region": "us-east-1", "account_id": "780976819607",
    "repository": "finrisk-ai-inference", "namespace": "finrisk", "app": "finrisk-inference",
    "kubectl_version": "v1.35.9", "kubectl_sha256": "0" * 64, "model_sha256": "f" * 64,
    "manifest_b64": __import__("base64").b64encode(MANIFEST.encode()).decode(),
}
rendered = TEMPLATE
for key, value in values.items():
    rendered = rendered.replace("${" + key + "}", value)
rendered = rendered.replace("$${", "${")
script = yaml.safe_load(rendered)["phases"]["build"]["commands"][0]

work = Path(tempfile.mkdtemp(prefix="finrisk-deploy-test-"))
stubs = work / "stubs"
stubs.mkdir()
script = script.replace("/opt/finrisk/bin", str(work / "bin")).replace("/tmp/", f"{work}/")
(work / "deploy.sh").write_text(script)


def stub(name, body):
    path = stubs / name
    path.write_text("#!/usr/bin/env bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


# Network, checksum and AWS calls are not under test; kubectl is the fake.
stub("curl", 'out=""; while [ $# -gt 0 ]; do case "$1" in -fsSLo|-o) out="$2"; shift;; esac; shift; done; : > "$out"')
stub("sha256sum", "cat >/dev/null; exit 0")
stub("aws", "exit 0")
stub("install", f'target="${{@: -1}}"; printf \'#!/usr/bin/env bash\\nexec {sys.executable} {FAKE_KUBECTL} "$@"\\n\' > "$target"; chmod +x "$target"')
# GNU and BSD sed differ on -i; the buildspec only uses -i "s#A#B#" FILE.
stub("sed", f'exec {sys.executable} -c \'import re,sys; e=sys.argv[2]; f=sys.argv[3]; a,b=e[2:-1].split("#",1); p=open(f).read(); open(f,"w").write(p.replace(a,b))\' "$@"')


def deploy(image, state, **env):
    run_env = dict(os.environ, PATH=f"{stubs}:{os.environ['PATH']}", FAKE_STATE=str(state),
                   FINRISK_IMAGE_URI=image, **env)
    result = subprocess.run(["bash", str(work / "deploy.sh")], env=run_env, capture_output=True, text=True)
    deployment = json.loads(state.read_text())["deployment"] if state.exists() else None
    return result.returncode, result.stdout + result.stderr, deployment


def fresh(name):
    return work / f"{name}.json"


checks = {}

code, out, dep = deploy(GOOD, fresh("first-ok"))
checks["first deploy succeeds and records the revision"] = code == 0 and dep["image"] == GOOD and "result=deployed" in out

state = fresh("update-fails")
deploy(GOOD, state)
code, out, dep = deploy(BAD, state, FAKE_BAD_IMAGES=BAD)
checks["failed update rolls back to the previous image"] = code == 1 and dep["image"] == GOOD and "result=rolled_back" in out

state = fresh("first-fails")
code, out, dep = deploy(BAD, state, FAKE_BAD_IMAGES=BAD)
first_removed = code == 1 and dep is None
code, out, dep = deploy(NEXT, state, FAKE_BAD_IMAGES=BAD)
checks["failed first deploy is removed, so the next deploy is healthy"] = first_removed and code == 0 \
    and dep["image"] == NEXT and dep["replicas"] >= 1

state = fresh("transient-get")
deploy(GOOD, state)
before = json.loads(state.read_text())["deployment"]
code, out, dep = deploy(BAD, state, FAKE_BAD_IMAGES=BAD, FAKE_FAIL_REVISION_GET="1")
calls = json.loads(state.read_text())["calls"]
checks["revision lookup error aborts before any change"] = code != 0 and dep == before \
    and not any(c.startswith(("apply", "-n finrisk delete", "-n finrisk scale")) for c in calls[-3:])

state = fresh("bad-uri")
code, out, dep = deploy(GOOD + ";id", state)
checks["invalid image URI stops before kubectl runs"] = code == 1 and not state.exists()

shutil.rmtree(work, ignore_errors=True)
failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("Deploy buildspec runtime acceptance failed: " + ", ".join(failed))
