# Probability calibration: integration and acceptance boundary

The logistic baseline, boosted tree, PyTorch GRU and TensorFlow GRU runners now fit
Platt calibration to validation predictions and apply the fitted mapping to test
predictions. The method is fixed in code, not selected by comparing test results.
The helper also supports isotonic calibration for explicitly configured experiments.
GRU predictions are collected after the selected checkpoint is restored. Existing
raw metrics, cohort selection, model hyperparameters and split cutoffs are unchanged.
MLP and ablation runners are outside this patch's integration scope.

## Outputs

Each of the four training output directories contains:

- The existing model metrics JSON, with additional `metrics.test.calibration` and
  `input` fields. Existing Brier/AUC fields remain explicitly raw results.
- `probability_evidence.json`: raw/calibrated Brier, log loss, ROC-AUC and average
  precision (the existing `pr_auc` convention), plus fixed-width reliability bins.
- `probability_calibrator.joblib`: the validation-fitted calibrator.
- `calibration_predictions.npz`: validation labels/raw predictions, test labels/raw
  predictions and calibrated test predictions, for replay without retraining.

The baseline now saves `baseline_model.joblib`; the boosted tree saves the fitted
model and imputer in `boosted_tree_model.joblib`. GRU checkpoint filenames remain
unchanged. These models still return RAW scores; apply the separate fitted
calibrator to those scores for calibrated output. Load joblib artifacts only from
trusted, verified runs. Prediction artifacts are evaluation evidence, not permission
to publish cohort-derived rows or source-restricted material.

`base_rate_brier` uses a constant fitted to VALIDATION prevalence. The separately
named `oracle_test_base_rate_brier` uses test prevalence and is retrospective only,
not a deployable benchmark. Schema version 2 makes this distinction explicit.
A lower Brier score alone does not establish calibration; inspect reliability bins,
log loss, ranking and sample counts too. No improvement is assumed or enforced.

## Validation

Tests execute the helper and small synthetic training paths, spy on actual fit
inputs, mutate test labels to verify fitted predictions do not change, replay the
persisted calibrator and exercise runner output wiring. Invalid probabilities,
nonbinary labels and single-class validation fail closed. Single-class test ranking
is explicitly undefined rather than serialized as NaN.

Real framework smoke tests use `pytest.importorskip`: default CI does not prove
PyTorch/TensorFlow execution when those dependencies are absent. Run
`pytest -q tests/test_model_calibration_integration.py` in each corresponding
ML-enabled training workflow; do not count skipped framework tests as passes.
Synthetic fixture scores are never research performance evidence.

## Not yet established

`input.cohort_sha256` fingerprints the exact consumed parquet file and
`input.code_commit` records GITHUB_SHA when present. This does NOT verify upstream
SEC source manifests, source-hash chains, security identity, censoring or label
maturity. The report explicitly records that upstream lineage is not verified by
the model runner. The helper validates arrays, not issuer/filing row identity.

Validation is reused for checkpoint selection and calibration; this is not a new
independent calibration holdout. Chronological observation splits alone do not
prove that 12-month label windows are mature or nonoverlapping at fit time. Those
point-in-time requirements need upstream verification before publication.

Acceptance still requires real-cohort reruns, inspection of all raw/calibrated
metrics and reliability evidence, upstream source-lineage/label-window review,
and a separately measured identity-enrichment comparison. No new historical
performance claims or recruiter-facing release are authorized by this patch.
