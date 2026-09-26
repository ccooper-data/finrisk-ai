# Rare-event evaluation suite

Accuracy is not a promoted metric for the distress task.

Every promoted classifier should report PR-AUC, ROC-AUC, Brier score, prevalence, positives, precision/recall/lift at controlled alert rates, and a thresholded operating point. The future test set remains untouched by model selection.

Alert-rate metrics answer an operational question: if analysts can investigate only the riskiest 0.1%, 0.5%, 1%, 2.5% or 5% of observations, how many actual distress events are captured and at what lift over prevalence?
