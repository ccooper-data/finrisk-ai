# Version 1 Results

## Final evaluation population
Version 1 evaluates only observations with complete 365-day outcome windows. The maturity correction removed 16,743 recent incomplete-window observations, all from the test period; train and validation were unchanged.

| Partition | Rows | Positives | Prevalence |
|---|---:|---:|---:|
| Train | 250,094 | 2,111 | 0.844% |
| Validation | 51,430 | 308 | 0.599% |
| Mature test | 64,194 | 669 | 1.042% |
| GRU mature test after sequence-history requirement | 63,322 | 666 | 1.052% |

## Promoted model results
| Metric | Logistic baseline | Boosted tree | PyTorch GRU |
|---|---:|---:|---:|
| ROC-AUC | 0.6224 | 0.8068 | 0.8103 |
| Average precision | 0.0150 | 0.0448 | 0.0540 |
| AP / prevalence | 1.44x | 4.30x | 5.13x |
| Calibrated Brier | 0.010325 | 0.010172 | 0.010226 |
| Calibrated log loss | 0.05864 | 0.05212 | 0.05328 |

The PyTorch GRU headline is a single predeclared seed-42 fitted-model result. Five-seed sensitivity was measured on validation, not by repeatedly selecting on test.

## What the comparisons support
Both nonlinear models materially improve rare-event ranking over the logistic baseline and improve probability-quality metrics over their validation-fitted constant benchmarks.

On the exact 63,322 observations shared by the boosted tree and GRU, paired issuer-cluster bootstrap intervals cross zero for average precision, ROC-AUC, calibrated Brier and calibrated log loss. Version 1 therefore does not claim one nonlinear architecture is superior.

## Calibration
The final GRU joint recalibration slope is approximately 1.001, indicating good dispersion. Its positive calibration-in-the-large offset indicates remaining level underprediction as event prevalence rises from validation to test.

## Superseded numbers
The earlier 6.33x GRU test-lift result is not a Version 1 result. It came from an earlier preprocessing/evaluation state before deterministic sequence ordering and complete-window maturity filtering. Version 1 replaces rather than compares against that figure.
