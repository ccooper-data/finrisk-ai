"""PR #138 review regressions. Synthetic tests are not performance evidence."""
import json
import warnings

import numpy as np
import pandas as pd
import pytest
from scipy.special import expit
from sklearn.exceptions import ConvergenceWarning

from finrisk.modeling import observation_identity as oid
from finrisk.modeling import probability_evidence as pe
from finrisk.modeling.calibration import ProbabilityCalibrator


def _ids(ciks):
    return oid.identifiers_from_frame(pd.DataFrame({
        "cik": ciks, "adsh": [f"a-{i}" for i in range(len(ciks))],
        "filed": ["2023-01-01"] * len(ciks),
    }))


def _report(**kwargs):
    return pe.probability_evidence([0, 0, 1, 1], [.1, .2, .7, .9],
                                   [0, 1, 0, 1], [.15, .3, .6, .85], **kwargs)


@pytest.mark.parametrize("value", ["0000895648", "895648", 895648, 895648.0,
                                    np.int64(895648), np.float64(895648), " 895648 "])
def test_cik_supported_representations_preserve_issuer(value):
    assert oid._cik_key(value) == "0000895648"
    assert oid._cik_key(value) != oid._cik_key(8956480)


@pytest.mark.parametrize("value", [None, pd.NA, np.nan, np.inf, -1, -895648.0,
                                    895648.5, True, np.bool_(True), "12x34",
                                    "895648.0", "8.95648e5", "", "00000000000",
                                    10000000000, "１２３４", "0000000000", 0])
def test_bad_ciks_are_explicitly_unavailable_not_guessed(value):
    assert oid._cik_key(value) == oid.UNAVAILABLE


def test_missing_issuer_never_creates_linked_event_or_cluster():
    ids = oid.identifiers_from_frame(pd.DataFrame({
        "adsh": ["a"], "filed": ["2020-01-01"], "next_distress_date": ["2020-06-01"]}))
    assert ids["event_id"].tolist() == [oid.UNAVAILABLE]
    assert ids["observation_id"].tolist() == [oid.UNAVAILABLE]
    c = oid.coverage(ids)
    assert c["unique_ciks"] == c["unique_linked_events"] == c["unique_observation_ids"] == 0


@pytest.mark.parametrize("ciks,blocker", [
    ([None] * 4, "test_ciks_unavailable"),
    ([1, 2, 3, None], "test_ciks_unavailable"),
    ([1] * 4, "fewer_than_two_distinct_test_ciks"),
])
def test_readiness_checks_entire_test_population(ciks, blocker):
    c = _report(test_identifiers=_ids(ciks))["identifier_coverage"]
    assert not c["supports_cluster_bootstrap"]
    assert blocker in c["cluster_bootstrap_readiness"]["blockers"]


def test_readiness_needs_no_validation_or_event_ids():
    r = _report(test_identifiers=_ids([1, 2, 1, 2]))["identifier_coverage"]
    assert r["validation"] == oid.UNAVAILABLE
    assert r["test"]["unique_linked_events"] == 0
    assert r["supports_cluster_bootstrap"] is True
    assert r["cluster_bootstrap_readiness"]["statistical_adequacy"] == "not_established"


def test_direct_invalid_keys_cannot_certify_readiness():
    ids = _ids([1, 2, 3, 4])
    ids["cik"][0] = "12x34"
    c = _report(test_identifiers=ids)["identifier_coverage"]
    assert c["test"]["ciks_invalid"] == 1
    assert c["test"]["unique_ciks"] == 3
    assert not c["supports_cluster_bootstrap"]
    assert "test_ciks_invalid" in c["cluster_bootstrap_readiness"]["blockers"]


def test_no_ids_or_empty_population_is_not_ready():
    assert not oid.cluster_bootstrap_readiness(None)["supports_cluster_bootstrap"]
    r = oid.cluster_bootstrap_readiness(_ids([]))
    assert "empty_test_population" in r["blockers"]
    assert not r["supports_cluster_bootstrap"]


def test_one_dimensional_and_nonragged_identifier_contract():
    ids = _ids([1, 2])
    ids["cik"] = np.array([["0000000001"], ["0000000002"]])
    with pytest.raises(ValueError, match="1D"):
        oid.coverage(ids)
    with pytest.raises(ValueError, match="ragged"):
        oid.build([1, 2], ["a"], ["2020-01-01"], [oid.UNAVAILABLE])


@pytest.mark.parametrize("y,p,status", [
    ([0, 0, 1, 1], [.1, .2, .8, .9], "unavailable_complete_separation"),
    ([1, 1, 0, 0], [.1, .2, .8, .9], "unavailable_complete_separation"),
    ([0, 0, 1, 1], [.1, .5, .5, .9], "unavailable_quasi_separation"),
    ([1, 1, 0, 0], [.1, .5, .5, .9], "unavailable_quasi_separation"),
    ([0, 1, 0, 1], [1e-16, 2e-16, 3e-16, 4e-16], "unavailable_constant_logit_after_clipping"),
])
def test_unidentified_joint_fit_never_reports_coefficients(y, p, status):
    d = pe.calibration_diagnostics(y, p)
    assert d["joint_recalibration"]["status"] == status
    assert not ({"slope", "intercept"} & d["joint_recalibration"].keys())
    assert d["status"] == "partial"
    assert d["average_precision_over_prevalence"] > 0
    assert d["calibration_in_the_large"]["status"] == "ok"
    json.dumps(d, allow_nan=False)


def test_constant_scores_keep_valid_lift_and_intercept_only_diagnostic():
    d = pe.calibration_diagnostics([0, 0, 0, 1], [.02] * 4)
    assert d["status"] == "unavailable_constant_predictions"
    assert "joint_recalibration" not in d
    assert d["average_precision_over_prevalence"] == 1
    assert d["calibration_in_the_large"]["status"] == "ok"


def test_iteration_exhaustion_is_partial_and_withholds_coefficients(monkeypatch):
    monkeypatch.setattr(pe, "MAX_JOINT_ITERATIONS", 1)
    d = pe.calibration_diagnostics([0, 1, 0, 1, 0, 1], [.05, .1, .2, .3, .4, .8])
    assert d["status"] == "partial"
    assert d["joint_recalibration"]["status"] == "unavailable_nonconverged"
    assert "slope" not in d["joint_recalibration"]
    assert d["calibration_in_the_large"]["status"] == "ok"


@pytest.mark.parametrize("behavior,status", [
    ("warning", "unavailable_nonconverged"),
    ("bad_score", "unavailable_score_equations"),
    ("nonfinite", "unavailable_nonfinite_coefficients"),
    ("exception", "unavailable_fit_failed"),
])
def test_diagnostic_solver_failures_are_statuses_not_model_failures(monkeypatch, behavior, status):
    class BadFit:
        def __init__(self, **kwargs):
            pass
        def fit(self, x, y):
            if behavior == "exception":
                raise RuntimeError("simulated solver failure")
            if behavior == "warning":
                warnings.warn("simulated failure", ConvergenceWarning)
            self.n_iter_ = np.array([1])
            self.intercept_ = np.array([np.nan if behavior == "nonfinite" else 0.])
            self.coef_ = np.array([[1.]])
            return self
    monkeypatch.setattr(pe, "LogisticRegression", BadFit)
    d = pe.calibration_diagnostics([0, 1, 0, 1, 0, 1], [.05, .1, .2, .3, .4, .8])
    assert d["joint_recalibration"]["status"] == status
    assert d["status"] == "partial"
    assert "slope" not in d["joint_recalibration"]
    # The calibration class is independent of the retrospective fit's solver.
    r = _report()
    assert np.isfinite(r["probability_quality"]["calibrated_brier"])


def test_finite_overlapping_fit_satisfies_both_score_equations():
    rng = np.random.default_rng(45)
    z = rng.normal(-4, 1, 6000)
    y = rng.binomial(1, expit(.3 + 1.1 * z))
    d = pe.calibration_diagnostics(y, expit(z))
    j = d["joint_recalibration"]
    assert d["status"] == j["status"] == "ok"
    residual = y - expit(j["intercept"] + j["slope"] * z)
    assert abs(residual.mean()) < pe.MEAN_SCORE_TOLERANCE
    assert abs(np.mean(residual * z)) < pe.MEAN_SCORE_TOLERANCE


def test_quantile_populated_bins_differ_from_intervals():
    q = pe._quantile_reliability_bins([0, 0, 1, 1], [.01, .01, .02, .02])
    assert q["realized_bins"] == 2
    assert q["interval_count"] == len(q["bins"])
    assert q["realized_bins"] == sum(x["rows"] > 0 for x in q["bins"])
    assert sorted(x["rows"] for x in q["bins"] if x["rows"]) == [2, 2]


def test_evidence_changes_cannot_mutate_calibrator_predictions_or_fit(tmp_path):
    yv, pv = [0, 0, 1, 1], [.1, .2, .7, .9]
    yt, pt = [0, 1, 0, 1], [.15, .3, .6, .85]
    cal = ProbabilityCalibrator("platt").fit(pv, yv)
    expected = cal.predict(pt)
    r = _report(test_identifiers=_ids([1, 2, 1, 2]), artifact_dir=tmp_path)
    with np.load(tmp_path / "calibration_predictions.npz", allow_pickle=False) as a:
        np.testing.assert_array_equal(a["p_test_calibrated"], expected)
        assert a["test_cik"].tolist() == ["0000000001", "0000000002"] * 2
    assert r["fit_fingerprint"] == cal.fit_fingerprint_
    assert set(r["reliability_bins"]) == {"raw", "calibrated"}
    assert json.loads((tmp_path / "probability_evidence.json").read_text()) == r


def test_tensorflow_disclosure_names_actual_checkpoint_metric():
    import ast
    import inspect
    from finrisk.modeling import tensorflow_gru as tfgru
    tree = ast.parse(inspect.getsource(tfgru.train_tensorflow_gru))
    labels = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, val in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "checkpoint_selection_metric":
                    labels.append(ast.literal_eval(val))
    assert labels == ["tf.keras.metrics.AUC(curve=PR); val_pr_auc; threshold approximation"]
