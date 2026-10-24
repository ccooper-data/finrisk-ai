# AWS V2 Validation Closeout

## Status

FinRisk-AI V2 (the Helm chart, the Argo CD GitOps deploy, in-cluster Prometheus and a bounded HPA load test) ran in one bounded real-AWS window on 2026-10-16, at commit `7d0f526fa13408f38c6e9cf93d3305478148ef55` (main, frozen from PLAN to DESTROY). The six V2 gate items, approved on 2026-10-05, are assessed below. Items 1 to 5 pass. Item 6 is not marked passed: its teardown checks pass, but its Cost Explorer snapshot is operator-reported and not independently timestamped.

Two limits apply:

- **HPA scale-out was measured; served traffic was not.** The HPA took the Deployment from 1 to 3 replicas under load. Only one replica was confirmed Available within the measured window, so the window does not show the added replicas serving requests.
- **Rollback, telemetry and public serving were not exercised.** See [What was intentionally not claimed](#what-was-intentionally-not-claimed).

Whether item 6 is closed on the operator's cost report is the operator's decision. This record does not claim it.

## Gate window (2026-10-16)

Commit `7d0f526fa13408f38c6e9cf93d3305478148ef55`. The window came after the V2 pull requests #172 (cluster add-ons), #173 (GitOps deploy), #174 (`m7i-flex.large` workers) and #175 (load test and gate).

### Runs

| Step | Run | Result |
| --- | --- | --- |
| PLAN | `38953604095` | 60 to add, 0 to change, 0 to destroy. The "Verify the plan pins the GitOps revision" step passed with `FINRISK_GITOPS_REVISION=7d0f526fa13408f38c6e9cf93d3305478148ef55`. |
| APPLY | `38954004651` | "Apply complete! Resources: 60 added." The deploy access entry was created. The PLAN lists its Kubernetes group as `finrisk-digest-writer`; the APPLY log does not repeat the group. The item 3 authz line shows the release role can patch its Application. |
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
| 5 | A bounded load Job drives the HPA from 1 to at least 2 replicas, with PromQL and HPA status evidence | **PASS, with the caveat below.** HPA before: 1 of 1 replicas at 2% CPU. During: 3 of 3 at 446% CPU. After: 3 of 3. kube-state-metrics agrees: `hpa_max_current_replicas=3`, `hpa_max_desired_replicas=3`. `available_min=1`, `available_max=1`. `request_rate=61.7096`. `load job=finrisk-load hpa_scaled=yes max_replicas=3 job_deleted=yes`. |
| 6 | Evidence saved before DESTROY; DESTROY ends with empty state and no orphaned EBS volumes, load balancers or network interfaces; a Cost Explorer snapshot at least 24 hours later | **Teardown passes; the cost snapshot is open.** The Cost Explorer figures below were reported to this record on 2026-10-23, and no AWS-side timestamp was preserved, so the checker's `6f` stays PENDING (see Cost). The Deploy run's artifacts were saved before DESTROY. The CodeBuild log export has 643 rows (bootstrap 310, deploy 333). Its 28 evidence payloads match its `FINRISK_EVIDENCE` lines exactly, though the export adds that prefix to each line. Its query time is not recorded: the file was last written at 19:56:51Z, after DESTROY began at 19:55:48Z, and the CodeBuild log group was deleted at 19:56:25Z. DESTROY: 60 destroyed, `Verify destroy state` passed, `vpc_tagged_remaining=0 vpc_enis_remaining=0 available_ebs_volumes=none`, lease cleared. Load balancers are checked indirectly, as the gate documents. |

**Caveat on item 5.** `available_max=1`. The HPA scaled the Deployment to 3 replicas, but the two added replicas were not yet Available within the measured window. The evidence does not establish why those replicas were not yet Available. Item 5 passes as defined. The accurate claim is "the HPA scaled out to 3 replicas under load", not "3 replicas served traffic".

### Cost

Cost Explorer, unblended, with no filters, as reported by the operator at displayed precision:

| Window | Cost Explorer range | Estimated unblended cost |
| --- | --- | --- |
| Rehearsal | 2026-10-12 to 2026-10-14 | -$0.00 |
| Gate window | 2026-10-16 to 2026-10-22 | -$0.00 |

The operator reported both figures to this record on 2026-10-23. No AWS-side artifact was preserved, such as an exported Cost Explorer report with its query time, so the time each snapshot was pulled is not recorded, and AWS has not attested to these figures. The reported date is more than 24 hours after DESTROY on 2026-10-16. These are estimates, not proof that the underlying usage was free.

## Rehearsal (2026-10-12 to 2026-10-13)

Before the gate window, a bounded rehearsal exercised the same path on `main` at `553bc6c`. It passed all 8 objectives (31 of 31 checks).

- PLAN `38324699138`, APPLY `38324982196` (60 added), Build `38326367926`, Deploy `38326686746`, DESTROY `38328546967` (60 destroyed, no orphans, lease cleared).
- An earlier APPLY `38317490840` failed on `t3.large` with "not eligible for Free Tier" (58 of 60 created). The account is limited to Free Tier instance types. DESTROY `38323572764` cleaned up, and PR #174 made `m7i-flex.large` the worker default.
- The rehearsal showed the monitoring Application as `OutOfSync` while it was Healthy and Succeeded. The evidence does not record the cause; the bootstrap buildspec's comment ascribes this kind of OutOfSync to CRD defaulting. PR #173 (`a7805f2`) tolerates OutOfSync only for the inference HPA and ServiceMonitor, and only when the cluster's own state confirms the deploy. The gate window's Argo CD line shows `out_of_sync=none`, so that tolerance was not needed.

## What was intentionally not claimed

- **Public serving.** The Service is ClusterIP only. The exposure guard denies LoadBalancer Services, Ingress and PersistentVolumeClaims.
- **Live failed-deploy rollback.** The failure paths, including a failed first deploy retained for diagnosis until DESTROY, were validated against a fake kubectl in CI only. None ran live.
- **CloudWatch runtime telemetry.** No inference runtime telemetry exports to CloudWatch. The CodeBuild build logs do.
- **Grafana dashboards and alerting.** Grafana is not installed, and there is no Alertmanager and no PrometheusRule. The CloudWatch alarm definitions (`inference_errors`, `latency_p95`) were created and destroyed with the window but were not exercised.
- **Recovery, scale-down, capacity or latency under production traffic.** The load is a fixed synthetic rate that proves the HPA mechanism. It is not a performance test. The smoke and PromQL lines are self-reported by the image under test.

## Evidence location

Local copies of the window's workflow evidence and the CodeBuild log export are kept outside the repository. GitHub expired the workflow artifacts after their retention period; when this record was checked, the gate window's artifacts were no longer listed. No Cost Explorer capture was saved; the cost figures are the operator's report. DESTROY deletes the CodeBuild log group and the image, so the log export is the surviving record of the build logs.
