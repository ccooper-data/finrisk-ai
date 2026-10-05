# Bounded Live AWS Validation Plan

This is a separate empirical-validation milestone after the eight implementation phases.

## Hard gates before apply
- Confirm current AWS spend leaves sufficient headroom below the $100 project ceiling.
- Confirm AWS Budget exists at or below $100. The stack creates its own budget at APPLY and deletes it at DESTROY, so a standing account-level budget outside the stack is the control that survives a stalled teardown.
- Use a dedicated Terraform workspace/state for the validation window.
- EKS desired workers = 1, maximum = 2.
- NAT, observability, and CloudTrail may be enabled only when required by the active test.
- Record start timestamp and Git SHA.

## Evidence sequence
1. **EKS scheduling:** record readiness and the in-pod smoke result from the deploy build's `FINRISK_EVIDENCE` lines, plus cluster, node group and add-on status from the EKS console. Operators have no Kubernetes access to the private API by design, so the console cannot list pods or nodes.
2. **HPA:** not exercisable with this design. There is no load generator, and no operator path to the private API to read replica counts. Record only that the metrics-server add-on is Active. HPA scale-out stays IMPLEMENTED / LIVE VALIDATION PENDING.
3. **Telemetry:** not exercisable with this design. The application has no OpenTelemetry exporter and nothing ships container logs, so the alarms have no data source and read OK by default. Do not cite alarm state as evidence. CloudWatch telemetry stays IMPLEMENTED / LIVE VALIDATION PENDING.
4. **Rollback:** not exercised live. The controlled path cannot ship a non-ready candidate: Deploy FinRisk Inference takes no image input and deploys only the image built from its own commit, Build Inference Image pushes only an image that passes its smoke test, and `main` is frozen from PLAN to DESTROY. Retain instead the passing CI run of `infra/tests/test_deploy_buildspec_runtime.py` at the window's Git SHA (it runs the deploy buildspec against a fake kubectl: a failed update returns to the previous revision, a failed first deploy is deleted) and the live deploy's `result=deployed` and `smoke=passed` evidence lines. Never inject a failure by committing to `main` during a window, or by starting builds or pushing images outside Build Inference Image and Deploy FinRisk Inference.
5. **Teardown/cost:** destroy ephemeral runtime resources, verify absence, and record cost snapshot.

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
- destroy evidence
- final cost snapshot, taken at least 24 hours after DESTROY
- a private copy of the workflow artifacts and the CodeBuild logs, made before DESTROY: DESTROY deletes the CodeBuild log group and the image, and the artifacts expire after 7 days

No live-runtime claim is permitted without this evidence. Live failed-deploy rollback is never claimed from a bounded window; it stays IMPLEMENTED / LIVE VALIDATION PENDING in `docs/aws-platform-acceptance-matrix.md`.

The 2026-10-03 window met this plan for deployment and serving; the record is in `docs/AWS_VALIDATION_CLOSEOUT.md`.
