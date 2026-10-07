#!/usr/bin/env python3
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
workflow = (ROOT / ".github" / "workflows" / "provision-bounded-aws.yml").read_text()
versions = (ROOT / "infra" / "terraform" / "versions.tf").read_text()
variables = (ROOT / "infra" / "terraform" / "variables.tf").read_text()
steps = {s["name"]: s for s in yaml.safe_load(workflow)["jobs"]["execute"]["steps"] if "name" in s}
names = list(steps)
orphans = steps.get("Verify no orphaned AWS resources", {})
upload = steps.get("Upload teardown evidence", {})
cluster = "-".join(re.search(rf'variable "{v}" \{{[^}}]*default\s*=\s*"([^"]+)"', variables)[1] for v in ("project_name", "environment"))


def orphan_check(**fake):
    """Runs the orphan step against a fake aws; returns exit code, output, evidence and the calls."""
    work = Path(tempfile.mkdtemp(prefix="finrisk-orphans-"))
    try:
        (work / "bin").mkdir()
        aws = work / "bin/aws"
        # Answers by query; FAKE_FAIL names a call that errors, as an API or permission failure would.
        aws.write_text('#!/usr/bin/env bash\necho "$*" >> "$CALLS"\n'
                       'case "$*" in *"$FAKE_FAIL"*) [ -n "$FAKE_FAIL" ] && { echo "An error occurred (UnauthorizedOperation)" >&2; exit 254; };; esac\n'
                       'case "$*" in *describe-vpcs*) echo "$FAKE_VPCS";; *describe-network-interfaces*) echo "$FAKE_ENIS";;\n'
                       '  *kubernetes.io/cluster/*) echo "$FAKE_OWNED";; *eks:cluster-name*) echo "$FAKE_NODES";; *) exit 99;; esac\n')
        aws.chmod(aws.stat().st_mode | stat.S_IEXEC)
        (work / "step.sh").write_text(orphans.get("run", "exit 99"))
        env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
        env.update(PATH=f"{work / 'bin'}{os.pathsep}{os.environ['PATH']}", CALLS=str(work / "calls"),
                   GITHUB_STEP_SUMMARY=str(work / "summary"), **orphans.get("env", {}),
                   **{f"FAKE_{k.upper()}": v for k, v in {"vpcs": "", "enis": "", "owned": "", "nodes": "", "fail": "", **fake}.items()})
        result = subprocess.run(["bash", "-e", "step.sh"], cwd=work, env=env, capture_output=True, text=True, timeout=60)
        read = lambda name: (work / name).read_text() if (work / name).exists() else ""
        return result.returncode, result.stdout + result.stderr, read("teardown-evidence.txt"), read("calls").splitlines()
    finally:
        shutil.rmtree(work, ignore_errors=True)


clean = orphan_check()
leftover = {"VPC": orphan_check(vpcs="vpc-0123"), "VPC with network interfaces": orphan_check(vpcs="vpc-0123\tvpc-0456", enis="eni-0a eni-0b"),
            "cluster-owned volume": orphan_check(owned="vol-0aaa"), "node volume": orphan_check(nodes="vol-0bbb\tvol-0aaa")}
# Each query failing, as an API or permission error would; the interface query runs only for a remaining VPC.
broken = {call: orphan_check(fail=call, vpcs="vpc-0123" if call == "describe-network-interfaces" else "")
          for call in ("describe-vpcs", "describe-network-interfaces", "kubernetes.io/cluster/", "eks:cluster-name")}

checks = {
    "manual dispatch only": "workflow_dispatch:" in workflow,
    "default is plan": 'default: "plan"' in workflow,
    "explicit lifecycle actions": all(x in workflow for x in ["- plan", "- apply-reviewed-plan", "- destroy"]),
    "OIDC permission": "id-token: write" in workflow,
    "remote S3 backend required": 'backend "s3" {}' in versions,
    "backend bucket configured": "TF_STATE_BUCKET" in workflow,
    "DynamoDB locking configured": "dynamodb_table=" in workflow and "TF_LOCK_TABLE" in workflow,
    "budget email is not workflow input": "budget_alert_email:" not in workflow.split("permissions:")[0],
    "budget email comes from secret": "secrets.BUDGET_ALERT_EMAIL" in workflow,
    "budget email Terraform variable sensitive": "sensitive   = true" in variables,
    "plan creates binary plan": "plan -out=bounded-validation.tfplan" in workflow,
    "no JSON plan published": "show -json" not in workflow,
    "binary plan stored privately": 'aws s3 cp "$TF_DIR/bounded-validation.tfplan"' in workflow
        and "/plans/${GITHUB_RUN_ID}/bounded-validation.tfplan" in workflow,
    "public artifact excludes binary plan": "bounded-aws-plan-evidence" in workflow,
    "apply requires plan run ID": "plan_run_id" in workflow,
    "apply validates workflow branch conclusion and SHA": all(term in workflow for term in [
        ".github/workflows/provision-bounded-aws.yml", "head_branch", "conclusion", "head_sha", "CURRENT_SHA"
    ]),
    "apply retrieves private plan": "/plans/${{ inputs.plan_run_id }}/bounded-validation.tfplan" in workflow,
    "checksum comes from PLAN GitHub artifact": "Download authoritative PLAN checksum artifact" in workflow
        and "reviewed-plan-evidence/bounded-validation.tfplan.sha256" in workflow,
    "plan checksum verified": "sha256sum -c bounded-validation.tfplan.sha256" in workflow,
    "latest source-run attempt checked": ".run_attempt" in workflow and "/attempts/${attempt}/jobs" in workflow,
    "apply exact binary only": "apply -lock-timeout=10m -auto-approve bounded-validation.tfplan" in workflow,
    "destroy action exists": "inputs.action == 'destroy'" in workflow and "destroy -auto-approve" in workflow,
    "destroy verifies empty state": "state list" in workflow,
    "region pinned": "AWS_REGION: us-east-1" in workflow and "aws_region:" not in workflow.split("permissions:")[0],
    "serialized lifecycle": "cancel-in-progress: false" in workflow,
    # Post-DESTROY: nothing outside Terraform state outlives the window (the lease is kept if it fails).
    "orphan check runs on destroy after the empty state check, before the lease is cleared":
        orphans.get("if") == "inputs.action == 'destroy'" and 0 < names.index("Verify destroy state")
        < names.index("Verify no orphaned AWS resources") < names.index("Clear teardown lease after verified destroy"),
    "orphan check only reads EC2, filtered to this project and cluster": orphans.get("env") == {"CLUSTER": cluster}
        and re.findall(r"\baws (\S+ \S+)", orphans.get("run", "")) == ["ec2 describe-vpcs", "ec2 describe-network-interfaces",
                                                                     "ec2 describe-volumes", "ec2 describe-volumes"]
        and all("--filters" in line for line in orphans["run"].splitlines() if "aws ec2" in line),
    "orphan check: clean account passes, with zero counts in the evidence": clean[0] == 0 and clean[2] == (
        "vpc_tagged_remaining=0\nvpc_enis_remaining=0\navailable_ebs_volumes=none\n"
        "load_balancers=not listed (no elasticloadbalancing:Describe*); none possible with vpc_tagged_remaining=0 "
        "and the bootstrap's live LoadBalancer denial\n"),
    "orphan check queries carry the tag, status and cluster filters": [c.split("--query")[0].strip() for c in clean[3]] == [
        "ec2 describe-vpcs --filters Name=tag:Project,Values=FinRisk-AI Name=tag:Environment,Values=portfolio",
        f"ec2 describe-volumes --filters Name=status,Values=available Name=tag-key,Values=kubernetes.io/cluster/{cluster}",
        f"ec2 describe-volumes --filters Name=status,Values=available Name=tag:eks:cluster-name,Values={cluster}"],
    # An interface in the VPC's subnets blocks deleting them, so interfaces are looked up only in a remaining
    # tagged VPC: never account-wide, where other clusters' interfaces would be published.
    "orphan check lists network interfaces only inside the remaining tagged VPCs":
        [c.split("--query")[0].strip() for c in leftover["VPC with network interfaces"][3] if "network-interfaces" in c]
        == ["ec2 describe-network-interfaces --filters Name=vpc-id,Values=vpc-0123,vpc-0456"]
        and "vpc_tagged_remaining=2\nvpc_enis_remaining=2\n" in leftover["VPC with network interfaces"][2],
    **{f"orphan check fails on a remaining {kind}, and records it": code == 1 and "remain after DESTROY" in out
       and evidence != clean[2] for kind, (code, out, evidence, _) in leftover.items()},
    "orphan check lists each volume once": "available_ebs_volumes=vol-0aaa,vol-0bbb\n" in leftover["node volume"][2],
    **{f"orphan check stops without reporting zero when its {call} query fails": code != 0
       and not re.search(r"=0$|=none$", evidence, re.M) and any(call in c for c in calls)
       for call, (code, _, evidence, calls) in broken.items()},
    "teardown evidence uploaded on every destroy outcome": upload.get("if") == "always() && inputs.action == 'destroy'"
        and upload.get("with", {}).get("path") == "teardown-evidence.txt" and names[-1] == "Upload teardown evidence",
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Provision workflow acceptance failed: " + ", ".join(failed))
