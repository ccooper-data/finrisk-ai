# AWS Validation Closeout

## Status

FinRisk-AI ran two bounded real-AWS validation windows:

- **2026-10-02, infrastructure lifecycle.** Controlled infrastructure promotion, EKS readiness, evidence capture and deterministic teardown, with no application deployed.
- **2026-10-03, EKS serving.** The pinned model was built into the production image and deployed through the private CodeBuild path. The pod became Ready, served the pinned model (SHA-256 verified) and returned a live prediction through the in-cluster Service. All 60 resources were then destroyed and empty state was verified.

V1 is complete. HPA scale-out, CloudWatch runtime telemetry and live failed-deploy rollback were not exercised; see [What was intentionally not claimed](#what-was-intentionally-not-claimed).

## Second window (2026-10-03): EKS serving

Commit `b83a3656d9c7e25c5d61f1e4accfac519585197d` (main, frozen from PLAN to DESTROY).

### Evidence chain

| Control | Evidence |
| --- | --- |
| Reviewed plan | PLAN run `37134101255`: 60 add / 0 change / 0 destroy. Independently reviewed before APPLY (plan against code, security, permissions, cost and teardown; every finding checked by two verifiers): no blockers. |
| Plan used for APPLY | PLAN run `37161316801`. Its 1,825-line redacted plan text is byte-identical to the reviewed plan; only the binary plan checksum differs. |
| Exact-plan promotion | APPLY run `37161882871`: "Apply complete! Resources: 60 added, 0 changed, 0 destroyed." |
| Pinned model | Training run `37055204267`, SHA-256 `ede499723ff72920048ceae5ddbc878ef90e6a8122b206bb5986efcc78e5b72b` (`model/served-model.json`) |
| Production image | Build Inference Image run `37162683296` pushed `finrisk-ai-inference@sha256:0c1e149206ed34aeb8f7ea9bad303ded4e331032b758a50079078a2a57cbcebd` (Python 3.12, pinned serving stack, smoke-tested before push) |
| Private deployment | Deploy FinRisk Inference run `37162787503`. The bootstrap build `5bf7fa5e-25f8-4751-b491-61adb89d18d3` logged `bootstrap=complete namespace=finrisk`. The deploy build `2dcf3e89-7e41-4050-8ea8-6223f1a4ebda` deployed the same digest at revision 1. |
| Pod Ready, model verified, live prediction | `smoke=passed model_sha256=ede499723ff72920048ceae5ddbc878ef90e6a8122b206bb5986efcc78e5b72b feature_count=8 probability=0.115200`, then `result=deployed … revision=1`. The prediction went through the in-cluster Service and matches the offline reproduction of the same model on the pinned stack. |
| Cluster state (EKS console) | Cluster Active (Kubernetes 1.35, private endpoint, EKS API authentication, 0 cluster health issues). Compute: one managed node group (created by APPLY in 1m 46s), 0 node health issues, 0 Fargate profiles, EKS Auto Mode disabled, so the Ready pod ran on the managed node group. The console cannot list pods or nodes because no console identity has Kubernetes access. metrics-server add-on Active at `v0.9.0-eksbuild.11`. |
| Kubernetes access | Four access entries: the bootstrap runner (AmazonEKSClusterAdminPolicy), the deploy runner (AmazonEKSEditPolicy, namespace `finrisk`), the node role, and the AWS-managed EKS service-linked role. No human, console or GitHub identity has Kubernetes access. |
| Deterministic teardown | DESTROY run `37163698470`: "Destroy complete! Resources: 60 destroyed." `Verify destroy state` passed (empty `terraform state list`), and the teardown lease was cleared. |
| Independent empty-state check | Reaper run `37193489529` (2026-10-04 09:51 UTC) found no lease and skipped its fail-safe destroy, which runs whenever state is non-empty without a lease. |
| Rollback control flow (offline) | ci run `37125039761` on the same commit: `pytest -q` passed (343 passed, 8 skipped). Test collection also executes `infra/tests/test_deploy_buildspec_runtime.py`, a script with no test functions. It runs the deploy buildspec's rollback paths against a fake kubectl and raises `SystemExit` if any check fails, which would have failed the run. |

The operator keeps the evidence in a private archive: workflow artifacts, the CodeBuild logs exported from CloudWatch (257 records, containing the three `FINRISK_EVIDENCE` lines above), and the EKS console captures. Workflow artifacts expire from GitHub after 7 days, and DESTROY deletes the CodeBuild log group and the image.

### First APPLY attempt and recovery

The first APPLY (run `37142940021`) stopped with AccessDenied after creating 47 of the 60 resources. The failed calls were `iam:CreateRole` for both CodeBuild runner roles and `eks:CreateAddon` for metrics-server. The managed policy `finrisk-ai-deployer-deploy-path` had been created in IAM but not attached to `github-finrisk-deployer`.

Recovery followed the contract. DESTROY run `37148135493` removed all 47 resources, verified empty state and cleared the lease. The policy was then attached with its JSON unchanged, and a fresh PLAN (`37161316801`) was confirmed identical to the reviewed plan before the second APPLY. The one-time setup in `docs/bounded-aws-validation.md` now asks the operator to confirm the attachment explicitly.

### Window facts

- APPLY started at **23:28 UTC**, and the verified DESTROY finished at **00:15 UTC**: about **47 minutes** from APPLY to empty state.
- EKS cluster creation took **10m 46s**, the node group **1m 46s** and the metrics-server add-on **44s**.
- Build Inference Image took about **1.5 minutes**, and Deploy FinRisk Inference about **3 minutes**.
- DESTROY took about **13 minutes**, including **3m 37s** to delete the EKS cluster. The CodeBuild runner security group was deleted in 1 second, with no leftover network interface.
- AWS cost, from Cost Explorer at least 24 hours after DESTROY, including the 1.5-hour failed attempt: **COST_SNAPSHOT_PENDING**.

## First window (2026-10-02): infrastructure lifecycle

### Evidence chain

| Control | Evidence |
| --- | --- |
| Reviewed infrastructure plan | GitHub Actions PLAN run `36950350218`, 45 add / 0 change / 0 destroy |
| Exact-plan promotion | APPLY run `37029203828` validated the source run, downloaded the private binary plan, verified the independent SHA-256 evidence, and applied that reviewed plan |
| Teardown lease | APPLY wrote the bounded teardown lease before Terraform mutation |
| Reaper validation | Reaper run `37016087352`, attempt 2, completed successfully while the lease remained active |
| Deterministic teardown | DESTROY run `37032984694` completed successfully |
| Empty-state verification | The final `Verify destroy state` step in run `37032984694` passed |
| Live validation commit | `d0096e9536b3b77597fc820ac391abccb0951c09` — the commit exercised by PLAN/APPLY/reaper/DESTROY |
| Post-validation hardening | `4361a69c54280537b1c8f1351eb2b4062b0dd257` — CI/static-validated only; not exercised in the live window |

### Validation window facts

- APPLY started at approximately **15:45 UTC** and verified DESTROY completed at approximately **16:30 UTC**, for a total bounded window of about **45 minutes**.
- EKS cluster creation took approximately **13m 11s**.
- Managed node-group creation took approximately **1m 57s**.
- DESTROY took approximately **12 minutes** through final state verification.
- Estimated AWS runtime cost for the validation window was **under $0.25**.

## Security and governance controls demonstrated

- GitHub OIDC with immutable repository/environment subject binding.
- Dedicated `portfolio-validation` (Terraform) and `portfolio-release` (image and deploy) environments, each restricted to `main`.
- Scoped deployer policy with explicit self-modification denial.
- Per-role EKS permissions boundary stored as code, also applied to the CodeBuild runner roles.
- S3 remote Terraform state with versioning, encryption, public-access blocking, and DynamoDB locking.
- Exact reviewed-plan promotion rather than re-planning during APPLY.
- Independent checksum evidence for the private plan.
- Private-only EKS API. Apart from the node role and the AWS-managed EKS service-linked role, the only identities with Kubernetes access are two in-VPC CodeBuild runners with fixed, plan-reviewed buildspecs. The release role can start them, and IAM denies every StartBuild override that has a condition key, except a digest-pinned `FINRISK_IMAGE_URI` on the deploy build. Timeout and debug-session overrides have no condition key, and debug sessions cannot connect.
- A model pinned by training run, size and SHA-256, verified again inside the running pod.
- AWS Budget alerts plus a persisted teardown lease and scheduled reaper.
- Manual DESTROY remains the primary closeout action; the reaper is the fail-safe backstop.

## Known limitations

- Network mutation permissions are constrained to `us-east-1`, but are region-scoped rather than resource-tag-scoped.
- IAM `CreateRole` cannot itself constrain the contents of a new role's trust policy. Risk is mitigated by the required EKS permissions boundary, generated-role naming constraints, and separate cluster/node managed-policy attachment allow-lists.
- The scheduled reaper depends on GitHub's best-effort cron execution. During validation, an approximately **7-hour scheduling gap** was observed. Manual DESTROY therefore remains the primary teardown control; the reaper is a backstop rather than a real-time scheduler.
- The reaper runs in its own concurrency group, so only a manual DESTROY is serialized with an in-VPC deploy build. Start the deploy promptly after APPLY so it finishes well before the lease expires.
- The reaper's `terraform init` has no workflow-level retry or backoff; Terraform's registry client makes only two quick attempts. Reaper run `37171879379` (2026-10-04 02:42 UTC) failed because both attempts to reach the Terraform provider registry failed ("connection reset by peer"). The stack was already destroyed, and the next run, about 7 hours later, succeeded.
- The only AWS Budget is created and destroyed with the stack, and budget data refreshes every 8–12 hours, so it cannot alert inside a window or after a stalled teardown.

## What was intentionally not claimed

- **Public serving.** The EKS API and the inference Service are private; nothing was exposed to the internet.
- **HPA scale-out.** The metrics-server add-on was Active, but no load was generated and operators have no Kubernetes access to the private API, so autoscaling was not exercised.
- **CloudWatch runtime telemetry.** The application has no OpenTelemetry exporter and nothing ships container logs, so the alarms had no data source. Their state is not evidence.
- **Live failed-deploy rollback.** The controlled path cannot ship a non-ready candidate. The rollback control flow is validated in CI against a fake kubectl (`infra/tests/test_deploy_buildspec_runtime.py`).

HPA scale-out, CloudWatch runtime telemetry and live failed-deploy rollback remain **IMPLEMENTED / LIVE VALIDATION PENDING** in `docs/aws-platform-acceptance-matrix.md`. Public serving is outside the V1 scope and has no matrix row: the inference Service is `ClusterIP`, and no ingress or load balancer is defined.

## V1.1 backlog

Not started; none of these changes the V1 result.

- HPA load test with replica evidence.
- OpenTelemetry exporter and container log shipping, so the SLO alarms have a data source.
- A reviewed failure-injection path for live rollback evidence.
- EKS control-plane audit and authenticator logs.
- Pin the metrics-server add-on version (`v0.9.0-eksbuild.11` was installed).
- Make the CodeBuild runner inline policies visible in the plan, by building the cluster ARN from locals.
- Audit bucket policy: add `aws:SourceArn` and a TLS-only deny.
- Remove the security groups that nothing attaches to (`alb`, `application`, `vpc_endpoints`), or attach them.
- A standing account-level budget outside the stack.
- Write the `FINRISK_EVIDENCE` lines to the workflow log as well as the 7-day artifact.
- Retry `terraform init` in the reaper, or commit a provider lock file, so a registry blip does not skip a cycle.

## Portfolio claim

A defensible summary is:

> Designed and secured an end-to-end financial-risk ML platform: point-in-time SEC data and temporal model validation, a pinned production container, and governed AWS infrastructure (Terraform, EKS, GitHub OIDC, scoped IAM and permissions boundaries, exact reviewed-plan promotion). Live-validated its AWS path in bounded real-AWS windows: exact reviewed-plan promotion, private EKS deployment through in-VPC CodeBuild with a live prediction verified against the pinned model, evidence capture, and verified teardown.

It must not be described as a fully production-validated AWS deployment; see the limitations above.

## Closeout rule

The bounded runtime environment is considered closed only when DESTROY succeeds and Terraform state verification is empty. Run `37032984694` satisfied both conditions for the first window, and run `37163698470` for the second.
