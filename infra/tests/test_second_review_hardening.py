#!/usr/bin/env python3
import json
from fnmatch import fnmatchcase
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
boundary=json.loads((ROOT/"docs/aws-eks-boundary-policy.json").read_text())
bootstrap=json.loads((ROOT/"docs/aws-bootstrap-policy.json").read_text())
main=(ROOT/"infra/terraform/main.tf").read_text()
provision=(ROOT/".github/workflows/provision-bounded-aws.yml").read_text()
reaper=(ROOT/".github/workflows/reap-bounded-aws.yml").read_text()
contract=(ROOT/"docs/bounded-aws-validation.md").read_text()

# The boundary must let each role use every action its attached AWS managed policy
# grants (effective permissions = boundary AND attached policy). Fixtures are the
# current default versions from the AWS Managed Policy Reference.
FIXTURES=ROOT/"infra/tests/fixtures/aws-managed-policies"
CLUSTER="arn:aws:iam::780976819607:role/finrisk-ai-eks-cluster-example"
NODES="arn:aws:iam::780976819607:role/finrisk-ai-eks-nodes-example"
attached={
 CLUSTER:["AmazonEKSClusterPolicy"],
 NODES:["AmazonEKSWorkerNodePolicy","AmazonEKS_CNI_Policy","AmazonEC2ContainerRegistryPullOnly"],
}

def as_list(v): return [v] if isinstance(v,str) else v
def matches(action,patterns): return any(fnmatchcase(action.lower(),p.lower()) for p in patterns)
def principal_ok(stmt,principal):
    pattern=stmt.get("Condition",{}).get("ArnLike",{}).get("aws:PrincipalArn")
    return pattern is None or matches(principal,as_list(pattern))
def boundary_allows(action,principal):
    hits=[s for s in boundary["Statement"] if matches(action,as_list(s["Action"])) and principal_ok(s,principal)]
    return any(s["Effect"]=="Allow" for s in hits) and not any(s["Effect"]=="Deny" for s in hits)
def managed_actions(name):
    doc=json.loads((FIXTURES/f"{name}.json").read_text())
    return {a for s in doc["Statement"] if s["Effect"]=="Allow" for a in as_list(s["Action"])}

blocked={f"{p.split('/')[-1]}:{a}" for p,names in attached.items() for n in names for a in managed_actions(n) if not boundary_allows(a,p)}
for b in sorted(blocked): print(f"BLOCKED BY BOUNDARY: {b}")
cluster_only=managed_actions("AmazonEKSClusterPolicy")-set().union(*(managed_actions(n) for n in attached[NODES]))
node_only=set().union(*(managed_actions(n) for n in attached[NODES]))-managed_actions("AmazonEKSClusterPolicy")
boundary_actions={a for s in boundary["Statement"] for a in as_list(s["Action"])}

stmts={s["Sid"]:s for s in bootstrap["Statement"]}
checks={
 "boundary covers every attached managed-policy action": len(managed_actions("AmazonEKSClusterPolicy"))>0 and not blocked,
 "boundary keeps cluster-only actions off the node role": not any(boundary_allows(a,NODES) for a in cluster_only if not a.startswith("ec2:Describe")),
 "boundary keeps node-only actions off the cluster role": not any(boundary_allows(a,CLUSTER) for a in node_only if not a.startswith("ec2:Describe")),
 "boundary has no service-wide or global wildcards": not ({"*","eks:*","iam:*","sts:*","s3:*","kms:*"} & boundary_actions),
 "boundary denies role chaining": any(s["Effect"]=="Deny" and "sts:AssumeRole" in as_list(s["Action"]) for s in boundary["Statement"]),
 "KMS alias authorized on alias and key": set(stmts["ManageFinRiskKMSAlias"]["Action"]) >= {"kms:CreateAlias","kms:DeleteAlias"}
   and set(stmts["AuthorizeFinRiskKMSAliasOnKeys"]["Action"]) == {"kms:CreateAlias","kms:DeleteAlias"}
   and stmts["AuthorizeFinRiskKMSAliasOnKeys"]["Resource"]=="arn:aws:kms:us-east-1:780976819607:key/*",
 "KMS key admin escalation removed": not ({"kms:PutKeyPolicy","kms:CreateGrant"} & set(stmts["ManageFinRiskKMS"]["Action"])),
 "budget at most five alerts": 'budget_thresholds = toset(["10", "25", "50", "75", "100"])' in main and "FORECASTED" not in main,
 "lease written before apply": provision.index("Write teardown lease before apply") < provision.index("Apply exact reviewed binary plan"),
 "reaper separate concurrency": "group: finrisk-bounded-aws-reaper" in reaper,
 "reaper scheduled": 'cron: "17 * * * *"' in reaper,
 "reaper does not swallow state errors": "terraform -chdir=\"$TF_DIR\" state list > state.txt" in reaper,
 "reaper inspects state before the lease": reaper.index("name: Inspect state") < reaper.index("name: Read teardown lease"),
 "reaper treats a missing lease as idle, not failure": "(404)" in reaper and 'echo "present=false"' in reaper,
 "reaper destroys unleased state (fail-safe)": "steps.lease.outputs.present == 'false' || steps.lease.outputs.expired == 'true'" in reaper,
 "reaper never clears an active lease": "if: steps.lease.outputs.present == 'true' && steps.lease.outputs.expired == 'true'" in reaper,
 "validation contract ACTIVE only": "control plane reaches `ACTIVE`" in contract and "node group reaches `ACTIVE`" in contract,
}
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed: raise SystemExit("Second review hardening failed: "+", ".join(failed))
