# Probability calibration policy

Ranking and probability estimation are separate concerns.

Model selection uses validation ranking metrics; calibration is fit only after a ranking model is frozen, using validation-era predictions. The future test set is used once for final evaluation and never to fit a calibrator.

Supported post-hoc methods:
- isotonic regression;
- Platt/logit scaling.

A calibrated model must retain both raw and calibrated Brier/log-loss evidence. Calibration must not be described as improved discrimination unless ranking metrics also improve independently.
