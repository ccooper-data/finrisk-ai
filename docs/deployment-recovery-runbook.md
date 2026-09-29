# Deployment and Recovery Runbook

## Purpose
This runbook governs the bounded FinRisk-AI EKS validation deployment. It proves controlled promotion and recovery without leaving a permanent portfolio environment running.

## Preconditions
- Phase 1–6 acceptance gates are green on the commit being promoted.
- AWS Budget hard ceiling remains $100 and current spend leaves adequate headroom.
- EKS and required NAT/observability resources are enabled only for the validation window.
- The candidate image exists in ECR under an immutable sha-<40 hex> tag.
- GitHub environment portfolio-validation has the required deployment variables.
- An operator-approved cluster name is supplied to the workflow.

## Promotion sequence
1. Validate immutable image tag format.
2. Exchange GitHub OIDC identity for short-lived AWS credentials.
3. Resolve the tag to an immutable ECR digest.
4. Configure access to the explicitly named EKS cluster.
5. Capture the currently deployed image as the rollback target.
6. Deploy the candidate digest.
7. Wait for Kubernetes rollout completion.
8. Verify ready replicas satisfy desired replicas.
9. Record deployment evidence.

## Failure sequence
If rollout or readiness fails:
1. Restore the exact image captured before mutation.
2. Wait for rollback rollout completion.
3. Leave the workflow failed even when recovery succeeds.
4. Preserve available evidence for root-cause analysis.
5. Do not retry deployment until the failure is understood.

If rollback itself cannot reach a healthy rollout, treat the environment as an incident and perform human recovery; do not claim automated recovery succeeded.

## Scaling validation
The Phase-4 HPA contract is 1–3 inference replicas with a 70% CPU target. Live validation should demonstrate scale-out and subsequent stabilization only during the bounded EKS window. Worker capacity remains separately capped by Terraform.

## Teardown
After evidence collection:
1. Export required deployment/telemetry evidence.
2. Disable or destroy EKS, NAT, CloudWatch, and CloudTrail validation resources.
3. Confirm Terraform plan no longer proposes retained billable runtime resources that were intended to be ephemeral.
4. Record teardown time and cost snapshot.

A successful deployment is not the final acceptance condition; successful teardown is part of the portfolio evidence.
