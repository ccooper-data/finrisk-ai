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
4. **Rollback:** deploy an intentionally non-ready candidate through the controlled workflow; retain failed deployment and verified previous-image recovery evidence.
5. **Teardown/cost:** destroy ephemeral runtime resources, verify absence, and record cost snapshot.

## Stop conditions
Immediately stop new validation activity if:
- projected/actual project spend reaches $75 without all remaining tests fitting comfortably below $100;
- Terraform proposes resources outside the documented validation architecture;
- rollback cannot restore a healthy workload;
- state integrity becomes uncertain.

## Required final evidence
- Git SHA
- Terraform plan/apply identifiers
- EKS cluster/workload evidence
- image digest + model SHA
- HPA evidence
- telemetry/SLO evidence
- rollback evidence
- destroy evidence
- final cost snapshot

No live-runtime claim is permitted without this evidence.
