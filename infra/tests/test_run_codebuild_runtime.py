#!/usr/bin/env python3
# Runs .github/scripts/run-codebuild.sh and the deploy workflow's build and cleanup steps against a
# fake aws CLI. Retries, stops and cancel signals are control flow that substring checks cannot
# catch.
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / ".github/scripts/run-codebuild.sh"
FAKE_AWS = ROOT / "infra/tests/fakes/aws.py"
workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-inference.yml").read_text())
steps = {s.get("name"): s for s in workflow["jobs"]["deploy"]["steps"]}
BOOTSTRAP, DEPLOY = workflow["env"]["BOOTSTRAP_PROJECT"], workflow["env"]["DEPLOY_PROJECT"]
IMAGE = "780976819607.dkr.ecr.us-east-1.amazonaws.com/finrisk-ai-inference@sha256:" + "a" * 64
DEPLOY_ARGS = [str(RUNNER), DEPLOY, f"FINRISK_IMAGE_URI={IMAGE}"]

work = Path(tempfile.mkdtemp(prefix="finrisk-runner-test-"))
fake_bin, no_sleep = work / "bin", work / "nosleep"
fake_bin.mkdir()
no_sleep.mkdir()


def stub(path, body):
    path.write_text("#!/usr/bin/env bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


stub(fake_bin / "aws", f'exec "{sys.executable}" "{FAKE_AWS}" "$@"')
# Waits are not under test except in the cancel checks, which use the real sleep.
stub(no_sleep / "sleep", "exit 0")


def start(name, command, polls=("SUCCEEDED",), logs=("OK",), evidence="", real_sleep=False, env=None):
    state, evidence_file = work / f"{name}.json", work / f"{name}.txt"
    state.write_text(json.dumps({"polls": list(polls), "logs": list(logs), "calls": [],
                                 "events": ["FINRISK_EVIDENCE result=deployed revision=2"]}))
    evidence_file.write_text(evidence)
    path = [str(fake_bin)] + ([] if real_sleep else [str(no_sleep)]) + [os.environ["PATH"]]
    run_env = dict(os.environ, **(env or {}))
    run_env.update(PATH=os.pathsep.join(path), FAKE_AWS_STATE=str(state), EVIDENCE_FILE=str(evidence_file))
    # Own process group, so leftovers can be killed; SIGINT reset in case this runs with it ignored.
    with open(work / f"{name}.out", "w") as out:
        proc = subprocess.Popen(command, cwd=ROOT, env=run_env, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True,
                                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    return proc, name


def finish(run, timeout):
    proc, name = run
    try:
        code = proc.wait(timeout)
    except subprocess.TimeoutExpired:
        code = None
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()
    calls = json.loads((work / f"{name}.json").read_text())["calls"]
    return code, (work / f"{name}.out").read_text(), calls, (work / f"{name}.txt").read_text()


def stops(calls):
    return [c for c in calls if c.startswith("codebuild stop-build")]


def cancel(name, command, env=None):
    """Signal only the entry process, as the runner does on cancel, once the build is being polled."""
    run = start(name, command, polls=["IN_PROGRESS"], real_sleep=True, env=env)
    state = work / f"{name}.json"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and "batch-get-builds" not in state.read_text():
        time.sleep(0.1)
    time.sleep(1)
    os.kill(run[0].pid, signal.SIGINT)
    # The runner sends SIGTERM 7.5 seconds after SIGINT and kills the step 2.5 seconds later.
    return finish(run, 5)


def step_script(name):
    run = steps.get(name, {}).get("run", "exit 99")
    path = work / (name.replace(" ", "-") + ".sh")
    path.write_text(run.replace("${{ steps.image.outputs.uri }}", IMAGE))
    # A run step with no shell runs as `bash -e <script>` on Linux runners.
    return ["bash", "-e", str(path)], dict(workflow["env"], **steps.get(name, {}).get("env", {}))


checks = {}

code, out, calls, evidence = finish(start("transient-status", DEPLOY_ARGS,
                                          polls=["IN_PROGRESS", "FAIL", "FAIL", "IN_PROGRESS", "SUCCEEDED"]), 30)
checks["a failed status read is retried, not a reason to stop the build"] = code == 0 and not stops(calls) \
    and f"{DEPLOY}_status=SUCCEEDED" in evidence and f"{DEPLOY}: result=deployed revision=2" in evidence

code, out, calls, evidence = finish(start("transient-logs", DEPLOY_ARGS, logs=["FAIL", "OK"]), 30)
checks["a failed log read is retried and the evidence still copied"] = code == 0 and not stops(calls) \
    and f"{DEPLOY}: result=deployed revision=2" in evidence

code, out, calls, evidence = finish(start("unreadable-logs", DEPLOY_ARGS, polls=["FAILED"], logs=["FAIL"]), 30)
checks["unreadable logs still reach the status check"] = code == 1 and not stops(calls) \
    and f"build {DEPLOY}:build-1 finished with status FAILED" in out

code, out, calls, evidence = finish(start("deadline", DEPLOY_ARGS, polls=["IN_PROGRESS"],
                                          env={"CODEBUILD_WAIT_MINUTES": "0"}), 30)
checks["the deadline stops the build"] = code == 1 and "Timed out" in out and len(stops(calls)) == 1

code, out, calls, evidence = finish(start("status-unreadable", DEPLOY_ARGS, polls=["FAIL"],
                                          env={"CODEBUILD_WAIT_MINUTES": "0"}), 30)
checks["status read errors stop the build only at the deadline"] = code == 1 and "Timed out" in out \
    and "Could not read the status" in out and len(stops(calls)) == 1

code, out, calls, evidence = cancel("cancel-runner", DEPLOY_ARGS)
checks["SIGINT stops the build at once, not after the poll sleep"] = code == 130 and len(stops(calls)) == 1

for step in ("Bootstrap namespace", "Deploy digest-pinned image"):
    command, env = step_script(step)
    code, out, calls, evidence = cancel(step, command, env)
    checks[f"cancelling '{step}' reaches the runner's stop-build trap"] = code == 130 and len(stops(calls)) == 1

command, env = step_script("Stop unfinished builds")
recorded = (f"{BOOTSTRAP}_build_id={BOOTSTRAP}:build-0\n{BOOTSTRAP}_status=SUCCEEDED\n"
            f"{DEPLOY}_build_id={DEPLOY}:build-1\n")
# The fake reports IN_PROGRESS once after stop-build, so STOPPED in the evidence means it waited.
code, out, calls, evidence = finish(start("cleanup", command, evidence=recorded, env=env), 30)
checks["cleanup stops only the unfinished build and waits until it has stopped"] = code == 0 \
    and stops(calls) == [f"codebuild stop-build --id {DEPLOY}:build-1"] \
    and evidence.endswith(f"{DEPLOY}_status_after_stop=STOPPED\n")

code, out, calls, evidence = finish(start("cleanup-noop", command, evidence=recorded + f"{DEPLOY}_status=FAILED\n",
                                          env=env), 30)
checks["cleanup leaves finished builds alone"] = code == 0 and calls == []

shutil.rmtree(work, ignore_errors=True)
failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("run-codebuild runtime acceptance failed: " + ", ".join(failed))
