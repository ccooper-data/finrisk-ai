# FinRisk AI — Version 1 Model Card

## Intended use
FinRisk AI is a research and portfolio system for ranking 12-month corporate financial-distress risk from information available at or before an SEC filing date. It is not investment advice, a credit decision engine, or a production bankruptcy oracle.

## Outcome and temporal contract
The promoted outcome is an SEC 8-K Item 1.03 bankruptcy/receivership event occurring strictly after the observation filing date and within 365 days.
Version 1 requires a complete 365-day outcome window for modelling and evaluation. Recent observations whose windows are incomplete are excluded, including already-known positives in that incomplete tail, because retaining only observable positives while non-events remain censored would create a selectively observed test region.
The final source snapshot records acquisition provenance and binds the outcome-observation cutoff to the frozen SEC submissions archive.

## Chronological split
- Train: 250,094 observations; 2,111 positives.
- Validation: 51,430 observations; 308 positives.
- Mature test population: 64,194 observations; 669 positives; 1.042% prevalence.
- PyTorch GRU test population after minimum-history requirements: 63,322 observations; 666 positives; 1.052% prevalence.
The censoring correction removed 16,743 incomplete-window observations, all from the test period. Train and validation populations were unchanged.

## Final PyTorch GRU evidence
The Version 1 headline is the predeclared seed-42 final run on the repaired, maturity-filtered pipeline:
- ROC-AUC: 0.8103
- Average precision: 0.0540
- Average precision / prevalence: 5.13x
- Calibrated Brier score: 0.010226
- Calibrated log loss: 0.05328
- Joint recalibration slope: approximately 1.001
This is a single fitted-model test result. It is not represented as a multi-seed test estimate.
A five-seed validation sensitivity experiment was run separately. It supports that the validation signal was not carried by one favorable seed, but it does not quantify test-set seed uncertainty.

## Boosted-tree evidence
On the full mature test population:
- ROC-AUC: 0.8068
- Average precision: 0.0448
- Average precision / prevalence: 4.30x
- Calibrated Brier score: 0.010172
- Calibrated log loss: 0.05212
On the exact 63,322 observations shared with the GRU, model-vs-model point estimates differ, but issuer-clustered paired bootstrap intervals cross zero for average precision, ROC-AUC, calibrated Brier, and calibrated log loss. Version 1 therefore makes no claim that either architecture outperforms the other.

## Benchmark evidence
Both promoted nonlinear models improve probability-quality metrics over validation-fitted constant benchmarks. The final analysis found approximately 12.1% log-loss improvement for the boosted tree and 10.8% for the GRU. Issuer-clustered benchmark comparisons remained favorable throughout the reported bootstrap replicates.
These cluster intervals are conditional on already-fitted models/calibrators. They do not include model-retraining uncertainty, calibration-refitting uncertainty, macroeconomic dependence across issuers, or full population-generalization uncertainty.

## Calibration interpretation
Calibration is not summarized with one adjective.
The GRU joint recalibration slope near 1 indicates good probability dispersion on the final test population. Its positive calibration-in-the-large offset indicates that the level is still underpredicted. Validation and test prevalence differ, so a calibrator fitted only on validation cannot know the later event level in advance.

## Reproducibility and leakage controls
Version 1 records source/cohort hashes, runtime environment, observation identifiers, sequence-preprocessing version, calibration fit fingerprints, and validation-reuse disclosures.
Sequence histories use a deterministic (cik, filed, adsh) ordering. Regression tests assert that adding or removing strictly later rows cannot alter earlier history tensors when the training/preprocessing window is held fixed.
The GRU uses validation for checkpoint selection and for fitting its Platt calibrator; this reuse is disclosed in the saved evidence and is a limitation.

## Superseded research artifacts
Metrics produced before the deterministic sequence-ordering repair or before outcome-window maturity filtering are historical research artifacts, not Version 1 performance claims. In particular, the earlier 6.33x test-lift figure is retired rather than compared with the Version 1 5.13x figure.

## Known limitations
- Item 1.03 captures a specific SEC-filed distress definition and is not every economically meaningful form of distress.
- Historical completeness of the SEC submissions-derived event source remains an evidence limitation unless separately established.
- The GRU cannot score observations lacking sufficient sequence history.
- Test data was inspected during iterative research; Version 1 does not represent the final test set as a pristine never-inspected holdout.
- The final GRU headline is one predeclared seed-42 fitted-model result.
- Model-vs-model superiority is not established.
- This system is research software, not a production financial decision system.
