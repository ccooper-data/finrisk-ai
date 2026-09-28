# Evidence diagnostics: acceptance boundaries

This extension changes evaluation metadata, not predictions, fitted calibrators,
cohort/split selection, model features, or early-stopping policy.

## Identifier support

The boosted tree and both GRUs emit validation/test identifiers. The logistic
baseline does not yet supply them; its identifier support remains unavailable.
Sequence identifiers are collected at prediction endpoints, not joined to the
input frame after histories have been reordered or excluded.

Supported CIK inputs are ASCII digit strings (1-10 digits, optional outer
whitespace), integers, and finite integral numeric floats within 1..9999999999.
Invalid or missing values become `unavailable`, not guessed identifiers. Decimal
or scientific-notation strings are not supported. Canonical output is a 10-digit
string. Unavailable/invalid CIKs do not count as issuers, and cannot create an
issuer/date event key. Event linkage comes from supplied next_distress_date;
it does not independently verify an event accession or its label window.

`supports_cluster_bootstrap` describes only mechanical readiness for a paired
CIK-cluster resampling of all held-out test rows, conditional on the existing
model/calibrator. Every test row must have a valid CIK, and at least two distinct
CIKs must exist. Validation identifiers and event identifiers are not required
for that scope. Blockers are explicit. Two clusters is a nondegeneracy minimum,
not evidence of statistical adequacy. This flag proves neither upstream row
alignment nor temporal independence and does not produce a confidence interval.

## Diagnostics

Quantile `realized_bins` counts populated groups. `interval_count` counts all
retained intervals, including empty ones. Equal predictions remain together;
labels do not determine boundaries. The existing fixed-width field is unchanged.

Joint unpenalized logistic recalibration is retrospective. For this one-covariate
plus intercept model, complete and quasi-separation are checked in either score
direction before fitting. A constant clipped logit is not an identified joint
fit. Convergence warnings, exhausted iterations, nonfinite coefficients, or a
failed mean-score check withhold joint coefficients and report an unavailable
status. Small score residuals alone are not an existence proof; separation is a
separate check. Overall status is `partial` when the joint fit fails but AP/lift
or the intercept-only offset remains valid. Constant raw predictions retain the
existing unavailable joint-fit status while preserving AP/lift and CITL.

TensorFlow checkpoint selection is threshold-approximated Keras PR AUC, not
scikit-learn average precision. PyTorch selects by average precision. Only the
TensorFlow disclosure label changes; neither training policy changes.

No test-fitted correction, bootstrap, significance claim, or publication approval
is introduced. Real-cohort reruns and upstream lineage/label-maturity acceptance
remain separate requirements.
