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
    "Terraform IAM mutation excludes bootstrap role": set(statements["ManageFinRiskRoles"]["Resource"]) == {
        "arn:aws:iam::*:role/finrisk-eks-cluster-*",
        "arn:aws:iam::*:role/finrisk-eks-nodes-*",
    },
    "bootstrap self-modification explicitly denied": statements["DenyBootstrapRoleSelfModification"]["Effect"] == "Deny"
        and statements["DenyBootstrapRoleSelfModification"]["Resource"].endswith("role/github-finrisk-deployer"),
    "bootstrap deny covers trust and permissions": {
        "iam:UpdateAssumeRolePolicy", "iam:AttachRolePolicy", "iam:DetachRolePolicy",
        "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:DeleteRole",
        "iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary",
        "iam:TagRole", "iam:UntagRole",
    }.issubset(actions(statements["DenyBootstrapRoleSelfModification"])),
    "managed attachments constrained": "iam:PolicyARN" in statements["AttachOnlyApprovedManagedPolicies"]["Condition"]["ArnEquals"],
    "pass role service constrained": "iam:PassedToService" in statements["PassOnlyFinRiskRolesToCompute"]["Condition"]["StringEquals"],
    "S3 bucket scope": statements["ManageFinRiskBuckets"]["Resource"] == "arn:aws:s3:::finrisk-*",
    "S3 object scope": statements["ManageFinRiskBucketObjects"]["Resource"] == "arn:aws:s3:::finrisk-*/*",
    "CloudTrail scoped": statements["ManageFinRiskCloudTrail"]["Resource"].endswith("trail/finrisk-*"),
    "budget uses real action": actions(statements["ManageFinRiskBudget"]) == {"budgets:ModifyBudget"},
    "OIDC read only": "iam:GetOpenIDConnectProvider" in actions(statements["ReadAccountAndInfrastructure"]),
}


trust = json.loads((ROOT / "docs" / "aws-bootstrap-trust-policy.json").read_text())

compact_policy = json.dumps(policy, separators=(",", ":"))
policy_chars = len(compact_policy)
trust_stmt = trust["Statement"][0]
trust_conditions = trust_stmt["Condition"]["StringEquals"]

checks.update({
    "inline role policy under AWS 10240-char limit": policy_chars <= 10240,
    "trust uses GitHub OIDC provider": trust_stmt["Principal"]["Federated"].endswith(
        ":oidc-provider/token.actions.githubusercontent.com"
    ),
    "trust audience pinned to STS": trust_conditions["token.actions.githubusercontent.com:aud"]
        == "sts.amazonaws.com",
    "trust subject pinned to FinRisk main": trust_conditions["token.actions.githubusercontent.com:sub"]
        == "repo:ccooper-data/finrisk-ai:ref:refs/heads/main",
})
print(f"INFO: compact inline policy size={policy_chars}/10240 characters")

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Bootstrap policy acceptance failed: " + ", ".join(failed))
