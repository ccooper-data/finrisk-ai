# PyTorch GRU seed sensitivity: bounded validation-only experiment

## Purpose and scope

Measure whether the current PyTorch GRU's validation ranking is sensitive to
training randomness before treating one seed's historical test AP as a stable
headline. This is a sensitivity exercise after test inspection, not prospective
confirmation on a pristine holdout and not a seed-selection contest.

Five fixed seeds: **11, 23, 42, 71, 101**. Seed 42 was already observed; do not
present the whole set as newly blinded independent experiments. Do not replace
poor/failed seeds or add seeds after seeing results. Every seed is reported.

The frozen input is the exact cohort parquet with SHA-256:
`c759d1223f5c7b6454ac17b31943cff8aa4b0f260a3097fe7b5b35dd50d24491`.
It comes from GitHub Actions cohort run `36201584816`. This file hash does not
validate upstream source lineage, censoring, purging or 12-month label maturity.

## Frozen training policy

Use the existing PyTorch architecture, features, sequence builder, imputer,
scaler, class weighting, optimizer, dropout, clipping and early stopping. The
budget remains 40 epochs, batch size 2048, patience 7, and validation AP
improvement of 1e-5. Existing calls retain seed 42 and test evaluation by default.

The new validation-only mode removes rows after 2022-12-31 BEFORE calling the
sequence builder, and it never evaluates test predictions or fits a calibrator.
The sweep entry point also removes those rows before calling the trainer.
The full parquet is read to select dated rows; this is not a claim that test
bytes were never accessed. Test labels/features do not enter training or scoring
in this mode. Label-window maturity is a separate, still-open acceptance check.

## Evidence

Retain every seed's checkpoint, validation predictions, endpoint identifiers,
metrics and early-stopping history. Record code commit, cohort hash and runtime
versions/threading/determinism settings. Compare validation observation-ID and
label digests across seeds. A seed's failure is persisted and prevents a complete
summary; successful seeds are not selectively summarized.

Report validation AP, AP/prevalence and ROC-AUC per seed, plus median, min/max and
quartiles. These five-seed spreads are descriptive, NOT confidence intervals.
They describe checkpoint-selected validation scores, not independently held-out
performance. No winning seed or automatic pass threshold is emitted.

This first sweep does NOT establish multi-seed test AP or calibrated test-loss
stability. A subsequent test sensitivity report would require a frozen all-seed
reporting policy, not selection of the best test seed, and explicit disclosure
that the historical test has already been examined.

## Framework interpretation

The two GRU implementations are not controlled identical models. In the current
code PyTorch dropout is between stacked recurrent layers; TensorFlow sets input
dropout on each GRU. PyTorch checkpoints on sklearn average precision; TensorFlow
checkpoints on threshold-approximated Keras PR area. PyTorch explicitly clips
gradients and TensorFlow's optimizer does not specify equivalent clipping.
Initialization and numerical implementations also differ. Same integer seed
across frameworks does not match initialization or dropout streams. Therefore the
cross-framework gap motivates a within-framework sweep but does not measure seed
variance. Do not modify either implementation to match the other in this patch.

## Existing-population reconciliation

Previously downloaded artifacts: tree `36480454647`; PyTorch `36485427108`.
On the exact same 49,854 validation observation IDs, tree AP is
`0.029141358853126093` and PyTorch AP is `0.0355938317975597`. This supports a
validation-based preference; it does not reconstruct proof that selection was
frozen before any test result was inspected.

The 1,287 tree-only test rows represent 1,287 distinct CIKs, but 1,123 of those
CIKs also have a GRU-scored test row. Only 164 CIKs are entirely tree-only. Thus
these exclusions must not be described as 1,287 single-filing-only companies.
They represent an observation-level history/coverage limitation. The observed
1.59% exclusion rate is cohort-specific, not a forecast of deployment coverage.

The MLP comparisons are not a controlled ablation establishing the causal value
of temporal order/history. Any such ablation should first be frozen and evaluated
on matched validation populations, not selected by this already-examined test.

## Execution

Run the separate workflow `PyTorch GRU validation seed sweep` from the reviewed
commit. It uses the existing frozen artifact and does not fetch SEC/EODHD data.
There is no automatic merge, training launch, identity-enrichment integration,
new operating threshold or recruiter-facing performance approval in this change.
