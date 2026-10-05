# FinRisk-AI Portfolio Presentation Guide

## 60-second executive narrative

FinRisk-AI is a point-in-time corporate financial-distress platform built to answer two questions: can the model identify elevated 12-month distress risk without look-ahead leakage, and can the resulting system be operated with evidence strong enough for a regulated or high-governance environment? I built the data and modeling pipeline around SEC filing-date knowledge boundaries, evaluated multiple model families chronologically, and then production-shaped the platform on AWS. The cloud lifecycle uses Terraform, EKS, GitHub OIDC, remote state and locking, scoped IAM, permissions boundaries, exact reviewed-plan promotion, budget controls, and fail-safe teardown. The first live window exercised commit `d0096e9536b3b77597fc820ac391abccb0951c09` through real AWS APPLY and deterministic DESTROY with empty-state verification. The second (2026-10-03, commit `b83a3656d9c7e25c5d61f1e4accfac519585197d`) deployed the pinned model's production image through in-VPC CodeBuild to the private EKS cluster, verified the model SHA-256 and a live prediction in the pod, and destroyed all 60 resources with empty state verified.

## 5-minute demonstration

1. **Business problem (30 sec)** — Explain 12-month corporate distress risk and why point-in-time evidence matters.
2. **Data/evidence (60 sec)** — Show the SEC cohort, filing-date cutoff, maturity gate, source hashes, and chronological evaluation.
3. **Modeling (60 sec)** — Show the logistic baseline, boosted tree, and PyTorch GRU; state the promoted GRU result and explain why the project does not claim an unsupported architecture winner.
4. **Cloud/security (90 sec)** — Walk through Terraform, private EKS, GitHub OIDC, remote state/locking, permissions boundaries, exact-plan promotion, and evidence checks.
5. **Operations (45 sec)** — Show the teardown lease/reaper design and the successful APPLY/DESTROY evidence chain.
6. **Leadership close (15 sec)** — Emphasize decision rights, controlled autonomy, cost containment, and evidence-based promotion.

## Manager/Director framing

Lead with the operating model rather than implementation details:

- **Decision rights:** automation can plan and provision only through constrained capabilities; reviewed evidence gates promotion.
- **Risk management:** uncertainty, stale evidence, privilege escalation, uncontrolled spend, and orphaned infrastructure are explicit failure modes.
- **Controlled autonomy:** OIDC, IAM boundaries, exact-plan promotion, and teardown automation allow speed without giving automation unrestricted authority.
- **Management visibility:** plan summaries, model evidence, CI gates, cost alerts, lifecycle artifacts, and closeout state make readiness observable.
- **Sustainability:** the system is designed so safe operation does not depend on one person remembering cleanup steps.

## Resume-ready bullets

- Architected and validated a production-shaped financial-risk ML platform spanning point-in-time SEC data engineering, temporal model validation, PyTorch/TensorFlow experimentation, Terraform, AWS EKS, and governed CI/CD.
- Implemented short-lived GitHub OIDC authentication, scoped IAM, per-role permissions boundaries, encrypted remote Terraform state with locking, and exact reviewed-plan promotion with independent SHA-256 verification; completed two bounded AWS validation windows (about 45 and 47 minutes from APPLY to verified empty state; the second day also included a failed first APPLY that the teardown contract destroyed within about 1.5 hours), at a net AWS cost of -$0.00 across both windows after account credits (Cost Explorer estimate).
- Deployed the pinned production model to a private EKS cluster through in-VPC CodeBuild runners with plan-reviewed buildspecs. The release identity cannot change the buildspec, source, image, environment or role, except to supply a digest-pinned image URI to the deploy build. A live in-pod smoke test verified the model SHA-256 and a prediction.
- Kept the limits explicit: HPA scale-out, CloudWatch runtime telemetry and live failed-deploy rollback were not live-validated in AWS.
- Designed cost and failure controls combining AWS Budget alerts, bounded deployment leases, scheduled fail-safe teardown, deterministic DESTROY, and empty-state verification.
- Built auditable model-evidence controls around SEC filing-date knowledge boundaries, complete outcome-window maturity, chronological evaluation, source hashing, and calibration reporting.
- Drove iterative independent security/operations reviews to closure, converting findings into automated CI acceptance gates rather than relying on manual review alone.

## Questions to expect

**Why EKS for a portfolio validation?**  
The goal was not to claim Kubernetes was the cheapest serving option. It demonstrated infrastructure governance, IAM separation, private networking, lifecycle controls, and operational evidence on a realistic orchestration target.

**Why private-only EKS?**  
The bounded windows validated infrastructure readiness (2026-10-02) and private serving of the pinned model through the in-cluster Service (2026-10-03), not public application serving. Keeping the API private avoided weakening the security posture merely to create a demo.

**Why destroy immediately?**  
The validation was evidence-driven and cost-bounded. Once each window's required evidence existed (the infrastructure lifecycle in the first; the deployed model's verified SHA-256 and a live prediction in the second), continued runtime added cost without adding portfolio value.

**What would change for production?**  
Separate accounts/environments, organization-level guardrails, production connectivity, durable observability/SLO ownership, a formal secrets strategy, longer-lived operational monitoring, and workload-specific scaling/capacity planning.
