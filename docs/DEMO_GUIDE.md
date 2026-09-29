# FinRisk AI — Interview Demo Guide

## 30-second version
FinRisk AI is a point-in-time corporate distress-risk research pipeline built on SEC filings. The final PyTorch GRU reaches ROC-AUC 0.810 and average precision 0.054, about 5.13x the roughly 1.05% event prevalence. The differentiator is the evaluation discipline: I corrected right-censoring, deterministic sequence reconstruction, calibration-fit provenance and security-identifier fidelity, then used issuer-clustered comparisons rather than declaring a model winner from point estimates.

## Five-minute walkthrough
1. **Problem:** rare 12-month distress prediction where ordinary accuracy is meaningless and leakage is easy.
2. **Data contract:** SEC filing date defines what is knowable; Item 1.03 filings define the promoted distress outcome; only complete 365-day outcome windows enter final evaluation.
3. **Architecture:** source-hashed SEC cohort -> point-in-time features -> chronological train/validation/test -> logistic/tree/sequence models -> validation-fitted calibration -> evidence artifacts.
4. **Result:** final GRU ROC-AUC 0.8103, AP 0.0540, 5.13x prevalence lift. Boosted tree is also strong; clustered paired intervals do not establish superiority of either architecture.
5. **Engineering judgment:** show CASE_STUDY.md. Explain one defect, its risk, the regression that now prevents recurrence, and why green CI alone was insufficient.
6. **Close:** the system is research software, not a production financial decision engine. Version 1 freezes defensible claims rather than continuing to tune against test.

## Ten-minute technical path
- Open README.md for the problem and headline.
- Open docs/RESULTS.md for the frozen evaluation population and model table.
- Open docs/V1_MODEL_CARD.md for calibration, temporal contract and limitations.
- Open docs/CASE_STUDY.md for failure analysis and governance controls.
- If asked for implementation depth, show labels.py maturity selection, sequence ordering regression tests, probability calibration fit fingerprints, and SEC 13F parser fidelity tests.

## Manager / Director framing
Do not lead with GRU layer sizes. Lead with decision quality: defining evidence standards, separating discovery from acceptance, preventing leakage, converting repeated failure modes into controls, and refusing to promote claims that the evidence cannot distinguish.

## Questions to be ready for
**Why AP instead of accuracy?** Distress is about 1%; accuracy is dominated by negatives. AP measures ranking quality for the rare positive class.
**Why not claim the GRU beats the tree?** Point estimates differ, but paired issuer-cluster intervals cross zero.
**Why exclude recent known positives?** Their non-event counterparts are still censored; retaining only observable positives would create a selectively observed recent tail.
**Is it deployed?** No. It is a production-shaped research pipeline with auditable controls, not a production financial decision service.
**What would you do next in a real organization?** Establish an independently refreshed outcome source, prospective monitoring, retraining/calibration governance, drift controls, and decision-specific operating thresholds before production use.
