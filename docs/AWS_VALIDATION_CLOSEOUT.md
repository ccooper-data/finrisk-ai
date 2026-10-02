# AWS Validation Closeout

## Status

FinRisk-AI completed its bounded real-AWS infrastructure validation on 2026-10-02. The purpose of the window was to prove controlled infrastructure promotion, EKS infrastructure readiness, evidence capture, and deterministic teardown—not public application serving.

## Evidence chain

| Control | Evidence |
| --- | --- |
| Reviewed infrastructure plan | GitHub Actions PLAN run `36950350218`, 45 add / 0 change / 0 destroy |
| Exact-plan promotion | APPLY run `37029203828` validated the source run, downloaded the private binary plan, verified the independent SHA-256 evidence, and applied that reviewed plan |
| Teardown lease | APPLY wrote the bounded teardown lease before Terraform mutation |
| Reaper validation | Reaper run `37016087352`, attempt 2, completed successfully while the lease remained active |
| Deterministic teardown | DESTROY run `37032984694` completed successfully |
| Empty-state verification | The final `Verify destroy state` step in run `37032984694` passed |
| Repository closeout baseline | `main` at `4361a69c54280537b1c8f1351eb2b4062b0dd257` after post-validation hardening |

## Security and governance controls demonstrated

- GitHub OIDC with immutable repository/environment subject binding.
- Dedicated `portfolio-validation` environment restricted to `main`.
- Least-privilege deployer policy with explicit self-modification denial.
- Per-role EKS permissions boundary stored as code.
- S3 remote Terraform state with versioning, encryption, public-access blocking, and DynamoDB locking.
- Exact reviewed-plan promotion rather than re-planning during APPLY.
- Independent checksum evidence for the private plan.
- Private-only EKS API during the bounded validation contract.
- AWS Budget alerts plus a persisted teardown lease and scheduled reaper.
- Manual DESTROY remains the primary closeout action; the reaper is the fail-safe backstop.

## What was intentionally not claimed

This validation does not claim that the private-only EKS window served the inference application publicly. The success criterion was infrastructure readiness and lifecycle governance. Application deployment requires a separately reviewed connectivity/access design.

## Portfolio claim

A defensible summary is:

> Designed, secured, and validated a production-shaped AWS ML platform lifecycle using Terraform, EKS, GitHub OIDC, remote state/locking, least-privilege IAM and permissions boundaries, exact-plan promotion, cost controls, automated teardown, and auditable CI evidence.

## Closeout rule

The bounded runtime environment is considered closed only when DESTROY succeeds and Terraform state verification is empty. Run `37032984694` satisfied both conditions.
