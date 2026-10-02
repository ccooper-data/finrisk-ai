#!/usr/bin/env python3
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
boundary=json.loads((ROOT/"docs/aws-eks-boundary-policy.json").read_text())
bootstrap=json.loads((ROOT/"docs/aws-bootstrap-policy.json").read_text())
main=(ROOT/"infra/terraform/main.tf").read_text()
provision=(ROOT/".github/workflows/provision-bounded-aws.yml").read_text()
reaper=(ROOT/".github/workflows/reap-bounded-aws.yml").read_text()
contract=(ROOT/"docs/bounded-aws-validation.md").read_text()

allowed=set()
for s in boundary["Statement"]:
    a=s["Action"]; allowed.update([a] if isinstance(a,str) else a)

required={
 "eks:*",
 "ecr:GetAuthorizationToken","ecr:BatchCheckLayerAvailability","ecr:GetDownloadUrlForLayer","ecr:BatchGetImage",
 "ec2:AssignPrivateIpAddresses","ec2:AttachNetworkInterface","ec2:CreateNetworkInterface",
 "ec2:DeleteNetworkInterface","ec2:DescribeNetworkInterfaces","ec2:DetachNetworkInterface",
 "ec2:ModifyNetworkInterfaceAttribute","ec2:UnassignPrivateIpAddresses",
 "ec2:DescribeInstances","ec2:DescribeInstanceTypes","ec2:DescribeRegions","ec2:DescribeAvailabilityZones",
 "ec2:DescribeRouteTables","ec2:DescribeSecurityGroups","ec2:DescribeSubnets","ec2:DescribeVpcs",
}
stmts={s["Sid"]:s for s in bootstrap["Statement"]}
checks={
 "boundary covers role runtime": required.issubset(allowed),
 "KMS alias authorized on alias and key": set(stmts["ManageFinRiskKMSAlias"]["Action"]) >= {"kms:CreateAlias","kms:DeleteAlias"}
   and set(stmts["AuthorizeFinRiskKMSAliasOnKeys"]["Action"]) == {"kms:CreateAlias","kms:DeleteAlias"}
   and stmts["AuthorizeFinRiskKMSAliasOnKeys"]["Resource"]=="arn:aws:kms:us-east-1:780976819607:key/*",
 "KMS key admin escalation removed": not ({"kms:PutKeyPolicy","kms:CreateGrant"} & set(stmts["ManageFinRiskKMS"]["Action"])),
 "budget at most five alerts": 'budget_thresholds = toset(["10", "25", "50", "75", "100"])' in main and "FORECASTED" not in main,
 "lease written before apply": provision.index("Write teardown lease before apply") < provision.index("Apply exact reviewed binary plan"),
 "reaper separate concurrency": "group: finrisk-bounded-aws-reaper" in reaper,
 "reaper scheduled": 'cron: "17 * * * *"' in reaper,
 "reaper does not swallow state errors": "terraform -chdir=\"$TF_DIR\" state list > state.txt" in reaper,
 "validation contract ACTIVE only": "control plane reaches `ACTIVE`" in contract and "node group reaches `ACTIVE`" in contract,
}
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed: raise SystemExit("Second review hardening failed: "+", ".join(failed))
