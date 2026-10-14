# AWS Platform Interview Demonstration

## 10-minute manager/director narrative

### 1. Business and engineering problem — 60 seconds
FinRisk-AI already demonstrated temporal financial-risk ML and model governance. The cloud extension addresses the final-mile problem: deploying a governed model with explicit controls for cost, identity, networking, reliability, observability, and recovery.

### 2. Cost and architecture — 90 seconds
Show the $100 Terraform budget ceiling, cost-gated NAT/EKS/observability/audit resources, and two-AZ VPC/private workload placement. Explain that the environment is intentionally ephemeral because portfolio evidence does not justify permanent infrastructure cost.

### 3. Secure supply chain — 90 seconds
Show non-root container validation, immutable ECR policy, GitHub OIDC trust bound to repository/ref, and digest-pinned deployment. Explain why short-lived identity and content-addressed deployment reduce credential and provenance risk.

### 4. Kubernetes operating model — 90 seconds
Show the hardened Deployment, readiness/liveness probes, resource requests/limits, HPA, and private-by-default EKS API. Explain separation between ingress, application workload, and control-plane access.

### 5. Observability and SLOs — 90 seconds
Show OpenTelemetry counters/traces/latency, CloudWatch alarm definitions, and the runtime SLO document. State clearly that 99.9% is an objective for a validation window, not a historical uptime claim.

### 6. Failure and recovery — 120 seconds
Show: candidate digest -> authorization preflight -> record the Argo CD Application's current digest -> patch only the image digest -> wait until Argo CD has compared, synced and reports Healthy exactly that digest at the planned commit -> in-pod smoke test against the pinned model -> PromQL evidence -> on failure, re-patch the recorded digest and verify it -> preserve failed status. A failed first deploy has no earlier digest: it is left in place for diagnosis until teardown.

Leadership point: recovery success does not convert a failed change into a successful change; the failed deployment remains visible for investigation.

### 7. Governance and leadership close — 60 seconds
Explain the operating model:
- cost is a release constraint;
- identity is short-lived and scoped;
- artifacts and deployments are evidence-bound;
- failure paths are designed before production;
- teardown is part of acceptance;
- claims are limited to what evidence actually demonstrates.

## Technical deep-dive prompts
- **Why EKS instead of ECS?** Kubernetes/EKS was an explicit evidence gap, so the platform deliberately demonstrates that operating model.
- **Why is NAT opt-in?** It avoids unnecessary fixed portfolio spend while preserving a bounded integration path.
- **Why deploy by digest?** A tag communicates intent; the digest identifies the exact container content.
- **Why private workloads?** To reduce unnecessary network exposure and separate ingress from application placement.
- **Why readiness and liveness?** Liveness answers whether the process is alive; readiness answers whether the service can safely receive traffic with its governed model loaded.
- **Why keep a failed workflow failed after rollback?** Recovery restores service state; it does not erase evidence that the candidate deployment failed.

## Evidence-language guardrail
The 2026-10-03 window live-validated deployment and serving (see `docs/AWS_VALIDATION_CLOSEOUT.md`). You may say the inference service was deployed by digest to a private EKS cluster, became ready, served the pinned model with its SHA-256 verified in the pod, returned a live prediction, and was torn down with empty state verified.

For autoscaling (HPA scale-out) and rollback, say **implemented and CI-validated**. For CloudWatch runtime telemetry, say the instrumentation and alarm definitions are CI-validated but nothing exports to CloudWatch yet. Do not say those behaviors were live-tested in AWS.
