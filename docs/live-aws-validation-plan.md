# Bounded Live AWS Validation Plan

This is a separate empirical-validation milestone after the eight implementation phases.

## Hard gates before apply
- Confirm current AWS spend leaves sufficient headroom below the $100 project ceiling.
- Confirm AWS Budget exists at or below $100.
- Use a dedicated Terraform workspace/state for the validation window.
- EKS desired workers = 1, maximum = 2.
- NAT, observability, and CloudTrail may be enabled only when required by the active test.
- Record start timestamp and Git SHA.

## Evidence sequence
1. **EKS scheduling:** record node/pod state and successful readiness.
2. **HPA:** apply bounded load; record replicas before/during/after.
3. **Telemetry:** retain request/error/latency evidence and alarm state.
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
- HPA evidence
- telemetry/SLO evidence
- rollback evidence (the buildspec runtime test's CI run at the window's Git SHA; see step 4)
- destroy evidence
- final cost snapshot

No live-runtime claim is permitted without this evidence. Live failed-deploy rollback is never claimed from a bounded window; it stays IMPLEMENTED / LIVE VALIDATION PENDING in `docs/aws-platform-acceptance-matrix.md`.
