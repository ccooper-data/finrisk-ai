#!/usr/bin/env python3
from pathlib import Path

workflow = (
    Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-inference.yml"
).read_text()

checks = {
    "manual bounded deployment": "workflow_dispatch:" in workflow,
    "OIDC permission": "id-token: write" in workflow,
    "short-lived AWS credentials": "aws-actions/configure-aws-credentials@v5" in workflow,
    "immutable tag validation": "sha-[0-9a-f]{40}" in workflow,
    "digest resolution": "imageDigest" in workflow,
    "digest deployment": "@$digest" in workflow,
    "previous image captured": "Capture rollback target" in workflow,
    "rollout status verified": "rollout status deployment/finrisk-inference" in workflow,
    "readiness verified": "Verify readiness" in workflow,
    "rollback on failure": "Roll back failed deployment" in workflow,
    "rollback condition covers rollout failure": "steps.rollout.outcome != 'success'" in workflow,
    "rollback condition covers readiness failure": "steps.readiness.outcome != 'success'" in workflow,
    "rollback restores captured image": 'inference="${{ steps.previous.outputs.image }}"' in workflow,
    "rollback itself is health-checked": workflow.count("rollout status deployment/finrisk-inference --timeout=180s") >= 2,
    "failed rollout stays failed": "Fail after verified rollback" in workflow,
    "deployment evidence retained": "finrisk-deployment-evidence" in workflow,
    "deployment serialized": "cancel-in-progress: false" in workflow,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Delivery/recovery acceptance failed: " + ", ".join(failed))
