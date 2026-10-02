#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
workflow = (ROOT / ".github" / "workflows" / "deploy-inference.yml").read_text()
runner = (ROOT / ".github" / "scripts" / "run-codebuild.sh").read_text()
buildspec = (ROOT / "infra" / "terraform" / "deploy" / "deploy-buildspec.yml.tftpl").read_text()

checks = {
    "manual bounded deployment": "workflow_dispatch:" in workflow,
    "OIDC permission": "id-token: write" in workflow,
    "short-lived AWS credentials": "aws-actions/configure-aws-credentials@v5" in workflow,
    "release role, not the Terraform role": "vars.AWS_RELEASE_ROLE_ARN" in workflow and "AWS_DEPLOY_ROLE_ARN" not in workflow,
    "immutable tag validation": "sha-[0-9a-f]{40}" in workflow,
    "digest resolution": "imageDigest" in workflow,
    "digest deployment": "@$digest" in workflow and 'FINRISK_IMAGE_URI=${{ steps.image.outputs.uri }}' in workflow,
    "namespace bootstrapped before deploy": workflow.index("Bootstrap namespace") < workflow.index("Deploy digest-pinned image"),
    "build failure fails the job": 'if [ "$status" != "SUCCEEDED" ]' in runner,
    "previous revision captured before apply": "PREV_REV=" in buildspec
        and buildspec.index("PREV_REV=") < buildspec.index("deploy_and_verify() {"),
    "rollout status verified": 'rollout status deployment/"$APP" --timeout=300s' in buildspec,
    "readiness verified": "{.status.readyReplicas}" in buildspec,
    "in-pod smoke test checks the pinned model": "exec -i deploy/\"$APP\"" in buildspec and 'EXPECTED = "${model_sha256}"' in buildspec,
    "rollback to the recorded revision": '--to-revision="$PREV_REV"' in buildspec,
    "first deploy has its own failure path": "--replicas=0" in buildspec,
    "rollback itself is health-checked": buildspec.count('rollout status deployment/"$APP" --timeout=300s') >= 2,
    "failed rollout stays failed": "result=rolled_back" in buildspec and "result=rollback_failed" in buildspec
        and buildspec.rstrip().endswith("exit 1\n        fi"),
    "deployment evidence retained": "finrisk-deployment-evidence" in workflow and "FINRISK_EVIDENCE" in runner,
    "deployment serialized": "cancel-in-progress: false" in workflow,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Delivery/recovery acceptance failed: " + ", ".join(failed))
