# Deployment and Recovery Runbook

## Purpose
This runbook governs the bounded FinRisk-AI EKS validation deployment. It covers controlled promotion through Argo CD, the deploy build's automated rollback (a re-patch of the image digest recorded before the change), and verified teardown, without leaving a permanent portfolio environment running. Rollback is validated in CI against a fake kubectl; live failed-deploy rollback is not exercised in a bounded window and is not claimed.

## Preconditions
- Phase 1–6 acceptance gates are green on the commit being promoted.
- AWS Budget alert limit remains capped at $100 (alerts only) and current spend leaves adequate headroom.
- EKS and required NAT/observability resources are enabled only for the validation window.
- The reviewed plan for the commit being promoted is applied, and `main` has not moved since PLAN: Terraform fixes the cluster name, the deploy build's expected model SHA-256 and the commit Argo CD deploys the chart from (`gitops_revision`, the PLAN's own commit) at PLAN time.
- The deployer policy edit for the `finrisk-digest-writer` group (`docs/bounded-aws-validation.md`, one-time setup step 6) was the policy's default version before that APPLY.
- **Build Inference Image** has pushed the immutable `sha-<40 hex>` tag for that same commit to ECR.
- GitHub environment `portfolio-release` (limited to `main`) has `AWS_RELEASE_ROLE_ARN`, and `github-finrisk-releaser` allows 2-hour sessions.

## Promotion sequence
**Deploy FinRisk Inference** takes no inputs and shares the provision workflow's concurrency group, so it never runs alongside PLAN, APPLY or DESTROY.
1. Derive the image tag `sha-<commit>` from the workflow's own commit and validate its format.
2. Exchange GitHub OIDC identity for short-lived release-role credentials.
3. Resolve the tag to an immutable ECR digest; fail if this commit has no image.
4. Run the bootstrap CodeBuild project (cluster admin, no caller input). It refuses to run unless the plan pinned a commit. It creates the `finrisk`, `argocd` and `monitoring` namespaces and enforces (and warns on) Pod Security `restricted` in each. It then applies the exposure guard and proves it with server-side dry runs, installs headless Argo CD from the pinned chart, and waits for Argo CD to sync the lean Prometheus stack (see `docs/live-aws-validation-plan.md`). Last, it creates the Role and RoleBinding of the group `finrisk-digest-writer` and the Argo CD Application `finrisk/finrisk-inference`, which renders `charts/finrisk-inference` at the PLAN's commit. Until the deploy sets an image digest the chart does not render, so the Application shows a `ComparisonError` and deploys nothing; that is expected. Any failed check stops the bootstrap before `bootstrap=complete`, and the deploy does not start.
5. Check that the commit Argo CD deploys (the bootstrap's `gitops ... target_revision=` line) is this run's commit, the one whose image was resolved in step 3. Otherwise stop before the deploy build.
6. Run the deploy CodeBuild project (Edit in `finrisk`, plus read and patch on that one Application) with the digest-pinned `FINRISK_IMAGE_URI` as its only input. Inside the VPC it:
   1. re-validates the URI against this account's repository and digest form, and refuses an unset commit;
   2. checks its authorization live (`kubectl auth can-i`): it may get and patch the Application, and may not patch another Application, create or delete one, patch an AppProject, read Secrets in `argocd` or create RoleBindings;
   3. reads the Application and stops unless it is exactly the bootstrap's apart from the digest: project `finrisk`, this repository's chart at the PLAN's commit with the bootstrap's release name and values (the image repository of the URI), destination `finrisk`, the bootstrap's sync policy (automated with prune and self-heal, `FailOnSharedResource`, the retry limit), no other spec field, no pending operation, no finalizer, and at most one parameter, `image.digest`. That digest (or none) is recorded as the previous digest;
   4. patches only the `image.digest` parameter;
   5. waits up to 8 minutes until Argo CD reports the Application Synced and Healthy at the PLAN's commit with this digest both compared and synced, by an automated sync of the Application's own source (no other source, `sources` or `manifests` in the operation), and the Deployment has observed its template, runs the image and has a ready replica. A status left from the previous digest never passes; each poll's `pending=` lists the checks not yet met. A transient `Degraded` (the HPA's metrics lag after a rollout) is waited out; a failed sync or the Deployment's progress deadline ends the wait early;
   6. confirms the rollout and runs the in-pod smoke test: readiness and a prediction must both report the pinned model SHA-256, and the probability must be valid;
   7. queries the in-cluster Prometheus from inside the pod: the app and kube-state-metrics targets up, the smoke prediction counted in requests and predictions, with mean latency, p95 inference latency and replica counts recorded.
7. Record each build's ID, status and `FINRISK_EVIDENCE` lines in the `finrisk-deployment-evidence` artifact. The workflow passes only if both builds succeed and log their final evidence lines (`bootstrap=complete`, then `result=deployed`).

## Failure sequence
A failure before the patch (a rejected URI, an unset commit, an unreachable namespace, an unexpected `auth can-i` answer, or an Application that is unreadable, differs from the bootstrap's or has an operation pending) stops the deploy build before anything changes, with no `result=` line. If the patch, Argo CD's convergence, the rollout or the smoke test fails, the deploy build logs `failure=<patch|sync_failed|progress_deadline|timeout|rollout|smoke>` and then:
1. If an earlier digest was recorded, it re-patches that digest and waits again for Argo CD to converge on it (up to 5 minutes) and for the rollout. It logs `result=rolled_back` or `result=rollback_failed`. It never runs `kubectl rollout undo`: Argo CD's self-heal would revert it, and the Application, not the Deployment, is the source of truth.
2. If there was no earlier digest (the first deploy of the window), there is nothing to return to and the runner has no delete right: the Application and whatever Argo CD created stay in place for diagnosis until DESTROY. It logs `result=first_deploy_retained`. This is not a rollback; do not describe it as one or as a recovery.
3. If the failed digest is the one already recorded (a re-run of the same commit), there is nothing else to return to; it logs `result=failed`.
4. It exits 1 in every case, so the workflow stays failed even when the rollback succeeds.
5. The evidence artifact is uploaded on every outcome; preserve it and the CodeBuild log for root-cause analysis.
6. Do not retry deployment until the failure is understood.

If the release is serving but its PromQL evidence is missing, the deploy build logs `result=observability_failed` and exits 1 without a rollback: the release itself passed the smoke test, so only its evidence failed. Treat the window's observability gate as failed.

A failed bootstrap build stops the workflow before the deploy build runs, so nothing in `finrisk` changes. A bootstrap stopped while Helm was installing Argo CD (a cancelled or timed-out run) leaves the Helm release pending, and Helm then refuses every later install: the next bootstrap stops with `Helm release argocd is pending from an interrupted bootstrap`. Do not retry. Preserve the evidence and DESTROY; nothing rolls the release back.

If the result is `rollback_failed` or `first_deploy_retained`, or the run was cancelled or timed out (the workflow then stops the unfinished build and waits for it to stop, which can interrupt a patch or a rollback; if it reports the build may still be running, wait for it before DESTROY), treat the environment as an incident and do not claim automated recovery succeeded. The EKS API is private and only the two CodeBuild roles have cluster access entries, so there is no operator kubectl path: preserve the evidence and DESTROY.

## Scaling validation
The Phase-4 HPA contract is 1–3 inference replicas with a 70% CPU target. Live scale-out is not exercisable in the bounded window: there is no load generator, and operators have no Kubernetes access to the private API to read replica counts. Record only that the metrics-server add-on is Active; a load test is V1.1 work. Worker capacity remains separately capped by Terraform.

## Teardown
After evidence collection:
1. Save the window's workflow artifacts and export the CodeBuild logs (CloudWatch log group `/finrisk/codebuild/finrisk-ai-portfolio`). There is no runtime telemetry to export yet.
2. Disable or destroy EKS, NAT, CloudWatch, and CloudTrail validation resources.
3. Confirm Terraform plan no longer proposes retained billable runtime resources that were intended to be ephemeral. The DESTROY run's **Verify no orphaned AWS resources** step must pass, and its `teardown-evidence.txt` must show no tagged VPC (so no network interface left in its subnets) and no available volume of this cluster. If it fails, the teardown lease is kept; remove what it lists by hand.
4. Record teardown time and cost snapshot.

A successful deployment is not the final acceptance condition; successful teardown is part of the portfolio evidence.
