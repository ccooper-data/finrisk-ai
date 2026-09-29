# Case Study: When Green CI Was Not Enough

FinRisk AI's strongest engineering result is not a single model score. It is the evidence that attractive metrics were repeatedly challenged until the data and evaluation contracts matched the claims.

## 1. Right-censoring disguised as negative labels
**Failure:** recent filings without a full 365-day outcome window were implicitly labelled negative when no bankruptcy event had yet been observed.
**Risk:** test prevalence and probability-quality metrics were biased by observations whose outcomes were not yet knowable.
**Repair:** labels now separate known positives, mature negatives and incomplete windows. Modelling requires complete outcome windows. The SEC submissions acquisition timestamp and source hash bind the maturity cutoff to the evidence actually used.
**Measured effect:** 16,743 observations were removed, all from test; train and validation were unchanged.

## 2. Future rows could perturb earlier sequence histories
**Failure:** per-issuer sequence construction re-sorted by filing date alone after an earlier deterministic sort. Same-day filings could change order when strictly later rows were added or removed.
**Risk:** no future-dated value entered a history directly, but the reconstructed past tensor was not solely a function of information available through the cutoff.
**Repair:** sequence ordering uses the complete (cik, filed, adsh) key. Regression tests compare full history tensors after removing strictly later rows while holding the training/preprocessing window fixed.

## 3. Calibration claims needed observable evidence
**Failure:** a validation-only calibration claim could not be proven from bare probability arrays.
**Risk:** test-label leakage could produce an apparently well-calibrated model while the evidence layer merely repeated the intended policy.
**Repair:** the calibrator records a fingerprint of the arrays it actually fit. Evidence asserts that fingerprint matches validation and differs from test; mutation tests deliberately fit on test and require rejection.

## 4. Identifier extraction could produce plausible nonsense
**Failure:** early CUSIP discovery accepted patterns that could match nine-character English tokens, and later SEC-list parsing initially assumed the CUSIP occupied one PDF word/column.
**Risk:** identity coverage could look successful while linking non-security text or silently extracting zero valid securities.
**Repair:** CUSIP check-digit validation, positional PDF parsing, fixed-width TXT parsing, positive controls, option partitioning and fail-closed fidelity assertions were added. Parser failures are now separated from genuine source non-coverage.

## 5. A point estimate is not a model-family winner
**Finding:** the final GRU has higher point-estimate AP/ROC-AUC and the tree has lower point-estimate log loss on some comparisons.
**Control:** paired issuer-cluster resampling on the identical common test population.
**Conclusion:** intervals cross zero across the audited model-vs-model metrics, so Version 1 does not declare a winner.

## Leadership lesson
The project evolved from 'make the model score well' to 'make every promoted claim observable and falsifiable.' Recurring defects were converted into regression tests, provenance records and fail-closed contracts rather than handled as one-off fixes. That is the operating principle behind the Version 1 release.
