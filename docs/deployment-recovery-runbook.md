# Deployment and Recovery Runbook

## Purpose
This runbook governs the bounded FinRisk-AI EKS validation deployment. It proves controlled promotion and recovery without leaving a permanent portfolio environment running.

## Preconditions
- Phase 1–6 acceptance gates are green on the commit being promoted.
- AWS Budget alert limit remains capped at $100 (alerts only) and current spend leaves adequate headroom.
- EKS and required NAT/observability resources are enabled only for the validation window.
- The reviewed plan for the commit being promoted is applied, and `main` has not moved since PLAN: Terraform fixes the cluster name and the deploy build's expected model SHA-256 at PLAN time.
- **Build Inference Image** has pushed the immutable `sha-<40 hex>` tag for that same commit to ECR.
- GitHub environment `portfolio-release` (limited to `main`) has `AWS_RELEASE_ROLE_ARN`, and `github-finrisk-releaser` allows 2-hour sessions.

## Promotion sequence
**Deploy FinRisk Inference** takes no inputs and shares the provision workflow's concurrency group, so it never runs alongside PLAN, APPLY or DESTROY.
1. Derive the image tag `sha-<commit>` from the workflow's own commit and validate its format.
2. Exchange GitHub OIDC identity for short-lived release-role credentials.
3. Resolve the tag to an immutable ECR digest; fail if this commit has no image.
4. Run the bootstrap CodeBuild project (cluster admin, no caller input): create the `finrisk` namespace and enforce (and warn on) Pod Security `restricted`.
5. Run the deploy CodeBuild project (edit rights in `finrisk` only) with the digest-pinned `FINRISK_IMAGE_URI` as its only input. Inside the VPC it:
   1. re-validates the URI against this account's repository and digest form;
   2. records the current Deployment revision as the rollback target (none only when the Deployment does not exist);
   3. server-side dry-runs the manifest, failing if Pod Security admission warns that its Pod template would violate `restricted` (enforce rejects Pods, not the Deployment, so this would otherwise fail only after the apply), then server-side applies it;
   4. waits for rollout completion and at least one ready replica;
   5. runs the in-pod smoke test: readiness and a prediction must both report the pinned model SHA-256, and the probability must be valid.
6. Record each build's ID, status and `FINRISK_EVIDENCE` lines in the `finrisk-deployment-evidence` artifact. The workflow passes only if both builds succeed and log their final evidence lines (`bootstrap=complete`, then `result=deployed`).

## Failure sequence
A failure before the apply (for example a rejected URI, an unreachable namespace, an unreadable revision, a failed dry run or a Pod Security warning on it) stops the deploy build before anything changes. If apply, rollout, readiness or the smoke test fails, the deploy build:
1. Runs `rollout undo --to-revision` to the recorded revision and waits for that rollout; on a failed first deploy it deletes the Deployment instead.
2. Logs `result=rolled_back` or `result=rollback_failed`, then exits 1, so the workflow stays failed even when recovery succeeds.
3. The evidence artifact is uploaded on every outcome; preserve it and the CodeBuild log for root-cause analysis.
4. Do not retry deployment until the failure is understood.

If the result is `rollback_failed`, or the run was cancelled or timed out (the workflow then stops the unfinished build and waits for it to stop, which can interrupt an apply or a rollback; if it reports the build may still be running, wait for it before DESTROY), treat the environment as an incident and do not claim automated recovery succeeded. The EKS API is private and only the two CodeBuild roles have cluster access entries, so there is no operator kubectl path: preserve the evidence and DESTROY.

## Scaling validation
The Phase-4 HPA contract is 1–3 inference replicas with a 70% CPU target. Live validation should demonstrate scale-out and subsequent stabilization only during the bounded EKS window. Worker capacity remains separately capped by Terraform.

## Teardown
After evidence collection:
1. Export required deployment/telemetry evidence.
2. Disable or destroy EKS, NAT, CloudWatch, and CloudTrail validation resources.
3. Confirm Terraform plan no longer proposes retained billable runtime resources that were intended to be ephemeral.
4. Record teardown time and cost snapshot.

A successful deployment is not the final acceptance condition; successful teardown is part of the portfolio evidence.
