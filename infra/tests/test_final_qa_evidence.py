#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
matrix = (ROOT / "docs" / "aws-platform-acceptance-matrix.md").read_text()
demo = (ROOT / "docs" / "aws-platform-demo.md").read_text()
runbook = (ROOT / "docs" / "deployment-recovery-runbook.md").read_text()

checks = {
    "acceptance vocabulary exists": "IMPLEMENTED / LIVE VALIDATION PENDING" in matrix,
    "live EKS remains pending": "| Live EKS scheduling |" in matrix
        and "LIVE VALIDATION PENDING" in matrix,
    "live HPA remains pending": "| Live HPA scale-out |" in matrix
        and "LIVE VALIDATION PENDING" in matrix,
    "live rollback remains pending": "| Live failed-deploy rollback |" in matrix
        and "LIVE VALIDATION PENDING" in matrix,
    "live teardown remains pending": "| Live teardown/cost evidence |" in matrix
        and "LIVE VALIDATION PENDING" in matrix,
    "production claim bounded": "must not be described as a fully production-validated AWS deployment" in matrix,
    "demo preserves evidence language": "implemented and CI-validated" in demo
        and "Do not say those behaviors were live-tested in AWS" in demo,
    "runbook requires teardown": "successful teardown is part of the portfolio evidence" in runbook,
    "manager/director narrative exists": "manager/director narrative" in demo,
    "cost constraint appears in demo": "$100" in demo,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Final QA evidence acceptance failed: " + ", ".join(failed))
