from __future__ import annotations
import numpy as np
import pytest
from finrisk.modeling import observation_identity as oid
from finrisk.modeling.probability_evidence import (
    _quantile_reliability_bins, calibration_diagnostics, probability_evidence,
)


def _split(n, positives, seed, shift=1.3):
    rng = np.random.default_rng(seed)
    y = np.zeros(n, dtype=int)
    y[rng.choice(n, positives, replace=False)] = 1
    return y, 1 / (1 + np.exp(-(rng.normal(0, 1, n) + y * shift)))


YV, PV = _split(6000, 60, 21)
YT, PT = _split(9000, 120, 22)


# --- Quantile bins -------------------------------------------------------------

def test_quantile_bins_are_reported_alongside_the_fixed_width_field():
    report = probability_evidence(YV, PV, YT, PT)
    assert set(report["reliability_bins"]) == {"raw", "calibrated"}   # unchanged shape
    assert report["quantile_reliability_bins"]["calibrated"]["strategy"] == "quantile"


def test_quantile_bin_boundaries_come_from_predictions_not_labels():
    """Flipping test labels must change event rates only."""
    a = probability_evidence(YV, PV, YT, PT)
    b = probability_evidence(YV, PV, 1 - YT, PT)
    qa = a["quantile_reliability_bins"]["calibrated"]
    qb = b["quantile_reliability_bins"]["calibrated"]
    assert qa["boundaries"] == qb["boundaries"]
    assert [x["rows"] for x in qa["bins"]] == [x["rows"] for x in qb["bins"]]
    assert [x["mean_probability"] for x in qa["bins"]] == [x["mean_probability"] for x in qb["bins"]]
    assert [x["event_rate"] for x in qa["bins"]] != [x["event_rate"] for x in qb["bins"]]
    assert a["fit_fingerprint"] == b["fit_fingerprint"]


def test_tied_probabilities_are_never_split_to_manufacture_bins():
    p = np.repeat([0.01, 0.02], 500)
    y = np.zeros(1000, dtype=int); y[:5] = 1
    result = _quantile_reliability_bins(y, p, bins=10)
    populated = [b for b in result["bins"] if b["rows"]]
    assert result["realized_bins"] < 10
    assert sorted(b["rows"] for b in populated) == [500, 500]
    assert all(len(np.unique(p[np.isclose(p, b["mean_probability"])])) == 1 for b in populated)


def test_constant_predictions_report_a_status_instead_of_inventing_bins():
    result = _quantile_reliability_bins(np.array([0, 1, 0, 1]), np.full(4, 0.25))
    assert result["status"] == "degenerate_constant_predictions"
    assert result["realized_bins"] == 1


def test_quantile_bins_account_for_every_row():
    q = probability_evidence(YV, PV, YT, PT)["quantile_reliability_bins"]["calibrated"]
    assert sum(b["rows"] for b in q["bins"]) == len(YT)
    assert sum(b["positives"] for b in q["bins"]) == int(YT.sum())


# --- Retrospective diagnostics -------------------------------------------------

def test_joint_and_intercept_only_terms_are_reported_separately():
    d = probability_evidence(YV, PV, YT, PT)["test_calibration_diagnostics"]
    assert d["status"] == "ok"
    joint = d["joint_recalibration"]
    citl = d["calibration_in_the_large"]
    assert {"intercept", "slope", "converged", "iterations", "note"} <= set(joint)
    assert citl["slope_fixed_at"] == 1.0
    # The joint intercept is not the standalone calibration-in-the-large term.
    assert joint["intercept"] != citl["intercept_only_offset"]


def test_diagnostics_are_flagged_as_test_label_derived_and_unused_for_prediction():
    d = probability_evidence(YV, PV, YT, PT)["test_calibration_diagnostics"]
    assert d["uses_test_labels"] is True
    assert d["used_for_prediction"] is False
    assert d["used_for_model_selection"] is False
    assert d["logit_clip"][0] > 0 and d["logit_clip"][1] < 1


def test_average_precision_over_prevalence_is_reported_unambiguously():
    d = probability_evidence(YV, PV, YT, PT)["test_calibration_diagnostics"]
    assert d["average_precision_over_prevalence"] == pytest.approx(
        d["average_precision"] / d["prevalence"])


def test_computing_diagnostics_does_not_touch_the_calibrator_or_its_predictions():
    from finrisk.modeling.calibration import ProbabilityCalibrator
    cal = ProbabilityCalibrator("platt").fit(PV, YV)
    before_fingerprint = cal.fit_fingerprint_
    before = cal.predict(PT).copy()
    calibration_diagnostics(YT, before)
    np.testing.assert_array_equal(cal.predict(PT), before)
    assert cal.fit_fingerprint_ == before_fingerprint


def test_single_class_test_yields_an_explicit_unavailable_status():
    d = calibration_diagnostics(np.zeros(50, dtype=int), np.linspace(0.01, 0.2, 50))
    assert d["status"] == "unavailable_single_class_test"
    assert "joint_recalibration" not in d


def test_constant_scores_yield_an_explicit_unavailable_status():
    y = np.zeros(50, dtype=int); y[:5] = 1
    d = calibration_diagnostics(y, np.full(50, 0.02))
    assert d["status"] == "unavailable_constant_predictions"
    assert "joint_recalibration" not in d


# --- Identifier + disclosure plumbing ------------------------------------------

def _ids(n, seed):
    rng = np.random.default_rng(seed)
    cik = np.array([str(int(c)).zfill(10) for c in rng.integers(1, 40, n)], dtype=object)
    adsh = np.array([f"a-{i}" for i in range(n)], dtype=object)
    filed = np.array(["2023-01-31"] * n, dtype=object)
    return oid.build(cik, adsh, filed, np.full(n, oid.UNAVAILABLE, dtype=object))


def test_identifier_coverage_marks_cluster_bootstrap_support():
    without = probability_evidence(YV, PV, YT, PT)["identifier_coverage"]
    assert without["supports_cluster_bootstrap"] is False
    assert without["test"] == "unavailable"
    with_ids = probability_evidence(
        YV, PV, YT, PT,
        validation_identifiers=_ids(len(YV), 1), test_identifiers=_ids(len(YT), 2),
    )["identifier_coverage"]
    assert with_ids["supports_cluster_bootstrap"] is True
    assert with_ids["test"]["rows"] == len(YT)
    assert 0 < with_ids["test"]["unique_ciks"] < len(YT)


def test_misaligned_identifiers_are_rejected():
    with pytest.raises(ValueError, match="identifiers for"):
        probability_evidence(YV, PV, YT, PT, test_identifiers=_ids(len(YT) - 1, 5))


def test_identifiers_are_persisted_beside_the_predictions(tmp_path):
    probability_evidence(
        YV, PV, YT, PT, artifact_dir=tmp_path,
        validation_identifiers=_ids(len(YV), 1), test_identifiers=_ids(len(YT), 2),
    )
    saved = np.load(tmp_path / "calibration_predictions.npz")
    for field in oid.IDENTIFIER_FIELDS:
        assert len(saved[f"test_{field}"]) == len(YT)
        assert len(saved[f"validation_{field}"]) == len(YV)
    assert saved["test_cik"][0].startswith("0")


def test_validation_reuse_is_machine_readable_and_defaults_conservatively():
    default = probability_evidence(YV, PV, YT, PT)["validation_reuse"]
    assert default["calibration_uses_validation"] is True
    assert default["independent_calibration_holdout"] is False
    assert default["optimism_quantified"] is False
    assert default["checkpoint_selection_uses_validation"] == "unavailable"
    declared = probability_evidence(YV, PV, YT, PT, validation_reuse={
        "checkpoint_selection_uses_validation": True,
        "calibration_uses_validation": True,
        "independent_calibration_holdout": False,
        "optimism_quantified": False,
    })["validation_reuse"]
    assert declared["checkpoint_selection_uses_validation"] is True


def test_joint_fit_reaches_a_stationary_point_not_just_a_default_tolerance():
    """Solver-independent convergence check via the two score equations.

    sklearn's default tol=1e-4 stopped ~0.004 short on the real cohort geometry,
    where the intercept is evaluated about five logits outside the data. Checking
    the score equations pins convergence without pinning the solver.
    """
    from finrisk.modeling.probability_evidence import LOGIT_CLIP
    d = probability_evidence(YV, PV, YT, PT)["test_calibration_diagnostics"]
    a = d["joint_recalibration"]["intercept"]
    b = d["joint_recalibration"]["slope"]
    lo, hi = LOGIT_CLIP
    q = np.clip(PT, lo, hi)
    z = np.log(q / (1 - q))
    # calibrated scores, refit through the joint model
    from finrisk.modeling.calibration import ProbabilityCalibrator
    pc = ProbabilityCalibrator("platt").fit(PV, YV).predict(PT)
    qc = np.clip(pc, lo, hi)
    zc = np.log(qc / (1 - qc))
    fitted = 1 / (1 + np.exp(-(a + b * zc)))
    residual = YT - fitted
    assert abs(residual.sum()) < 1e-4
    assert abs((residual * zc).sum()) < 1e-4
    assert d["joint_recalibration"]["converged"] is True


def test_intercept_only_offset_solves_its_own_score_equation():
    d = probability_evidence(YV, PV, YT, PT)["test_calibration_diagnostics"]
    offset = d["calibration_in_the_large"]["intercept_only_offset"]
    from finrisk.modeling.calibration import ProbabilityCalibrator
    from finrisk.modeling.probability_evidence import _logit
    pc = ProbabilityCalibrator("platt").fit(PV, YV).predict(PT)
    fitted = 1 / (1 + np.exp(-(_logit(pc) + offset)))
    assert abs((YT - fitted).sum()) < 1e-6
