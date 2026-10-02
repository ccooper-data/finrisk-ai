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

APPLY writes a six-hour teardown lease to the private Terraform state bucket before creating runtime infrastructure. `reap-bounded-aws.yml` checks the lease hourly using a separate concurrency group and destroys expired non-empty Terraform state. State or lease read failures fail the reaper rather than being ignored.
