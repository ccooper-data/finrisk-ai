#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
matrix = (ROOT / "docs" / "aws-platform-acceptance-matrix.md").read_text()
demo = (ROOT / "docs" / "aws-platform-demo.md").read_text()
runbook = (ROOT / "docs" / "deployment-recovery-runbook.md").read_text()
rows = {line.split("|")[1].strip(): line for line in matrix.splitlines() if line.startswith("| ")}

checks = {
    "acceptance vocabulary exists": "IMPLEMENTED / LIVE VALIDATION PENDING" in matrix,
    "live EKS remains pending": "| Live EKS scheduling |" in matrix
        and "LIVE VALIDATION PENDING" in matrix,
    "live HPA remains pending": "| Live HPA scale-out |" in matrix
        and "LIVE VALIDATION PENDING" in matrix,
    "live rollback remains pending": rows.get("Live failed-deploy rollback", "").rstrip()
        .endswith("| IMPLEMENTED / LIVE VALIDATION PENDING |"),
    "live rollback is not claimed from a bounded window": "not exercisable in a bounded window"
        in rows.get("Live failed-deploy rollback", ""),
    "live teardown remains pending": "| Live teardown/cost evidence |" in matrix
        and "LIVE VALIDATION PENDING" in matrix,
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
