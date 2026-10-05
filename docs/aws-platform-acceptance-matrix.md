# AWS Platform Final Acceptance Matrix

Status vocabulary:
- **VALIDATED** — exercised by repository CI/static acceptance with passing evidence.
- **LIVE VALIDATED** — exercised in a bounded real-AWS window, with the evidence recorded in `docs/AWS_VALIDATION_CLOSEOUT.md`.
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
| Rollback control flow | deploy buildspec run against a fake kubectl + acceptance | VALIDATED |
| Live EKS scheduling | 2026-10-03 window (`docs/AWS_VALIDATION_CLOSEOUT.md`): pod Ready on the managed node group | LIVE VALIDATED |
| Live private deployment of the pinned model | 2026-10-03 window (`docs/AWS_VALIDATION_CLOSEOUT.md`): digest-pinned image deployed through in-VPC CodeBuild; in-pod smoke test verified the model SHA-256 and a live prediction through the in-cluster Service | LIVE VALIDATED |
| Live HPA scale-out | bounded load test required; the window recorded only that the metrics-server add-on was Active | IMPLEMENTED / LIVE VALIDATION PENDING |
| Live CloudWatch telemetry | not implemented end to end: instrumentation and alarm definitions exist, but there is no OpenTelemetry exporter or log shipping (V1.1), so the alarms had no data source in the window | IMPLEMENTED / LIVE VALIDATION PENDING |
| Live failed-deploy rollback | not exercisable in a bounded window: the controlled deploy cannot ship a non-ready candidate; needs a reviewed failure-injection mechanism | IMPLEMENTED / LIVE VALIDATION PENDING |
| Live teardown/cost evidence | 2026-10-02 and 2026-10-03 windows (`docs/AWS_VALIDATION_CLOSEOUT.md`): DESTROY with empty state verified; cost snapshot recorded | LIVE VALIDATED |

## Final acceptance rule
The repository may be described as a **production-shaped AWS platform implementation** after static/CI acceptance. It must not be described as a fully production-validated AWS deployment until the bounded live-validation items above are executed and their evidence is retained.

The project reaches portfolio-complete status only after either:
1. the bounded live validation is executed successfully under the $100 ceiling and teardown is verified, or
2. portfolio materials explicitly preserve the live-validation-pending limitation rather than implying those tests occurred.

The 2026-10-03 window met condition 1 for deployment and serving: the pinned model was deployed to private EKS and served a live prediction, and teardown was verified. HPA scale-out, CloudWatch telemetry and live failed-deploy rollback remain pending, so portfolio materials keep those limitations (condition 2 for those rows).

Live failed-deploy rollback is outside the bounded window (`docs/live-aws-validation-plan.md`, step 4), so it stays pending after a successful window and portfolio materials keep that limitation either way.
