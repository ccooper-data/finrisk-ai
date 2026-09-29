# AWS Platform Final Acceptance Matrix

Status vocabulary:
- **VALIDATED** — exercised by repository CI/static acceptance with passing evidence.
- **IMPLEMENTED / LIVE VALIDATION PENDING** — production-shaped code exists, but no claim is made that the AWS runtime behavior has been empirically demonstrated.
- **BLOCKED** — required evidence is absent.

| Capability | Evidence | Status |
|---|---|---|
| $100 hard ceiling | Terraform variable validation + budget resource | VALIDATED |
| Cost-aware NAT | disabled by default + network acceptance | VALIDATED |
| Two-AZ VPC/subnet separation | Terraform + network acceptance | VALIDATED |
| EKS cost gate | enable_eks=false by default; workers capped | VALIDATED |
| EKS API exposure | private by default; 0.0.0.0/0 prohibited | VALIDATED |
| Container build | container CI | VALIDATED |
| Non-root container | container CI | VALIDATED |
| Model serving contract | serving tests + model artifact feature contract | VALIDATED |
| Immutable registry policy | ECR immutable tags/lifecycle Terraform | VALIDATED |
| Kubernetes workload hardening | EKS acceptance | VALIDATED |
| HPA configuration | Kubernetes manifest + EKS acceptance | VALIDATED |
| GitHub/AWS OIDC | security Terraform + acceptance | VALIDATED |
| KMS/private artifact store | security Terraform + acceptance | VALIDATED |
| OpenTelemetry instrumentation | observability acceptance | VALIDATED |
| SLO/alert definitions | docs + Terraform + acceptance | VALIDATED |
| Digest-pinned deployment | delivery workflow + acceptance | VALIDATED |
| Rollback control flow | delivery workflow + acceptance | VALIDATED |
| Live EKS scheduling | bounded AWS run required | IMPLEMENTED / LIVE VALIDATION PENDING |
| Live HPA scale-out | bounded load test required | IMPLEMENTED / LIVE VALIDATION PENDING |
| Live CloudWatch telemetry | bounded AWS run required | IMPLEMENTED / LIVE VALIDATION PENDING |
| Live failed-deploy rollback | bounded AWS failure injection required | IMPLEMENTED / LIVE VALIDATION PENDING |
| Live teardown/cost evidence | bounded AWS run + destroy required | IMPLEMENTED / LIVE VALIDATION PENDING |

## Final acceptance rule
The repository may be described as a **production-shaped AWS platform implementation** after static/CI acceptance. It must not be described as a fully production-validated AWS deployment until the bounded live-validation items above are executed and their evidence is retained.

The project reaches portfolio-complete status only after either:
1. the bounded live validation is executed successfully under the $100 ceiling and teardown is verified, or
2. portfolio materials explicitly preserve the live-validation-pending limitation rather than implying those tests occurred.
