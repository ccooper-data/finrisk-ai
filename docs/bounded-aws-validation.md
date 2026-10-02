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

The primary control is a manual DESTROY as soon as the success criteria are met. The first window (2026-10-02) took about 45 minutes from APPLY to verified DESTROY.

APPLY writes a four-hour teardown lease to the private Terraform state bucket before creating runtime infrastructure. Four hours leaves room for the reaper's schedule and a 15-20 minute destroy inside a six-hour window. GitHub scheduled runs are best-effort, though: this repository has seen gaps of several hours between them, so the reaper is a backstop, not a guarantee. `reap-bounded-aws.yml` runs hourly in a separate concurrency group:

- Empty state (including no state object before the first APPLY): nothing to do. An expired lease is cleared; an active lease is left alone because an APPLY may be starting.
- Non-empty state with an expired lease: destroy.
- Non-empty state with no lease: destroy (fail-safe).
- A missing lease (404) is a normal idle condition. Any other state or lease read error fails the reaper rather than being ignored.
- Before clearing an expired lease, the reaper re-reads its ETag and leaves it alone if an APPLY replaced it in the meantime.

A manual DESTROY clears the lease once it has verified that state is empty.

## Operating limits

- Both workflows request 2-hour AWS credentials (`role-duration-seconds: 7200`). The `github-finrisk-deployer` role's maximum session duration must be at least 2 hours, or every run fails at the credentials step.
- APPLY and DESTROY wait up to 10 minutes for the Terraform state lock instead of failing immediately.
- Never cancel a run while a Terraform step is running. The runner kills Terraform within about 10 seconds, which can leave the state locked and resources half-created.
- PLAN fails if a chosen Availability Zone maps to an AZ ID that EKS does not support (`use1-az3` in us-east-1).

## Recovery: DESTROY stuck on a subnet, security group, or VPC

Rarely, the VPC CNI leaves a network interface in the `available` state after the nodes terminate. Terraform does not delete those itself, so deleting the subnet, security group, or VPC retries for up to 20 minutes and then fails. The NAT gateway, EIP and EKS resources are already gone by then, so the leftover network costs nothing. To recover, an administrator deletes the leftover interfaces in the VPC (EC2 console, **Network Interfaces**, filter by the VPC, status `available`), then runs DESTROY again.

## Permissions boundary

`docs/aws-eks-boundary-policy.json` is the content of the out-of-band IAM policy `finrisk-ai-eks-boundary`. After changing the file, update that policy in AWS so its default version matches the file exactly.
