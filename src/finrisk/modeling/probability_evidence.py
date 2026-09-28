"""Validation-fitted calibration with inspectable held-out evaluation artifacts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from finrisk.modeling.calibration import ProbabilityCalibrator, array_fingerprint


def _inputs(labels, probabilities, partition: str):
    y = np.asarray(labels, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    if y.ndim != 1 or p.ndim != 1 or len(y) == 0 or len(y) != len(p):
        raise ValueError(f"{partition}: labels/probabilities must be nonempty aligned 1D arrays")
    if not np.isfinite(y).all() or not np.isin(y, [0, 1]).all():
        raise ValueError(f"{partition}: labels must be finite binary values")
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError(f"{partition}: probabilities must be finite and in [0, 1]")
    return y.astype(int), p


def _reliability_bins(y, p):
    """Fixed-width descriptive bins; never used to select or fit calibration."""
    bins = np.minimum((p * 10).astype(int), 9)
    result = []
    for i in range(10):
        mask = bins == i
        count = int(mask.sum())
        result.append({
            "lower": i / 10, "upper": (i + 1) / 10, "rows": count,
            "mean_probability": float(p[mask].mean()) if count else None,
            "event_rate": float(y[mask].mean()) if count else None,
        })
    return result


RANKING_TOLERANCE = 1e-12


def _assert_fit_partition(calibrator, pv, yv, pt, yt) -> str:
    """Verify the calibrator was fit on validation, by reading what it recorded.

    Note the limit of this boundary: the function receives bare arrays and cannot
    know an array's provenance, so "reject test data" is not expressible here.
    What is expressible -- and what this checks -- is that the calibrator's own
    record of its fit inputs matches validation and differs from test.
    """
    observed = getattr(calibrator, "fit_fingerprint_", None)
    if observed is None:
        raise ValueError("Calibrator did not record its fit inputs; leakage cannot be verified")
    if observed != array_fingerprint(pv, yv):
        raise ValueError("Calibrator fit inputs do not match the validation partition")
    if observed == array_fingerprint(pt, yt):
        raise ValueError("Calibrator was fit on the test partition")
    return observed


def _assert_ranking_preserved(method: str, raw: float | None, calibrated: float | None) -> None:
    """Platt is strictly monotone, so ROC-AUC must be bit-identical; any drift is
    a pipeline bug. Isotonic is weakly monotone and may only lose ranking."""
    if raw is None or calibrated is None:
        return
    if method == "platt" and abs(calibrated - raw) > RANKING_TOLERANCE:
        raise ValueError(f"Platt calibration altered ROC-AUC by {calibrated - raw:.3e}")
    if method == "isotonic" and calibrated - raw > RANKING_TOLERANCE:
        raise ValueError(f"Isotonic calibration increased ROC-AUC by {calibrated - raw:.3e}")


def probability_evidence(
    y_validation, p_validation, y_test, p_test, method: str = "platt", *,
    artifact_dir: Path | None = None, _calibrator_factory=ProbabilityCalibrator,
) -> dict:
    """Fit on validation only; evaluate the preselected method on test.

    Callers own row alignment, chronological splitting and label maturity.
    Test labels influence evaluation only, not calibrator or baseline fitting.
    """
    yv, pv = _inputs(y_validation, p_validation, "validation")
    yt, pt = _inputs(y_test, p_test, "test")
    if np.unique(yv).size != 2:
        raise ValueError("validation: calibration requires both outcome classes")
    calibrator = _calibrator_factory(method).fit(pv, yv)
    fit_fingerprint = _assert_fit_partition(calibrator, pv, yv, pt, yt)
    _, calibrated = _inputs(yt, calibrator.predict(pt), "calibrated test")
    baseline_probability = float(yv.mean())
    constant = np.full(len(yt), baseline_probability, dtype=float)
    prevalence = float(yt.mean())
    oracle_constant = np.full(len(yt), prevalence, dtype=float)
    both_classes = np.unique(yt).size == 2
    report = {
        "schema_version": 2,
        "calibration_method": method,
        "method_selection": "fixed_before_test_evaluation",
        "fit_partition": "validation",
        "fit_fingerprint": fit_fingerprint,
        "evaluation_partition": "test",
        "validation_rows": int(len(yv)),
        "validation_positives": int(yv.sum()),
        "validation_prevalence": baseline_probability,
        "test_rows": int(len(yt)),
        "test_positives": int(yt.sum()),
        "test_prevalence": prevalence,
        "baseline_fit_partition": "validation",
        "baseline_probability": baseline_probability,
        "ranking_status": "defined" if both_classes else "undefined_single_class_test",
        "ranking": {
            "raw_roc_auc": float(roc_auc_score(yt, pt)) if both_classes else None,
            "calibrated_roc_auc": (
                float(roc_auc_score(yt, calibrated)) if both_classes else None
            ),
            "raw_pr_auc": float(average_precision_score(yt, pt)) if both_classes else None,
            "calibrated_pr_auc": (
                float(average_precision_score(yt, calibrated)) if both_classes else None
            ),
        },
        "probability_quality": {
            "raw_brier": float(brier_score_loss(yt, pt)),
            "calibrated_brier": float(brier_score_loss(yt, calibrated)),
            "base_rate_brier": float(brier_score_loss(yt, constant)),
            "oracle_test_base_rate_brier": float(brier_score_loss(yt, oracle_constant)),
            "raw_log_loss": float(log_loss(yt, pt, labels=[0, 1])),
            "calibrated_log_loss": float(log_loss(yt, calibrated, labels=[0, 1])),
            "base_rate_log_loss": float(log_loss(yt, constant, labels=[0, 1])),
        },
        "reliability_bins": {
            "raw": _reliability_bins(yt, pt),
            "calibrated": _reliability_bins(yt, calibrated),
        },
        "versions": {"numpy": np.__version__, "scikit_learn": sklearn.__version__},
    }
    _assert_ranking_preserved(method, report["ranking"]["raw_roc_auc"],
                              report["ranking"]["calibrated_roc_auc"])
    if artifact_dir is not None:
        artifact_dir = Path(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        # These are private run artifacts, not approval to publish cohort-derived data.
        joblib.dump(calibrator, artifact_dir / "probability_calibrator.joblib")
        np.savez_compressed(
            artifact_dir / "calibration_predictions.npz",
            y_validation=yv, p_validation=pv, y_test=yt, p_test=pt,
            p_test_calibrated=calibrated,
        )
        (artifact_dir / "probability_evidence.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
        )
    return report


def cohort_input_evidence(cohort_path: Path) -> dict:
    """Fingerprint the consumed file; do not claim upstream lineage is verified."""
    cohort_path = Path(cohort_path)
    digest = hashlib.sha256()
    with cohort_path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "cohort_file": cohort_path.name,
        "cohort_sha256": digest.hexdigest(),
        "code_commit": os.environ.get("GITHUB_SHA"),
        "upstream_source_lineage": "not_verified_by_model_runner",
    }
