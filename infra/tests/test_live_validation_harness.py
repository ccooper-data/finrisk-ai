#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
script = (ROOT / "scripts" / "live_aws_validation.sh").read_text()
plan = (ROOT / "docs" / "live-aws-validation-plan.md").read_text()
runtime_test = (ROOT / "infra" / "tests" / "test_deploy_buildspec_runtime.py").read_text()

checks = {
    "strict shell mode": "set -euo pipefail" in script,
    "cleanup trap": "trap cleanup EXIT INT TERM" in script,
    "destroy on exit": 'terraform -chdir="$TF_DIR" destroy -auto-approve' in script,
    "destroy failure escalates": "CRITICAL destroy_failed manual_recovery_required" in script,
    "plan before apply": "plan -out=tfplan" in script,
    "automatic apply prohibited": "terraform -chdir=\"$TF_DIR\" apply" not in script,
    "explicit stop before billing": "apply is intentionally not automated" in script,
    "$100 ceiling documented": "$100 project ceiling" in plan,
    "$75 stop condition": "reaches $75" in plan,
    "five evidence areas": all(term in plan for term in [
        "EKS scheduling", "HPA", "Telemetry", "Rollback", "Teardown/cost"
    ]),
    "runtime claims evidence-gated": "No live-runtime claim is permitted without this evidence." in plan,
    # The deploy takes no image input and main is frozen PLAN to DESTROY, so a window cannot ship a
    # non-ready candidate; rollback evidence is the buildspec run against the fake kubectl.
    "rollback evidence obtainable without breaking the freeze":
        "non-ready candidate through the controlled workflow" not in plan
        and "infra/tests/test_deploy_buildspec_runtime.py" in plan
        and "failed update rolls back to the previous image" in runtime_test
        and "Never inject a failure by committing to `main`" in plan,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Live-validation harness acceptance failed: " + ", ".join(failed))
