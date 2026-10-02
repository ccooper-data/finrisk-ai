# Bounded AWS EKS Validation Contract

The first window (2026-10-02) proved infrastructure provisioning and teardown. The deploy path below adds application deployment to the private EKS API; it is CI/static-validated and has not yet been exercised in a live window.

## Success criteria

- Terraform applies the exact reviewed binary plan.
- The EKS control plane reaches `ACTIVE`.
- The managed node group reaches `ACTIVE`.
- The EKS API remains private-only for this validation window.
- The inference image is built from the pinned model and passes its local smoke test before it is pushed.
- The deploy build rolls out the digest-pinned image, the pod is ready, and the in-pod smoke test returns a valid prediction from the pinned model.
- Evidence is captured, then the environment is destroyed no later than the persisted teardown lease.

## Deploy path

GitHub-hosted runners cannot reach the private EKS endpoint, so two CodeBuild projects run inside the private subnets (`infra/terraform/deploy_path.tf`). Their buildspecs are fixed by Terraform and reviewed with the plan.

| Identity | Can do | Cannot do |
|---|---|---|
| `github-finrisk-deployer` (environment `portfolio-validation`) | Terraform lifecycle, including the CodeBuild projects and their roles | Start builds; associate any EKS access policy other than the two below; assume any `finrisk-ai-*` role; create a cluster that grants its creator admin |
| `github-finrisk-releaser` (environment `portfolio-release`) | Push images to `finrisk-ai-inference`; start, watch and stop the two builds; read their logs | Change either project; override anything with an IAM condition key except `FINRISK_IMAGE_URI` on the deploy build (timeout and debug-session overrides have no key; debug sessions cannot connect) |
| `finrisk-ai-codebuild-bootstrap-*` | `AmazonEKSClusterAdminPolicy` (cluster scope); creates the `finrisk` namespace | Accept any caller-supplied variable |
| `finrisk-ai-codebuild-deploy-*` | `AmazonEKSEditPolicy` scoped to `finrisk`: apply, roll out, exec smoke test, roll back | Create namespaces or touch other namespaces |

The served model is pinned in `model/served-model.json` (source run, size, SHA-256). Changing it takes a reviewed commit, and the image build also checks that the training run's recorded Python, scikit-learn, numpy and pandas versions match `constraints/serving.txt`.

Actions artifacts expire after 30 days. The pinned model artifact (run 37055204267) expires 2026-11-01, and the cohort artifact that retraining needs (run 36626740566) expires 2026-10-29. After that, rebuild the cohort, retrain, show prediction equivalence with the pinned model, and update the pin in a reviewed commit; never loosen the provenance checks.

### One-time setup (administrator, before the next PLAN)

1. Update `finrisk-ai-eks-boundary` to match `docs/aws-eks-boundary-policy.json`.
2. Create the managed policy `finrisk-ai-deployer-deploy-path` from `docs/aws-deployer-deploy-path-policy.json` and attach it to `github-finrisk-deployer`.
3. Create the role `github-finrisk-releaser` with trust policy `docs/aws-release-trust-policy.json`, inline policy `docs/aws-release-policy.json`, and maximum session duration 2 hours.
4. In GitHub, create the environment `portfolio-release` limited to `main`, with the variable `AWS_RELEASE_ROLE_ARN`.
5. Optional, recommended: confirm with the IAM policy simulator that `StartBuild` requests carrying `BASH_ENV`, a buildspec override or an image override are denied, and that a request with only a digest-pinned `FINRISK_IMAGE_URI` is allowed.

### Window sequence

PLAN, review, APPLY the reviewed plan, then **Build Inference Image** (the ECR repository exists only while the stack is up), then **Deploy FinRisk Inference**, then capture evidence and DESTROY. `main` stays frozen from PLAN to DESTROY: the deploy takes no image input and uses the image built from its own commit, and the deploy buildspec's expected model SHA-256 is fixed at PLAN time, so all three must be the same commit. The deploy shares the provision workflow's concurrency group, so a DESTROY never starts under a running in-VPC build.

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

Rarely, the VPC CNI leaves a network interface in the `available` state after the nodes terminate. Terraform does not delete those itself, so deleting the subnet, security group, or VPC retries for up to 20 minutes and then fails. The NAT gateway, EIP and EKS resources are already gone by then, so the leftover network costs nothing. To recover, an administrator deletes the leftover interfaces in the VPC (EC2 console, **Network Interfaces**, filter by the VPC, status `available`), then runs DESTROY again. The same applies to an interface left by a CodeBuild runner (description starting `AWS CodeBuild`).

## Permissions boundary

`docs/aws-eks-boundary-policy.json` is the content of the out-of-band IAM policy `finrisk-ai-eks-boundary`. After changing the file, update that policy in AWS so its default version matches the file exactly.
