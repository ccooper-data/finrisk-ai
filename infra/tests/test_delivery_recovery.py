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
    "deploys the image built from its own commit": 'tag="sha-${GITHUB_SHA}"' in workflow and "sha-[0-9a-f]{40}" in workflow,
    "no image input to redirect the deploy": "inputs:" not in workflow,
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
    "failed first deploy is deleted, not left at zero replicas": 'delete deployment "$APP"' in buildspec and "--replicas=0" not in buildspec,
    "only NotFound counts as a first deploy": "--ignore-not-found" in buildspec and "2>/dev/null || true" not in buildspec,
    "rollback itself is health-checked": buildspec.count('rollout status deployment/"$APP" --timeout=300s') >= 2,
    "failed rollout stays failed": "result=rolled_back" in buildspec and "result=rollback_failed" in buildspec
        and buildspec.rstrip().endswith("exit 1\n        fi"),
    "deployment evidence retained": "finrisk-deployment-evidence" in workflow and "FINRISK_EVIDENCE" in runner,
    "deployment serialized with provision/destroy": "group: finrisk-bounded-aws-validation" in workflow
        and "cancel-in-progress: false" in workflow,
    "abandoned builds are stopped": "stop-build" in runner and "trap stop_if_running EXIT" in runner,
    "success requires the final evidence line": "final evidence line was not found" in runner and "--next-token" in runner,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Delivery/recovery acceptance failed: " + ", ".join(failed))
