#!/usr/bin/env python3
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
matrix = (ROOT / "docs" / "aws-platform-acceptance-matrix.md").read_text()
demo = (ROOT / "docs" / "aws-platform-demo.md").read_text()
runbook = (ROOT / "docs" / "deployment-recovery-runbook.md").read_text()
closeout = (ROOT / "docs" / "AWS_VALIDATION_CLOSEOUT.md").read_text()
presentation = (ROOT / "docs" / "PORTFOLIO_PRESENTATION.md").read_text()
rows = {line.split("|")[1].strip(): line for line in matrix.splitlines() if line.startswith("| ")}
PENDING, LIVE = "| IMPLEMENTED / LIVE VALIDATION PENDING |", "| LIVE VALIDATED |"


def status(row, value):
    return rows.get(row, "").rstrip().endswith(value)


def live_with_evidence(row):
    return status(row, LIVE) and "docs/AWS_VALIDATION_CLOSEOUT.md" in rows[row]


checks = {
    "acceptance vocabulary exists": "IMPLEMENTED / LIVE VALIDATION PENDING" in matrix and "**LIVE VALIDATED**" in matrix,
    # Live rows are claimed only with the closeout record that holds their evidence.
    "live EKS scheduling validated with evidence": live_with_evidence("Live EKS scheduling"),
    "live private deployment validated with evidence": live_with_evidence("Live private deployment of the pinned model"),
    "closeout records the live chain": all(term in closeout for term in (
        "smoke=passed model_sha256=", "result=deployed", "Destroy complete! Resources: 60 destroyed.")),
    "live HPA remains pending": status("Live HPA scale-out", PENDING),
    "live telemetry remains pending": status("Live CloudWatch telemetry", PENDING),
    "live rollback remains pending": rows.get("Live failed-deploy rollback", "").rstrip()
        .endswith("| IMPLEMENTED / LIVE VALIDATION PENDING |"),
    "live rollback is not claimed from a bounded window": "not exercisable in a bounded window"
        in rows.get("Live failed-deploy rollback", ""),
    "live teardown validated with evidence": live_with_evidence("Live teardown/cost evidence"),
    # The cost figures are filled in from Cost Explorer before merge.
    "closeout cost recorded": not re.search(r"COST_\w*PENDING", closeout + presentation),
    "production claim bounded": "must not be described as a fully production-validated AWS deployment" in matrix,
    "demo preserves evidence language": "implemented and CI-validated" in demo
        and "Do not say those behaviors were live-tested in AWS" in demo,
    "runbook requires teardown": "successful teardown is part of the portfolio evidence" in runbook,
    # Deploy runs as the release role and recovers to a recorded revision, not a captured image.
    "runbook names the release environment": "portfolio-release" in runbook
        and "portfolio-validation" not in runbook,
    "recovery is to the recorded revision": "--to-revision" in runbook
        and not any(stale in doc.lower() for doc in (runbook, demo)
                    for stale in ("previous image", "deployed image", "image captured")),
    "manager/director narrative exists": "manager/director narrative" in demo,
    "cost constraint appears in demo": "$100" in demo,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Final QA evidence acceptance failed: " + ", ".join(failed))
