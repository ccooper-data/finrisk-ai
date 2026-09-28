"""Validation-fitted calibration with inspectable held-out evaluation artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import warnings
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from scipy.special import expit
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from finrisk.modeling.calibration import ProbabilityCalibrator, array_fingerprint
from finrisk.modeling import observation_identity


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



LOGIT_CLIP = (1e-12, 1.0 - 1e-12)
JOINT_FIT_TOL = 1e-10
MAX_JOINT_ITERATIONS = 20000
MEAN_SCORE_TOLERANCE = 1e-7
UNAVAILABLE = "unavailable"


def _logit(p):
    lo, hi = LOGIT_CLIP
    q = np.clip(np.asarray(p, dtype=float), lo, hi)
    return np.log(q / (1.0 - q))


def _quantile_reliability_bins(y, p, bins: int = 10) -> dict:
    """Quantile bins, reported alongside the fixed-width bins rather than replacing them.

    Boundaries come from the predictions only -- never from labels. Identical
    probabilities always land in the same bin: at this prevalence many rows share
    a score, so splitting ties to manufacture ten populated bins would invent
    structure. Realized bin count is reported so a collapsed distribution is
    visible instead of hidden.
    """
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    edges = np.unique(np.quantile(p, np.linspace(0.0, 1.0, bins + 1)))
    if edges.size < 2:
        return {"strategy": "quantile", "status": "degenerate_constant_predictions",
                "requested_bins": bins, "realized_bins": 1, "interval_count": 1,
                "boundaries": [float(edges[0])] if edges.size else [],
                "bins": [{"lower": float(edges[0]) if edges.size else None,
                          "upper": float(edges[0]) if edges.size else None,
                          "rows": int(len(p)), "positives": int(y.sum()),
                          "mean_probability": float(p.mean()) if len(p) else None,
                          "event_rate": float(y.mean()) if len(y) else None}]}
    # searchsorted on unique interior edges keeps tied scores in one bin.
    interior = edges[1:-1]
    index = np.searchsorted(interior, p, side="right")
    rows = []
    for i in range(len(interior) + 1):
        mask = index == i
        count = int(mask.sum())
        rows.append({
            "lower": float(edges[i]), "upper": float(edges[i + 1]),
            "rows": count, "positives": int(y[mask].sum()) if count else 0,
            "mean_probability": float(p[mask].mean()) if count else None,
            "event_rate": float(y[mask].mean()) if count else None,
        })
    return {"strategy": "quantile", "status": "ok", "requested_bins": bins,
            "realized_bins": sum(row["rows"] > 0 for row in rows),
            "interval_count": len(rows), "boundaries": [float(e) for e in edges],
            "bins": rows}


def _calibration_in_the_large(y, p) -> float | None:
    """Intercept-only offset: solve sum(y - sigmoid(logit(p) + a)) = 0 for a.

    This is the standalone calibration-in-the-large term. It is NOT the intercept
    of the joint fit: with a slope other than 1 the joint intercept is evaluated
    at logit(p)=0, far outside the range of these predictions, so it cannot be
    read as a base-rate effect.
    """
    z = _logit(p)
    y = np.asarray(y, dtype=float)

    def score(a):
        return float(np.sum(y - 1.0 / (1.0 + np.exp(-(z + a)))))

    lo, hi = -40.0, 40.0
    if score(lo) < 0 or score(hi) > 0:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if score(mid) > 0:
            lo = mid
        else:
            hi = mid
    return float(0.5 * (lo + hi))


def calibration_diagnostics(y_test, p_calibrated) -> dict:
    """Retrospective test-label diagnostics; never apply these fits to predictions.

    Finite logistic MLEs require overlap, not just a small optimizer gradient.
    The separation check below is specific to one logit covariate + intercept.
    Joint-fit failure does not discard independently valid AP/lift or CITL.
    """
    report = {
        "uses_test_labels": True,
        "used_for_prediction": False,
        "used_for_model_selection": False,
        "estimator": "unpenalised binomial logistic MLE on logit(p); lbfgs",
        "solver_tolerance": JOINT_FIT_TOL,
        "mean_score_tolerance": MEAN_SCORE_TOLERANCE,
        "logit_clip": [float(LOGIT_CLIP[0]), float(LOGIT_CLIP[1])],
    }
    try:
        y, p = _inputs(y_test, p_calibrated, "diagnostics")
    except (TypeError, ValueError):
        report["status"] = "unavailable_invalid_inputs"
        return report
    report["prevalence"] = float(y.mean())
    if np.unique(y).size != 2:
        report["status"] = "unavailable_single_class_test"
        return report
    report["average_precision"] = float(average_precision_score(y, p))
    report["average_precision_over_prevalence"] = report["average_precision"] / report["prevalence"]
    offset = _calibration_in_the_large(y, p)
    report["calibration_in_the_large"] = (
        {"status": "ok", "intercept_only_offset": offset, "slope_fixed_at": 1.0}
        if offset is not None else {"status": "unavailable_no_bracketed_root"})
    if np.unique(p).size < 2:
        # Retain the existing status/absence of a joint fit, but preserve the
        # now-computed AP, lift and identifiable intercept-only offset.
        report["status"] = "unavailable_constant_predictions"
        return report

    z = _logit(p)
    joint = None
    if np.unique(z).size < 2:
        joint = {"status": "unavailable_constant_logit_after_clipping"}
    else:
        z0, z1 = z[y == 0], z[y == 1]
        if z0.max() < z1.min() or z1.max() < z0.min():
            joint = {"status": "unavailable_complete_separation"}
        elif z0.max() == z1.min() or z1.max() == z0.min():
            joint = {"status": "unavailable_quasi_separation"}
    if joint is None:
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ConvergenceWarning)
                fit = LogisticRegression(
                    penalty=None, solver="lbfgs", max_iter=MAX_JOINT_ITERATIONS,
                    tol=JOINT_FIT_TOL,
                ).fit(z.reshape(-1, 1), y)
            iterations = int(np.max(fit.n_iter_))
            warned = any(issubclass(w.category, ConvergenceWarning) for w in caught)
            coefficients = np.array([fit.intercept_[0], fit.coef_[0][0]], dtype=float)
            if warned or iterations >= MAX_JOINT_ITERATIONS:
                joint = {"status": "unavailable_nonconverged", "converged": False,
                         "iterations": iterations, "convergence_warning": warned}
            elif not np.isfinite(coefficients).all():
                joint = {"status": "unavailable_nonfinite_coefficients", "converged": False}
            else:
                residual = y - expit(coefficients[0] + coefficients[1] * z)
                score = float(max(abs(residual.mean()), abs(np.mean(residual * z))))
                if not np.isfinite(score) or score > MEAN_SCORE_TOLERANCE:
                    joint = {"status": "unavailable_score_equations", "converged": False,
                             "iterations": iterations}
                else:
                    joint = {
                        "status": "ok", "intercept": float(coefficients[0]),
                        "slope": float(coefficients[1]), "converged": True,
                        "iterations": iterations, "max_abs_mean_score": score,
                        "note": "intercept and slope act jointly; the intercept is not a base-rate term",
                    }
        except Exception as exc:
            # A retrospective diagnostic is allowed to be unavailable; a model
            # run must not fail or publish invalid coefficients because of it.
            joint = {"status": "unavailable_fit_failed", "error_type": type(exc).__name__,
                     "converged": False}
    report["joint_recalibration"] = joint
    report["status"] = ("ok" if joint["status"] == "ok"
                        and report["calibration_in_the_large"]["status"] == "ok" else "partial")
    return report


def _assert_fit_partition(calibrator, pv, yv, pt, yt) -> str:
    """Check recorded fit inputs, not upstream row or temporal provenance.

    The supplied arrays are the limit of this check. Distinct underlying rows
    can have identical score/label arrays, so equality is a conservative block,
    not proof that the upstream rows are the same.
    """
    observed = getattr(calibrator, "fit_fingerprint_", None)
    if observed is None:
        raise ValueError("Calibrator did not record its fit inputs; leakage cannot be verified")
    if observed != array_fingerprint(pv, yv):
        raise ValueError("Calibrator fit inputs do not match the validation partition")
    if observed == array_fingerprint(pt, yt):
        raise ValueError("Calibrator was fit on the test partition or the arrays are identical")
    return observed


def probability_evidence(
    y_validation, p_validation, y_test, p_test, method: str = "platt", *,
    artifact_dir: Path | None = None, _calibrator_factory=ProbabilityCalibrator,
    validation_identifiers: dict | None = None, test_identifiers: dict | None = None,
    validation_reuse: dict | None = None,
) -> dict:
    """Fit on validation only; evaluate the preselected method on test.

    Callers own row alignment, chronological splitting and label maturity.
    Test labels influence evaluation only, not calibrator or baseline fitting.
    """
    yv, pv = _inputs(y_validation, p_validation, "validation")
    yt, pt = _inputs(y_test, p_test, "test")
    if validation_identifiers is not None:
        observation_identity.assert_aligned(validation_identifiers, pv, "validation")
    if test_identifiers is not None:
        observation_identity.assert_aligned(test_identifiers, pt, "test")
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
    bootstrap_readiness = observation_identity.cluster_bootstrap_readiness(test_identifiers)
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
        "quantile_reliability_bins": {
            "raw": _quantile_reliability_bins(yt, pt),
            "calibrated": _quantile_reliability_bins(yt, calibrated),
        },
        "test_calibration_diagnostics": calibration_diagnostics(yt, calibrated),
        "identifier_coverage": {
            "validation": (observation_identity.coverage(validation_identifiers)
                           if validation_identifiers is not None else UNAVAILABLE),
            "test": (observation_identity.coverage(test_identifiers)
                     if test_identifiers is not None else UNAVAILABLE),
            "supports_cluster_bootstrap": bootstrap_readiness["supports_cluster_bootstrap"],
            "cluster_bootstrap_readiness": bootstrap_readiness,
        },
        "validation_reuse": validation_reuse if validation_reuse is not None else {
            "checkpoint_selection_uses_validation": UNAVAILABLE,
            "calibration_uses_validation": True,
            "independent_calibration_holdout": False,
            "optimism_quantified": False,
        },
        "versions": {"numpy": np.__version__, "scikit_learn": sklearn.__version__},
    }
    if artifact_dir is not None:
        artifact_dir = Path(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        # These are private run artifacts, not approval to publish cohort-derived data.
        joblib.dump(calibrator, artifact_dir / "probability_calibrator.joblib")
        arrays = {"y_validation": yv, "p_validation": pv, "y_test": yt, "p_test": pt,
                  "p_test_calibrated": calibrated}
        for prefix, ids in (("validation", validation_identifiers), ("test", test_identifiers)):
            if ids is None:
                continue
            for field in observation_identity.IDENTIFIER_FIELDS:
                arrays[f"{prefix}_{field}"] = np.asarray(ids[field], dtype=str)
        np.savez_compressed(artifact_dir / "calibration_predictions.npz", **arrays)
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
