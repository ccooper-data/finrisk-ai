#!/usr/bin/env python3
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
matrix = (ROOT / "docs" / "aws-platform-acceptance-matrix.md").read_text()
demo = (ROOT / "docs" / "aws-platform-demo.md").read_text()
runbook = (ROOT / "docs" / "deployment-recovery-runbook.md").read_text()
closeout = (ROOT / "docs" / "AWS_VALIDATION_CLOSEOUT.md").read_text()
v2_closeout = (ROOT / "docs" / "AWS_V2_VALIDATION_CLOSEOUT.md").read_text()
presentation = (ROOT / "docs" / "PORTFOLIO_PRESENTATION.md").read_text()
rows = {line.split("|")[1].strip(): line for line in matrix.splitlines() if line.startswith("| ")}
PENDING, LIVE = "| IMPLEMENTED / LIVE VALIDATION PENDING |", "| LIVE VALIDATED |"
V1_RECORD, V2_RECORD = "docs/AWS_VALIDATION_CLOSEOUT.md", "docs/AWS_V2_VALIDATION_CLOSEOUT.md"
V2_LIVE_ROWS = (
    "V2 cluster add-ons (Argo CD, lean Prometheus, exposure guard)",
    "V2 GitOps digest-only deploy",
    "V2 Prometheus evidence of the deployed model",
    "V2 HPA scale-out under a bounded load",
    "V2 gate window evidence chain",
)


def status(row, value):
    return rows.get(row, "").rstrip().endswith(value)


def live_with_evidence(row, record=V1_RECORD):
    return status(row, LIVE) and record in rows[row]


checks = {
    "acceptance vocabulary exists": "IMPLEMENTED / LIVE VALIDATION PENDING" in matrix and "**LIVE VALIDATED**" in matrix,
    # Live rows are claimed only with the closeout record that holds their evidence.
    "live EKS scheduling validated with evidence": live_with_evidence("Live EKS scheduling"),
    "live private deployment validated with evidence": live_with_evidence("Live private deployment of the pinned model"),
    "closeout records the live chain": all(term in closeout for term in (
        "smoke=passed model_sha256=", "result=deployed", "Destroy complete! Resources: 60 destroyed.")),
    "live HPA scale-out is validated with its V2 record": live_with_evidence("Live HPA scale-out", V2_RECORD),
    "live telemetry remains pending": status("Live CloudWatch telemetry", PENDING),
    "live rollback remains pending": rows.get("Live failed-deploy rollback", "").rstrip()
        .endswith("| IMPLEMENTED / LIVE VALIDATION PENDING |"),
    "live rollback is not claimed from a bounded window": "not exercisable in a bounded window"
        in rows.get("Live failed-deploy rollback", ""),
    "live teardown validated with evidence": live_with_evidence("Live teardown/cost evidence"),
    # The cost figures are filled in from Cost Explorer before merge.
    "closeout cost recorded": not re.search(r"COST_\w*PENDING", closeout + v2_closeout + presentation),
    "production claim bounded": "must not be described as a fully production-validated AWS deployment" in matrix,
    "demo preserves evidence language": "implemented and CI-validated" in demo
        and "Do not say rollback or telemetry was live-tested in AWS" in demo,
    "runbook requires teardown": "successful teardown is part of the portfolio evidence" in runbook,
    # Deploy runs as the release role. A non-first failure returns to the digest recorded before the
    # patch (never rollout undo, which Argo CD's self-heal reverts); a failed first deploy is retained for
    # diagnosis, never described as a rollback.
    "runbook names the release environment": "portfolio-release" in runbook
        and "portfolio-validation" not in runbook,
    "recovery is a re-patch of the recorded digest, never rollout undo": "re-patches that digest" in runbook
        and "never runs `kubectl rollout undo`" in runbook and "--to-revision" not in runbook + demo
        and not any(stale in doc.lower() for doc in (runbook, demo)
                    for stale in ("previous image", "deployed image", "image captured")),
    "a failed first deploy is retained, not called a rollback or recovery": "result=first_deploy_retained" in runbook
        and "This is not a rollback; do not describe it as one or as a recovery." in runbook
        and "left in place for diagnosis" in demo and "delete a failed first deploy" not in demo,
    # V2 ran in the 2026-10-16 window. Its rows are live with the V2 record, except failed-deploy
    # handling, which no failure path exercised live.
    "V2 rows are live with the V2 record; failed-deploy handling stays pending": all(
        live_with_evidence(row, V2_RECORD) for row in V2_LIVE_ROWS) and status("V2 failed-deploy handling", PENDING)
        and {*V2_LIVE_ROWS, "V2 failed-deploy handling"} <= set(rows),
    "V2 record holds the gate window's evidence": all(term in v2_closeout for term in (
        "result=deployed", "smoke=passed model_sha256=", "Destroy complete! Resources: 60 destroyed.",
        "7d0f526fa13408f38c6e9cf93d3305478148ef55", "served traffic")),
    "a failed load test is documented as a failed gate, never a rollback or recovery": all(
        f"`result={r}`" in runbook for r in ("load_not_started", "hpa_not_scaled", "hpa_evidence_failed", "load_cleanup_failed"))
        and "none of these is a rollback or a recovery" in runbook,
    "manager/director narrative exists": "manager/director narrative" in demo,
    "cost constraint appears in demo": "$100" in demo,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Final QA evidence acceptance failed: " + ", ".join(failed))
