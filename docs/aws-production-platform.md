# AWS Production Platform — Phase 1 Architecture & Cost Guardrails

## Objective
Extend FinRisk-AI into a production-shaped AWS ML platform while preserving the existing modeling, evidence, CI, and governance system.

## Non-negotiable cost policy
- Hard cumulative project ceiling: **$100 USD**.
- Engineering target: **$25–$50 USD total** for portfolio validation.
- No billable production-shaped resource may be provisioned without a documented purpose, expected cost driver, and teardown path.
- EKS, NAT Gateway, ALB, and worker compute are ephemeral validation resources; they must not be intentionally left running after evidence collection.
- Cost is a release gate: if projected cumulative spend threatens the $100 ceiling, deployment stops and architecture is revised.
- AWS Budget alert thresholds: **$10, $25, $50, $75, $90, $100**.
- All supported resources must be tagged at minimum with Project=FinRisk-AI, Environment, ManagedBy=Terraform, and CostCenter=Portfolio.

## Target architecture
GitHub Actions (OIDC) -> ECR -> ALB -> EKS -> FinRisk inference API

Supporting services:
- Terraform for infrastructure-as-code
- VPC spanning two Availability Zones
- Public subnets only for internet-facing ingress/NAT components where required
- Private subnets for EKS workloads
- S3 for governed model/data artifacts
- IAM least privilege and workload identity
- KMS for encryption controls
- Secrets Manager only where a runtime secret is actually required
- CloudWatch + OpenTelemetry for logs, metrics, traces, alarms, and deployment evidence
- Kubernetes HPA for autoscaling
- Health/readiness probes and deployment rollback
- VPC endpoints where they reduce NAT dependency/cost without adding unjustified fixed cost

## Architecture decisions
1. **EKS rather than ECS**: selected deliberately because Kubernetes/EKS is a primary portfolio evidence gap.
2. **Terraform-owned infrastructure**: the deployed environment must be reproducible and destructible from code.
3. **Ephemeral production-shaped environment**: portfolio evidence does not require 24/7 uptime.
4. **Private application workloads**: ingress is separated from workload placement.
5. **OIDC over long-lived AWS keys**: CI/CD should use short-lived federated credentials.
6. **Observability is part of the platform**: telemetry, SLO evidence, and rollback validation are not post-project additions.
7. **Cost governance is an engineering control**: budget checks and teardown evidence are part of acceptance.

## Eight-phase roadmap
1. Architecture & cost guardrails — 8%
2. AWS network foundation — 14% (22% cumulative)
3. Containerized model serving — 14% (36%)
4. Kubernetes / EKS — 18% (54%)
5. Cloud security — 12% (66%)
6. Observability & reliability — 13% (79%)
7. CI/CD, scaling & recovery — 14% (93%)
8. QA & portfolio demonstration — 7% (100%)

## Phase 1 acceptance gate
Phase 1 is complete only when:
- [x] Current repository baseline inspected.
- [x] No existing Terraform/VPC/EKS/ECR foundation found that would be duplicated.
- [x] Target AWS architecture documented.
- [x] $100 hard ceiling and $25–$50 engineering target documented.
- [x] Billable-resource teardown policy documented.
- [x] Budget alert thresholds defined.
- [x] Eight-phase completion model documented.
- [ ] Terraform cost-guardrail foundation is reviewed in PR before any billable infrastructure is applied.

## Phase 2 entry condition
Do not run Terraform apply for the network/platform stack until cost guardrails are represented in code and reviewed. Phase 2 begins with Terraform module structure, provider/version pinning, VPC CIDR/subnet design, and automated static validation.
