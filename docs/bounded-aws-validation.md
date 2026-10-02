# Bounded AWS EKS Validation Contract

The bounded AWS validation window proves infrastructure provisioning and teardown, not application deployment.

## Success criteria

- Terraform applies the exact reviewed binary plan.
- The EKS control plane reaches `ACTIVE`.
- The managed node group reaches `ACTIVE`.
- The EKS API remains private-only for this validation window.
- Evidence is captured, then the environment is destroyed no later than the persisted teardown lease.

## Out of scope

`.github/workflows/deploy-inference.yml` is not authorized against the private-only bounded validation cluster. Application deployment requires a separately reviewed connectivity and access design.

## Cost enforcement

APPLY writes a six-hour teardown lease to the private Terraform state bucket before creating runtime infrastructure. `reap-bounded-aws.yml` runs hourly in a separate concurrency group:

- Empty state: nothing to do. An expired lease is cleared; an active lease is left alone because an APPLY may be starting.
- Non-empty state with an expired lease: destroy.
- Non-empty state with no lease: destroy (fail-safe).
- A missing lease (404) is a normal idle condition. Any other state or lease read error fails the reaper rather than being ignored.

## Permissions boundary

`docs/aws-eks-boundary-policy.json` is the content of the out-of-band IAM policy `finrisk-ai-eks-boundary`. After changing the file, update that policy in AWS so its default version matches the file exactly.
