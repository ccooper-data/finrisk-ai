# Bounded Live AWS Validation Plan

This is a separate empirical-validation milestone after the eight implementation phases.

## Hard gates before apply
- Confirm current AWS spend leaves sufficient headroom below the $100 project ceiling.
- Confirm AWS Budget exists at or below $100. The stack creates its own budget at APPLY and deletes it at DESTROY, so a standing account-level budget outside the stack is the control that survives a stalled teardown.
- Use a dedicated Terraform workspace/state for the validation window.
- EKS desired workers = 1, maximum = 2. Worker type `t3.large` (the PR 2a default; the account is on the Paid plan, which the operator confirmed on 2026-10-07).
- NAT, observability, and CloudTrail may be enabled only when required by the active test.
- Record start timestamp and Git SHA.

## Evidence sequence
1. **EKS scheduling:** record readiness and the in-pod smoke result from the deploy build's `FINRISK_EVIDENCE` lines, plus cluster, node group and add-on status from the EKS console. Operators have no Kubernetes access to the private API by design, so the console cannot list pods or nodes.
2. **HPA:** not exercisable with this design. There is no load generator, and no operator path to the private API to read replica counts. Record only that the metrics-server add-on is Active. HPA scale-out stays IMPLEMENTED / LIVE VALIDATION PENDING.
3. **Telemetry:** not exercisable with this design. The application has no OpenTelemetry exporter and nothing ships container logs, so the alarms have no data source and read OK by default. Do not cite alarm state as evidence. CloudWatch telemetry stays IMPLEMENTED / LIVE VALIDATION PENDING.
4. **Rollback:** not exercised live. The controlled path cannot ship a non-ready candidate: Deploy FinRisk Inference takes no image input and deploys only the image built from its own commit, Build Inference Image pushes only an image that passes its smoke test, and `main` is frozen from PLAN to DESTROY. Retain instead the passing CI run of `infra/tests/test_deploy_buildspec_runtime.py` at the window's Git SHA (it runs the deploy buildspec against a fake kubectl: a failed update returns to the previous revision, from PR 2b by re-patching the previous digest. A failed first deploy was deleted in V1; from PR 2b it is retained for diagnosis, which is not a rollback) and the live deploy's `result=deployed` and `smoke=passed` evidence lines. Never inject a failure by committing to `main` during a window, or by starting builds or pushing images outside Build Inference Image and Deploy FinRisk Inference.
5. **Teardown/cost:** destroy ephemeral runtime resources, verify absence, and record cost snapshot. From PR 2a, DESTROY also checks that nothing outside Terraform state remains and records it in `teardown-evidence.txt` (see below).

## Stop conditions
Immediately stop new validation activity if:
- projected/actual project spend reaches $75 without all remaining tests fitting comfortably below $100;
- Terraform proposes resources outside the documented validation architecture;
- a deploy build ends in `result=rollback_failed`;
- state integrity becomes uncertain.

## Required final evidence
- Git SHA
- Terraform plan/apply identifiers
- EKS cluster/workload evidence
- image digest + model SHA
- metrics-server add-on status (HPA scale-out is not claimed; see step 2)
- telemetry/SLO: not claimed (see step 3)
- rollback evidence (the buildspec runtime test's CI run at the window's Git SHA; see step 4)
- destroy evidence, including the DESTROY run's `teardown-evidence.txt`
- final cost snapshot, taken at least 24 hours after DESTROY
- a private copy of the workflow artifacts and the CodeBuild logs, made before DESTROY: DESTROY deletes the CodeBuild log group and the image, and the artifacts expire after 7 days

No live-runtime claim is permitted without this evidence. Live failed-deploy rollback is never claimed from a bounded window; it stays IMPLEMENTED / LIVE VALIDATION PENDING in `docs/aws-platform-acceptance-matrix.md`.

The 2026-10-03 window met this plan for deployment and serving; the record is in `docs/AWS_VALIDATION_CLOSEOUT.md`.

## V2 cluster add-ons (PR 2a)

From PR 2a, the bootstrap build (`infra/terraform/deploy/bootstrap-buildspec.yml.tftpl`) does more than create the `finrisk` namespace. In order, it:
1. Enforces Pod Security `restricted` on `finrisk`, `argocd` and `monitoring`.
2. Applies the exposure guard (`infra/k8s/cluster-guards.yaml`) and proves it with server-side dry runs.
3. Installs headless Argo CD from the sha256-pinned chart, with digest-pinned images.
4. Applies the AppProjects.
5. Has Argo CD sync the lean kube-prometheus-stack from its OCI manifest digest.

With PR 2a alone the deploy build was unchanged: it applied `infra/k8s/inference.yaml` (the V1 path). PR 2b moves the deploy to Argo CD and removes that file (see "V2 GitOps deploy" below). No IAM change is needed for PR 2a.

The bootstrap's evidence lines, in this order (the deployment evidence prefixes each with the project name):

| Line | Shows |
|---|---|
| `node count= instance_type= allocatable_pods= allocatable_cpu= allocatable_memory=` | Every node is the planned type; the first node's allocatable capacity |
| `guard policy=finrisk-no-external-exposure loadbalancer_dry_run=denied external_ips_dry_run=denied external_ips_denied_by= ingress_dry_run=denied pvc_dry_run=denied clusterip_dry_run=admitted` | Server-side dry runs in `finrisk`: the guard denies a LoadBalancer Service, a Service with externalIPs, an Ingress and a PersistentVolumeClaim, and admits a ClusterIP Service. `external_ips_denied_by` says whether the policy or the API server's own `DenyServiceExternalIPs` plugin denied it |
| `argocd chart=argo-cd-10.9.6 chart_sha256= image= server_replicas=0 ingresses=0 non_clusterip_services=0 admin_enabled=false application_namespaces=finrisk redis_auth=secret images_digest_pinned=yes` | The install matches the reviewed values |
| `monitoring app=finrisk-monitoring health=Healthy operation=Succeeded sync= oci_target= synced_revision= images_digest_pinned=yes reload=ProcessSignal lifecycle_api=off prometheus_up_series= prometheus_up_ok= repo_server_restarts= repo_server_last_termination=` | Prometheus runs from the pinned digest, without the lifecycle API, and scrapes kube-state-metrics |
| `bootstrap=complete namespace=finrisk` | Last line; the workflow requires it |

Every check behind these lines fails the build if it does not hold. Two fields are recorded rather than gated, because their live values are not yet known: `sync` (a server-side apply can show OutOfSync with nothing wrong) and `synced_revision`. The same applies to the repo-server restart fields.

Every wait and download in the bootstrap is bounded. At their bounds they add up to about 21 minutes, which leaves 4 minutes of the 25-minute build timeout for provisioning, the applies and the checks between waits (`infra/tests/test_cluster_addons.py` adds them up). Each kubectl call a wait polls with has a 10-second request timeout, and each download is retried on transient errors for at most about a minute.

A bootstrap stopped while Helm is installing Argo CD (a cancelled or timed-out run) leaves the Helm release pending, and Helm then refuses every later install. The next bootstrap stops with `Helm release argocd is pending from an interrupted bootstrap; DESTROY rather than retry`. Recovery is DESTROY; nothing rolls the release back.

DESTROY adds the step **Verify no orphaned AWS resources** after the empty-state check. It writes `teardown-evidence.txt` to the job summary and to the artifact `bounded-aws-teardown-evidence`:
- `vpc_tagged_remaining=0`
- `vpc_enis_remaining=0`, the network interfaces still in a remaining tagged VPC (looked up only when one remains)
- `available_ebs_volumes=none`, counting only volumes tagged for this cluster
- a `load_balancers=` note

If anything remains, the step fails and the teardown lease is kept. Every query is filtered to this project or cluster, so the evidence names no other resource. Two kinds of resource are covered indirectly:
- Network interfaces, including the VPC CNI's. An interface left in a subnet blocks deleting it, so `vpc_tagged_remaining=0` rules them out. An account-wide query would also list other clusters' interfaces.
- Load balancers. The deployer cannot list them. Their absence follows from three things: no tagged VPC remains (an in-VPC load balancer's network interfaces would have blocked deleting it), state is empty, and the guard's live LoadBalancer denial.

## V2 GitOps deploy (PR 2b)

From PR 2b, Argo CD deploys the inference chart; the deploy build only sets the image digest on the Application and verifies the result (`docs/bounded-aws-validation.md`, "GitOps deploy", and `docs/deployment-recovery-runbook.md`).

**Before the PLAN**
- The one IAM console step (`docs/bounded-aws-validation.md`, one-time setup step 6) is the default version of `finrisk-ai-deployer-deploy-path`, with its end state checked. Without it, APPLY fails at the deploy runner's access entry and the window must DESTROY. It is backward compatible, so it can be done as soon as PR 2b is merged.

**PLAN**
- PLAN passes `-var gitops_revision=$GITHUB_SHA`. The step **Verify the plan pins the GitOps revision** fails the PLAN unless the plan text has exactly one `FINRISK_GITOPS_REVISION=<sha>` line, inside the bootstrap project, equal to the run's commit, and no buildspec shown as `(known after apply)`. A failed PLAN cannot be applied.
- In the plan text, the bootstrap buildspec shows five `/tmp/finrisk/<file>` sha256 lines (now with `inference-app.yaml`) and that commit line; the deploy buildspec shows `TARGET_REVISION=<sha>`. The deploy runner's access entry shows `kubernetes_groups = ["finrisk-digest-writer"]`; the bootstrap's has none.

**Evidence lines** (in addition to PR 2a's; the deployment evidence prefixes each with the project name)

| Build | Line | Shows |
|---|---|---|
| bootstrap | `gitops app=finrisk/finrisk-inference project=finrisk target_revision= image_repository= conditions=` | The Application at the PLAN's commit, read back after the apply. `conditions=ComparisonError` is expected: no digest yet, so nothing deploys |
| workflow | `gitops_revision_check=<sha>` | The commit Argo CD deploys is the run's commit, the one its image was built from |
| deploy | `authz patch_app=yes get_app=yes patch_other_app=no create_app=no delete_app=no patch_appproject=no argocd_secrets=no create_rolebindings=no` | The live authorization preflight, before any change |
| deploy | `argocd_target_revision= previous_digest=` | The Application as the bootstrap left it; `none` before the first deploy |
| deploy | `argocd digest= sync=Synced revision= compared= operation=Succeeded synced= synced_revision= health=Healthy automated=True overrides=none image= ready= conditions= images= pending=none` | Argo CD converged on this digest at the PLAN's commit, by an automated sync of the Application's own source. `overrides=none` means the operation had no other source, `sources` or `manifests`; Argo CD's automated sync always carries a copy of the Application's source, which is not an override. On a timeout, the `failure=timeout` line's `pending=` names the checks never met |
| deploy | `smoke=passed model_sha256= feature_count= probability=` | Unchanged from V1 |
| deploy | `promql name=<app_up, ksm_up, requests, latency_mean_ms, predictions, inference_p95_ms, replicas_available, hpa_current_replicas> value=` | In-cluster Prometheus, queried from the pod |
| deploy | `result=deployed image_uri= revision= argocd_revision= previous_digest=` | Last line |

Other last lines: `result=observability_failed` (serving, but the PromQL evidence is missing; no rollback), `result=rolled_back` or `result=rollback_failed` (a failed update and the re-patch of the previous digest), `result=first_deploy_retained` (a failed first deploy, left in place until DESTROY; not a rollback), `result=failed` (a failed re-run of the deployed digest). Each fails the workflow.

**Time budget.** The deploy build's waits add up to 21.1 minutes on its worst path (a failed update, then the re-patch) and 18.8 minutes on the success path, inside the 30-minute build timeout with 4 minutes for provisioning and the work between waits (`infra/tests/test_delivery_recovery.py` parses them). PR 3's load test, inside this build, has about 7 minutes on the success path before the timeouts must be raised together.

**Buildspec sizes.** Rendered by Terraform 1.9.8 with realistic values, the bootstrap buildspec is about 19,700 characters against the 20,000-character CI cap, so about 300 characters are left. No primary source states CodeBuild's limit for an inline buildspec, so the cap stays. Any later bootstrap addition goes inside the sha256-checked embedded bundle, not the buildspec text. The deploy buildspec is about 17,500 characters, which leaves PR 3 about 2,500; its load-test manifest belongs in a sha256-checked bundle like the bootstrap's.

**First live run.** The rehearsal after PR 2a does not exercise any of this. Unless a second rehearsal is scheduled after PR 2b merges, the gate window is the first live run of: applications in any namespace, the group's RBAC through the access entry, the digest patch and the convergence wait, the app's ServiceMonitor scrape and the PromQL evidence, and the plan-text check. Each fails closed: the bootstrap's read-back, the deploy's `auth can-i` preflight and Application check (before any change), the 8-minute convergence bound, and the PLAN step.

## Rehearsal window (after PR 2a merges, before the V2 gate window)

**Sequencing.** Hold the PR 2b merge until the rehearsal's DESTROY. The rehearsal PLANs from the PR 2a merge commit, and under the frozen-`main` rule its deploy runs from that same commit, so `main` must still be the PR 2a merge. If PR 2b merges first, the rehearsal runs the PR 2b deploy path and needs one-time setup step 6 (`docs/bounded-aws-validation.md`) before its APPLY.

This optional practice window was approved for about $1. It runs PLAN, APPLY, Build Inference Image, Deploy FinRisk Inference (V1 deploy on top of the add-ons) and DESTROY. Its purpose is to retire the riskiest first-time unknowns of PR 2a before the gate window. It has its own gate:

**Before APPLY**
- PLAN from the PR 2a merge commit. In the plan text, check two things:
  - The bootstrap buildspec appears in full, with the four `/tmp/finrisk/<file>` sha256 lines. It must never show as `(known after apply)`.
  - `instance_types = ["t3.large"]`.
- Record the start time and the Git SHA.

**Objectives and the evidence that proves each**

| # | Objective | Evidence to save | Passes when |
|---|---|---|---|
| 1 | The node fits the add-ons | bootstrap `node` line; `kubectl top` table in the bootstrap log | `instance_type=t3.large`, `allocatable_pods=35` |
| 2 | The exposure guard works live | bootstrap `guard` line | LoadBalancer, externalIPs, Ingress and PVC `denied`, ClusterIP `admitted` |
| 3 | Argo CD installs from the pinned chart | bootstrap `argocd` line | as listed above, `images_digest_pinned=yes` |
| 4 | Argo CD syncs Prometheus from the OCI digest, and the Prometheus Pod is admitted under Pod Security `restricted` | bootstrap `monitoring` line | `health=Healthy operation=Succeeded lifecycle_api=off`, `prometheus_up_ok` at least 3; note whether `synced_revision` equals `oci_target` (PR 2b relies on that format) |
| 5 | The repo-server has memory headroom | bootstrap `monitoring` line | `repo_server_restarts=0 repo_server_last_termination=none` |
| 6 | The bootstrap fits its timeout | the bootstrap build's duration (CodeBuild build history, or the log timestamps) | under 20 minutes of the 25-minute build timeout |
| 7 | The V1 deploy still works on top of the add-ons | deploy `smoke=passed` and `result=deployed` lines | both present |
| 8 | Nothing outlives DESTROY | `Verify destroy state` passes; `teardown-evidence.txt` | `vpc_tagged_remaining=0 vpc_enis_remaining=0 available_ebs_volumes=none` |

**Teardown gate**
- Start DESTROY as soon as objectives 1 to 7 have evidence saved. Save the `finrisk-deployment-evidence` artifact, the plan evidence and an export of the CodeBuild log group. Do not keep the window open because the planned two hours or the 4-hour lease have not run out.
- On any failure, save the bootstrap or deploy log and DESTROY at once. Do not fix anything in the window: `main` stays frozen, and fixes go through a PR before the gate window.
- Do not cancel a deploy run while its bootstrap is installing Argo CD. A stopped install leaves the Helm release pending, and every later bootstrap then stops. If that happens, DESTROY.
- After DESTROY, objective 8 must pass. Take the Cost Explorer snapshot at least 24 hours later.

**What the rehearsal does not prove** (it belongs to PR 2b or PR 3, so the gate window is its first live run):
- The GitOps deploy: the Application `finrisk/finrisk-inference`, applications in any namespace, the `finrisk-digest-writer` group RBAC through the deploy access entry, the digest patch and convergence wait, and the PLAN `gitops_revision` marker. These are PR 2b, along with its IAM console step, which this window neither needs nor tests.
- That Prometheus scrapes the app through the chart's ServiceMonitor, and the PromQL evidence. The V1 manifest has no ServiceMonitor; this is PR 2b.
- HPA scale-out and the load Job (PR 3).
- Failure handling in the deploy build. It is not exercised, and live rollback is not claimed.
