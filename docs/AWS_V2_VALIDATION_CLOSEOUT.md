# AWS V2 Validation Closeout

## Status

FinRisk-AI V2 (the Helm chart, the Argo CD GitOps deploy, in-cluster Prometheus and a bounded HPA load test) ran in one bounded real-AWS window on 2026-10-16, at commit `7d0f526fa13408f38c6e9cf93d3305478148ef55` (main, frozen from PLAN to DESTROY). All six V2 gate items, approved on 2026-10-05, pass against that window's evidence.

Two limits apply:

- **HPA scale-out was measured; served traffic was not.** The HPA took the Deployment from 1 to 3 replicas under load. Only one replica was confirmed Available within the measured window, so the window does not show the added replicas serving requests.
- **Rollback, telemetry and public serving were not exercised.** See [What was intentionally not claimed](#what-was-intentionally-not-claimed).

V2 is closed when this record is merged.

## Gate window (2026-10-16)

Commit `7d0f526fa13408f38c6e9cf93d3305478148ef55`. The window came after the V2 pull requests #172 (cluster add-ons), #173 (GitOps deploy), #174 (`m7i-flex.large` workers) and #175 (load test and gate).

### Runs

| Step | Run | Result |
| --- | --- | --- |
| PLAN | `38953604095` | 60 to add, 0 to change, 0 to destroy. The "Verify the plan pins the GitOps revision" step passed with `FINRISK_GITOPS_REVISION=7d0f526fa13408f38c6e9cf93d3305478148ef55`. |
| APPLY | `38954004651` | "Apply complete! Resources: 60 added." The deploy access entry was created with group `finrisk-digest-writer`, so the single deployer-policy edit works live. |
| Build Inference Image | `38956067877` | `finrisk-ai-inference@sha256:4aa0a35730ccccb40e84fb76811baa5dda3ed59a8864b4a8b74b2a7ae7e7ea8a`. Pinned model: training run `37055204267`, SHA-256 `ede499723ff72920048ceae5ddbc878ef90e6a8122b206bb5986efcc78e5b72b`. |
| Deploy FinRisk Inference | `38956338437` | Bootstrap and deploy builds succeeded. `result=deployed`. |
| DESTROY | `38958508125` | "Destroy complete! Resources: 60 destroyed." `Verify destroy state` passed, the orphan check passed, and the teardown lease was cleared. |
| Terraform Static Validation (gate item 1) | `38977751613` | `terraform-validate.yml` on `main` at `7d0f526`: `success`. Dispatched on 2026-10-16 after the window, to give item 1 a run at the frozen commit. It is a CI-only run and changes no content. |

### Gate items

| # | Gate item (approved 2026-10-05) | Result and evidence |
| --- | --- | --- |
| 1 | `charts/finrisk-inference` is the only deploy artifact; CI lints and renders it; the output passes the Pod Security and schema checks | **PASS.** Run `38977751613` at `7d0f526` succeeded, including the inference chart acceptance, the EKS deploy path acceptance and the deploy buildspec runtime acceptance. The PR-head run `38605599229` (at `a68b5da`, the same tree) was green too. |
| 2 | Argo CD is installed from a pinned chart with pinned digests and no UI; the Application tracks the chart at the frozen PLAN commit | **PASS.** `argocd chart=argo-cd-10.9.6 chart_sha256=6eda90bd…` with `images_digest_pinned=yes server_replicas=0 admin_enabled=false`. `gitops … target_revision=7d0f526…`. The bootstrap guard policy is `finrisk-no-external-exposure`. |
| 3 | The release role sets only the image digest; Argo CD reports Synced and Healthy; the in-pod smoke test passes with the pinned model SHA and a live prediction | **PASS, with no OutOfSync deviation.** `authz patch_app=yes … patch_other_app=no create_app=no delete_app=no patch_appproject=no argocd_secrets=no create_rolebindings=no`. `argocd … sync=Synced out_of_sync=none revision=7d0f526… synced_revision=7d0f526… health=Healthy`. `smoke=passed model_sha256=ede49972… probability=0.115200`. The deployed image equals the Build run's image. |
| 4 | Lean in-cluster Prometheus scrapes the app's `/metrics` and kube-state-metrics; PromQL evidence | **PASS.** `app_up=1`, `ksm_up=1`, `requests=1`, `predictions=1`, `latency_mean_ms=21`, `inference_p95_ms=24.25`. The monitoring Application was Healthy, Synced and Succeeded, with the Argo CD lifecycle API off. |
| 5 | A bounded load Job drives the HPA from 1 to at least 2 replicas, with PromQL and HPA status evidence | **PASS, with the caveat below.** HPA before: 1 of 1 replicas at 2% CPU. During: 3 of 3 at 446% CPU. After: 3 of 3. kube-state-metrics agrees: `hpa_max_current_replicas=3`, `hpa_max_desired_replicas=3`. `available_min=1`, `available_max=1`. `request_rate=61.71`. `load job=finrisk-load hpa_scaled=yes max_replicas=3 job_deleted=yes`. |
| 6 | Evidence saved before DESTROY; DESTROY ends with empty state and no orphaned EBS volumes, load balancers or network interfaces; a Cost Explorer snapshot at least 24 hours later | **Passes, with one attestation open:** the Cost Explorer figure below was reported by the operator, and its pull time is not recorded in the evidence. Artifacts and the CodeBuild log export were saved before DESTROY. The export has 643 rows (bootstrap 310, deploy 333), and every evidence line in the deployment artifact appears verbatim in it. DESTROY: 60 destroyed, `Verify destroy state` passed, `vpc_tagged_remaining=0 vpc_enis_remaining=0 available_ebs_volumes=none`, lease cleared. Load balancers are checked indirectly, as the gate documents. |

**Caveat on item 5.** `available_max=1`. The HPA scaled the Deployment to 3 replicas, but the two added replicas were not yet Available within the measured window. That matches the known slow first readiness probe under CPU throttling. Item 5 passes as defined. The accurate claim is "the HPA scaled out to 3 replicas under load", not "3 replicas served traffic".

### Cost

Cost Explorer, unblended, with no filters, as reported by the operator at displayed precision:

| Window | Cost Explorer range | Estimated unblended cost |
| --- | --- | --- |
| Rehearsal | 2026-10-12 to 2026-10-14 | -$0.00 |
| Gate window | 2026-10-16 to 2026-10-22 | -$0.00 |

These are estimates, not proof that the underlying usage was free. The pull time of each snapshot is not recorded in the evidence.

## Rehearsal (2026-10-12 to 2026-10-13)

Before the gate window, a bounded rehearsal exercised the same path on `main` at `553bc6c`. It passed all 8 objectives (31 of 31 checks).

- PLAN `38324699138`, APPLY `38324982196` (60 added), Build `38326367926`, Deploy `38326686746`, DESTROY `38328546967` (60 destroyed, no orphans, lease cleared).
- An earlier APPLY `38317490840` failed on `t3.large` with "not eligible for Free Tier" (58 of 60 created). The account is limited to Free Tier instance types. DESTROY `38323572764` cleaned up, and PR #174 made `m7i-flex.large` the worker default.
- The rehearsal showed the monitoring Application as `OutOfSync` while it was Healthy and Succeeded, a spurious server-side-apply difference. PR #173 (`a7805f2`) tolerates OutOfSync only for the inference HPA and ServiceMonitor, and only when the cluster's own state confirms the deploy. The gate window's Argo CD line shows `out_of_sync=none`, so that tolerance was not needed.

## What was intentionally not claimed

- **Public serving.** The Service is ClusterIP only. The exposure guard denies LoadBalancer Services, Ingress and PersistentVolumeClaims.
- **Live failed-deploy rollback.** The failure paths, including a failed first deploy retained for diagnosis until DESTROY, were validated against a fake kubectl in CI only. None ran live.
- **CloudWatch runtime telemetry.** Nothing exports to CloudWatch.
- **Grafana dashboards and alerting.** Grafana is not installed. There is no Alertmanager and no alert rule.
- **Recovery, scale-down, capacity or latency under production traffic.** The load is a fixed synthetic rate that proves the HPA mechanism. It is not a performance test. The smoke and PromQL lines are self-reported by the image under test.

## Evidence location

The operator keeps the workflow artifacts, the CodeBuild log export and the Cost Explorer captures in a private archive. GitHub expires workflow artifacts after their retention period; when this record was checked, the gate window's artifacts were no longer listed. DESTROY deletes the CodeBuild log group and the image, so the log export is the surviving record.
