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
| Live validation commit | `d0096e9536b3b77597fc820ac391abccb0951c09` — the commit exercised by PLAN/APPLY/reaper/DESTROY |\n| Post-validation hardening | `4361a69c54280537b1c8f1351eb2b4062b0dd257` — CI/static-validated only; not exercised in the live window |

## Security and governance controls demonstrated

- GitHub OIDC with immutable repository/environment subject binding.
- Dedicated `portfolio-validation` environment restricted to `main`.
- Scoped deployer policy with explicit self-modification denial.
- Per-role EKS permissions boundary stored as code.
- S3 remote Terraform state with versioning, encryption, public-access blocking, and DynamoDB locking.
- Exact reviewed-plan promotion rather than re-planning during APPLY.
- Independent checksum evidence for the private plan.
- Private-only EKS API during the bounded validation contract.
- AWS Budget alerts plus a persisted teardown lease and scheduled reaper.
- Manual DESTROY remains the primary closeout action; the reaper is the fail-safe backstop.

## Validation window facts

- APPLY started at approximately **15:45 UTC** and verified DESTROY completed at approximately **16:30 UTC**, for a total bounded window of about **45 minutes**.
- EKS cluster creation took approximately **13m 11s**.
- Managed node-group creation took approximately **1m 57s**.
- DESTROY took approximately **12 minutes** through final state verification.
- Estimated AWS runtime cost for the validation window was **under $0.25**.

## Known limitations

- Network mutation permissions are constrained to `us-east-1`, but are region-scoped rather than resource-tag-scoped.
- IAM `CreateRole` cannot itself constrain the contents of a new role's trust policy. Risk is mitigated by the required EKS permissions boundary, generated-role naming constraints, and separate cluster/node managed-policy attachment allow-lists.
- The scheduled reaper depends on GitHub's best-effort cron execution. During validation, an approximately **7-hour scheduling gap** was observed. Manual DESTROY therefore remains the primary teardown control; the reaper is a backstop rather than a real-time scheduler.

## What was intentionally not claimed

This validation does not claim that the private-only EKS window served the inference application publicly. The success criterion was infrastructure readiness and lifecycle governance. Application deployment requires a separately reviewed connectivity/access design.

## Portfolio claim

A defensible summary is:

> Designed, secured, and validated a production-shaped AWS ML platform lifecycle using Terraform, EKS, GitHub OIDC, remote state/locking, scoped IAM and permissions boundaries, exact-plan promotion, cost controls, automated teardown, and auditable CI evidence.

## Closeout rule

The bounded runtime environment is considered closed only when DESTROY succeeds and Terraform state verification is empty. Run `37032984694` satisfied both conditions.
