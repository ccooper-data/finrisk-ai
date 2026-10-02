#!/usr/bin/env python3
# Follow-ups from the first bounded AWS validation window (2026-10-02).
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
provision=(ROOT/".github/workflows/provision-bounded-aws.yml").read_text()
reaper=(ROOT/".github/workflows/reap-bounded-aws.yml").read_text()
eks=(ROOT/"infra/terraform/eks.tf").read_text()
outputs=(ROOT/"infra/terraform/outputs.tf").read_text()
# Only source files: CI runs `terraform init` first, which adds a .terraform directory here.
TF_DIR=ROOT/"infra/terraform"
tf_text={p.name:p.read_text() for p in [*TF_DIR.glob("*.tf"),TF_DIR/"README.md"]}
policy=json.loads((ROOT/"docs/aws-bootstrap-policy.json").read_text())
stmts={s["Sid"]:s for s in policy["Statement"]}

def block(text,header):
    """Return the brace-balanced block that starts at header."""
    start=text.index(header); depth=0
    for i in range(text.index("{",start),len(text)):
        depth+={"{":1,"}":-1}.get(text[i],0)
        if depth==0: return text[start:i+1]
    raise ValueError(header)

def block_or_empty(text,header):
    return block(text,header) if header in text else ""

node_group=block(eks,'resource "aws_eks_node_group" "platform"')
cluster=block(eks,'resource "aws_eks_cluster" "platform"')
az_data=block_or_empty(eks,'data "aws_availability_zones" "eks"')
node_deps=re.search(r"depends_on\s*=\s*\[(.*?)\]",node_group,re.S).group(1)
profile_stmt=[s for s in policy["Statement"] if "iam:RemoveRoleFromInstanceProfile" in json.dumps(s["Action"])]

checks={
 "reaper treats a missing state object as empty": "state list > state.txt 2> state.err" in reaper
   and "No state file was found" in reaper and ": > state.txt" in reaper,
 "both workflows request 2h credentials": provision.count("role-duration-seconds: 7200")==1 and reaper.count("role-duration-seconds: 7200")==1,
 "lease shortened to 4h": 'VALIDATION_MAX_HOURS: "4"' in provision,
 "apply waits for the state lock": "apply -lock-timeout=10m -auto-approve bounded-validation.tfplan" in provision,
 "destroy waits for the state lock": provision.count("destroy -auto-approve -lock-timeout=10m")==1 and "destroy -auto-approve -lock-timeout=10m" in reaper,
 "AZ IDs resolved from the configured zone names": 'name   = "zone-name"' in az_data and "var.availability_zones" in az_data,
 "PLAN fails on an EKS-unsupported AZ ID": '"use1-az3"' in eks and "precondition" in cluster and "data.aws_availability_zones.eks[0].zone_ids" in cluster,
 "node group waits for NAT route": "aws_nat_gateway.platform" in node_deps and "aws_route_table_association.private" in node_deps
   and "aws_iam_role_policy_attachment.eks_nodes" in node_deps,
 "instance-profile cleanup scoped to EKS profiles": len(profile_stmt)==1 and profile_stmt[0]["Effect"]=="Allow"
   and profile_stmt[0]["Resource"]=="arn:aws:iam::780976819607:instance-profile/eks-*",
 "manual destroy clears lease only after verifying empty state": "Clear teardown lease after verified destroy" in provision
   and provision.index("name: Verify destroy state") < provision.index("Clear teardown lease after verified destroy"),
 "reaper re-checks lease ETag before clearing": "LEASE_ETAG" in reaper and 'echo "etag=$etag"' in reaper
   and '[ "$current" != "$LEASE_ETAG" ]' in reaper,
 "budget output not called a hard ceiling": 'output "budget_alert_limit_usd"' in outputs and "hard_ceiling" not in outputs,
 "Terraform no longer calls the budget a hard ceiling": not any(re.search(r"hard[ _-]ceiling",t,re.I) for t in tf_text.values()),
}
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed: raise SystemExit("Post-validation hardening failed: "+", ".join(failed))
