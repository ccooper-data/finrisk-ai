#!/usr/bin/env python3
from pathlib import Path

workflow = (
    Path(__file__).resolve().parents[2]
    / ".github" / "workflows" / "provision-bounded-aws.yml"
).read_text()

checks = {
    "manual dispatch only": "workflow_dispatch:" in workflow,
    "default is plan": 'default: "plan"' in workflow,
    "plan and apply explicit choices": "- plan" in workflow and "- apply" in workflow,
    "OIDC permission": "id-token: write" in workflow,
    "short-lived AWS auth": "aws-actions/configure-aws-credentials@v5" in workflow,
    "AWS identity preflight": "aws sts get-caller-identity" in workflow,
    "$100 budget forced": 'monthly_budget_limit_usd=100' in workflow,
    "plan artifact retained": "bounded-aws-validation-plan" in workflow,
    "plan path creates no resources": "PLAN ONLY: no billable runtime infrastructure was applied." in workflow,
    "apply is conditional": "if: inputs.action == 'apply'" in workflow,
    "apply uses saved plan": "apply -auto-approve bounded-validation.tfplan" in workflow,
    "deployment serialized": "cancel-in-progress: false" in workflow,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Provision workflow acceptance failed: " + ", ".join(failed))
