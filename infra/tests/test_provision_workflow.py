#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
workflow = (ROOT / ".github" / "workflows" / "provision-bounded-aws.yml").read_text()
versions = (ROOT / "infra" / "terraform" / "versions.tf").read_text()
variables = (ROOT / "infra" / "terraform" / "variables.tf").read_text()

checks = {
    "manual dispatch only": "workflow_dispatch:" in workflow,
    "default is plan": 'default: "plan"' in workflow,
    "explicit lifecycle actions": all(x in workflow for x in ["- plan", "- apply-reviewed-plan", "- destroy"]),
    "OIDC permission": "id-token: write" in workflow,
    "remote S3 backend required": 'backend "s3" {}' in versions,
    "backend bucket configured": 'TF_STATE_BUCKET' in workflow,
    "DynamoDB locking configured": 'dynamodb_table=' in workflow and 'TF_LOCK_TABLE' in workflow,
    "budget email is not workflow input": "budget_alert_email:" not in workflow.split("permissions:")[0],
    "budget email comes from secret": 'secrets.BUDGET_ALERT_EMAIL' in workflow,
    "budget email Terraform variable sensitive": "sensitive   = true" in variables,
    "plan creates binary plan": "plan -out=bounded-validation.tfplan" in workflow,
    "no JSON plan published": "show -json" not in workflow,
    "binary plan retained": "bounded-validation.tfplan" in workflow and "bounded-aws-reviewed-plan" in workflow,
    "apply requires plan run ID": "plan_run_id" in workflow,
    "apply downloads prior plan": "actions/download-artifact@v4" in workflow and "run-id:" in workflow,
    "apply exact binary only": "apply -auto-approve bounded-validation.tfplan" in workflow,
    "destroy action exists": 'inputs.action == \'destroy\'' in workflow and "destroy -auto-approve" in workflow,
    "destroy verifies empty state": "state list" in workflow,
    "serialized lifecycle": "cancel-in-progress: false" in workflow,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Provision workflow acceptance failed: " + ", ".join(failed))
