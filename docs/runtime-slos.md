# FinRisk-AI Runtime Reliability Contract

## Scope
These SLOs apply to the bounded portfolio inference deployment, not to the historical research pipeline.

## Service-level indicators
- **Availability SLI:** successful non-5xx inference responses / valid inference requests.
- **Latency SLI:** server-side inference duration measured at the API.
- **Readiness SLI:** readiness endpoint can load and validate the governed model artifact.
- **Deployment integrity:** serving response identifies the exact model artifact SHA-256.

## Portfolio SLOs
- Availability: **99.9%** during an active validation window.
- Latency: **p95 < 300 ms** for inference during the controlled validation workload.
- Server error rate: **< 1%** during the controlled validation workload.
- Readiness: deployment is not promoted while `/health/ready` returns non-200.

## Alert policy
CloudWatch operational resources are disabled by default and enabled only for bounded runtime validation.
- Any server-side inference error in a 5-minute validation window is investigated.
- p95 inference latency >= 300 ms over 5 minutes breaches the latency guardrail.
- Missing data does not page because the portfolio environment is intentionally ephemeral.

## Evidence standard
A runtime validation record should bind:
1. Git commit SHA.
2. Container image digest/tag.
3. Model artifact SHA-256.
4. EKS deployment revision.
5. Validation start/end timestamps.
6. SLI measurements and alarm state.
7. Teardown evidence.

These SLOs are engineering validation objectives, not claims of measured 24/7 production availability.
