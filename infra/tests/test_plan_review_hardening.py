#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
policy = json.loads((ROOT / "docs" / "aws-bootstrap-policy.json").read_text())
eks = (ROOT / "infra" / "terraform" / "eks.tf").read_text()
variables = (ROOT / "infra" / "terraform" / "variables.tf").read_text()
main = (ROOT / "infra" / "terraform" / "main.tf").read_text()
security = (ROOT / "infra" / "terraform" / "security.tf").read_text()
workflow = (ROOT / ".github" / "workflows" / "provision-bounded-aws.yml").read_text()
statements = {s["Sid"]: s for s in policy["Statement"]}

roles = {
    "arn:aws:iam::*:role/finrisk-ai-eks-cluster-*",
    "arn:aws:iam::*:role/finrisk-ai-eks-nodes-*",
}
checks = {
    "role scopes match generated names": set(statements["ManageFinRiskRoles"]["Resource"]) == roles
        and set(statements["PassOnlyFinRiskRolesToCompute"]["Resource"]) == roles
        and statements["AttachApprovedClusterPolicy"]["Resource"] == "arn:aws:iam::*:role/finrisk-ai-eks-cluster-*"
        and statements["AttachApprovedNodePolicies"]["Resource"] == "arn:aws:iam::*:role/finrisk-ai-eks-nodes-*"
        and "var.project_name}-eks-cluster-" in eks and "var.project_name}-eks-nodes-" in eks,
    "role creation requires boundary": statements["CreateBoundedFinRiskRoles"]["Condition"]["StringEquals"]["iam:PermissionsBoundary"]
        == "arn:aws:iam::780976819607:policy/finrisk-ai-eks-boundary",
    "Terraform attaches boundary": eks.count("permissions_boundary") == 2,
    "KMS alias ARN covers generated alias": statements["ManageFinRiskKMSAlias"]["Resource"]
        == "arn:aws:kms:us-east-1:780976819607:alias/finrisk-ai-*"
        and "var.project_name}-artifacts" in security,
    "budget ARN covers generated name": statements["ManageFinRiskBudget"]["Resource"]
        == "arn:aws:budgets::780976819607:budget/finrisk-ai-*"
        and "var.project_name}-${var.environment}-validation-alerts" in main,
    "EKS standard support": 'support_type = "STANDARD"' in eks and 'default     = "1.35"' in variables,
    "teardown deadline recorded": 'VALIDATION_MAX_HOURS: "6"' in workflow and "teardown-deadline.txt" in workflow,
}
failed = [k for k,v in checks.items() if not v]
for k,v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("Plan review hardening failed: " + ", ".join(failed))
