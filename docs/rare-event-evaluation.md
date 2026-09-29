# Rare-event evaluation suite

Accuracy is not a promoted metric for the distress task.

Every promoted classifier should report PR-AUC, ROC-AUC, Brier score, prevalence, positives, precision/recall/lift at controlled alert rates, and a thresholded operating point. Model selection is based on validation evidence. Version 1 explicitly discloses that the historical test set was inspected during iterative research; it is not represented as a pristine never-inspected holdout.

Alert-rate metrics answer an operational question: if analysts can investigate only the riskiest 0.1%, 0.5%, 1%, 2.5% or 5% of observations, how many actual distress events are captured and at what lift over prevalence?

## Version 1 comparison policy

Promoted model-vs-model claims require paired issuer-cluster evidence on an identical observation population. Point-estimate ordering alone is not described as superiority. The final boosted-tree versus PyTorch GRU intervals cross zero on all audited comparison metrics, so Version 1 reports both models without declaring a winner.

The final PyTorch GRU test headline is a single predeclared seed-42 fitted-model result. Multi-seed sensitivity is reported on validation rather than repeatedly selecting or optimizing against the historical test set.
