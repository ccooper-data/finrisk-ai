#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
policy = json.loads((ROOT / "docs" / "aws-bootstrap-policy.json").read_text())
security = (ROOT / "infra" / "terraform" / "security.tf").read_text()
statements = {s["Sid"]: s for s in policy["Statement"]}

def actions(statement):
    value = statement["Action"]
    return {value} if isinstance(value, str) else set(value)

checks = {
    "Terraform does not create OIDC provider": 'resource "aws_iam_openid_connect_provider"' not in security,
    "Terraform does not create bootstrap GitHub role": 'resource "aws_iam_role" "github_deploy"' not in security,
    "no OIDC create/delete permissions": not (
        {"iam:CreateOpenIDConnectProvider", "iam:DeleteOpenIDConnectProvider"}
        & set().union(*(actions(s) for s in policy["Statement"]))
    ),
    "IAM roles scoped to finrisk": statements["ManageFinRiskRoles"]["Resource"].endswith("role/finrisk-*"),
    "managed attachments constrained": "iam:PolicyARN" in statements["AttachOnlyApprovedManagedPolicies"]["Condition"]["ArnEquals"],
    "pass role service constrained": "iam:PassedToService" in statements["PassOnlyFinRiskRolesToCompute"]["Condition"]["StringEquals"],
    "S3 bucket scope": statements["ManageFinRiskBuckets"]["Resource"] == "arn:aws:s3:::finrisk-*",
    "S3 object scope": statements["ManageFinRiskBucketObjects"]["Resource"] == "arn:aws:s3:::finrisk-*/*",
    "CloudTrail scoped": statements["ManageFinRiskCloudTrail"]["Resource"].endswith("trail/finrisk-*"),
    "budget uses real action": actions(statements["ManageFinRiskBudget"]) == {"budgets:ModifyBudget"},
    "OIDC read only": "iam:GetOpenIDConnectProvider" in actions(statements["ReadAccountAndInfrastructure"]),
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Bootstrap policy acceptance failed: " + ", ".join(failed))
