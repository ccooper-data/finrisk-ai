import hashlib
import json

import joblib
import numpy as np
import pytest
from sklearn.metrics import brier_score_loss

import finrisk.modeling.probability_evidence as evidence_module
from finrisk.modeling.probability_evidence import cohort_input_evidence, probability_evidence


@pytest.mark.parametrize("method", ["platt", "isotonic"])
def test_calibration_artifacts_replay_and_report_probability_quality(tmp_path, method):
    yv = np.array([0] * 90 + [1] * 10)
    pv = np.array([.20] * 90 + [.80] * 10)
    yt = yv.copy()
    pt = np.array([.25] * 90 + [.75] * 10)
    report = probability_evidence(yv, pv, yt, pt, method, artifact_dir=tmp_path)
    assert report["fit_partition"] == "validation"
    assert report["evaluation_partition"] == "test"
    assert report["probability_quality"]["calibrated_brier"] < report["probability_quality"]["raw_brier"]
    persisted = joblib.load(tmp_path / "probability_calibrator.joblib")
    with np.load(tmp_path / "calibration_predictions.npz") as saved:
        np.testing.assert_array_equal(saved["y_validation"], yv)
        np.testing.assert_array_equal(saved["p_validation"], pv)
        np.testing.assert_allclose(persisted.predict(pt), saved["p_test_calibrated"])
        assert brier_score_loss(yt, saved["p_test_calibrated"]) == pytest.approx(
            report["probability_quality"]["calibrated_brier"]
        )
    assert json.loads((tmp_path / "probability_evidence.json").read_text()) == report
    for series in report["reliability_bins"].values():
        assert sum(x["rows"] for x in series) == len(yt)


@pytest.mark.parametrize("method", ["platt", "isotonic"])
def test_changing_test_labels_cannot_change_fitted_calibrator(tmp_path, method, monkeypatch):
    yv = np.array([0, 0, 0, 1, 1, 1])
    pv = np.array([.1, .2, .3, .7, .8, .9])
    pt = np.array([.15, .25, .35, .65, .75, .85])
    calls = []
    original_fit = evidence_module.ProbabilityCalibrator.fit

    def spy_fit(self, p, y):
        calls.append((np.asarray(p).copy(), np.asarray(y).copy()))
        return original_fit(self, p, y)

    monkeypatch.setattr(evidence_module.ProbabilityCalibrator, "fit", spy_fit)
    first = probability_evidence(yv, pv, yv, pt, method, artifact_dir=tmp_path / "a")
    second = probability_evidence(yv, pv, 1-yv, pt, method, artifact_dir=tmp_path / "b")
    assert len(calls) == 2
    for actual_p, actual_y in calls:
        np.testing.assert_array_equal(actual_p, pv)
        np.testing.assert_array_equal(actual_y, yv)
    a = joblib.load(tmp_path / "a/probability_calibrator.joblib")
    b = joblib.load(tmp_path / "b/probability_calibrator.joblib")
    np.testing.assert_array_equal(a.predict(pt), b.predict(pt))
    assert first["probability_quality"]["calibrated_brier"] != second["probability_quality"]["calibrated_brier"]


def test_baseline_uses_validation_prevalence_not_test_prevalence():
    yv = [0, 0, 0, 1]
    yt = [0, 1, 1, 1]
    report = probability_evidence(yv, [.1, .2, .3, .8], yt, [.1, .2, .7, .8])
    assert report["baseline_fit_partition"] == "validation"
    assert report["baseline_probability"] == .25
    assert report["test_prevalence"] == .75
    quality = report["probability_quality"]
    assert quality["base_rate_brier"] == pytest.approx(brier_score_loss(yt, [.25]*4))
    assert quality["oracle_test_base_rate_brier"] == pytest.approx(brier_score_loss(yt, [.75]*4))
    assert quality["base_rate_brier"] > quality["oracle_test_base_rate_brier"]


@pytest.mark.parametrize("labels,probabilities", [
    ([], []), ([0, 1], [.5]), ([[0, 1]], [[.2, .8]]),
    ([0, .5], [.2, .8]), ([0, np.nan], [.2, .8]),
    ([0, 1], [np.nan, .8]), ([0, 1], [np.inf, .8]),
    ([0, 1], [-.1, .8]), ([0, 1], [.2, 1.1]),
])
@pytest.mark.parametrize("partition", ["validation", "test"])
def test_invalid_inputs_fail_before_fitting_or_writing(tmp_path, monkeypatch, labels, probabilities, partition):
    def forbidden_fit(*args, **kwargs):
        raise AssertionError("invalid input reached fitting")
    monkeypatch.setattr(evidence_module.ProbabilityCalibrator, "fit", forbidden_fit)
    args = [labels, probabilities, [0, 1], [.1, .9]] if partition == "validation" else [[0, 1], [.1, .9], labels, probabilities]
    with pytest.raises(ValueError, match=partition):
        probability_evidence(*args, artifact_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_single_class_validation_fails_closed():
    with pytest.raises(ValueError, match="both outcome classes"):
        probability_evidence([0, 0], [.1, .2], [0, 1], [.1, .9])


def test_single_class_test_has_explicit_undefined_ranking_and_finite_brier():
    report = probability_evidence([0, 1], [.1, .9], [0, 0], [0., 1.])
    assert report["ranking_status"] == "undefined_single_class_test"
    assert all(value is None for value in report["ranking"].values())
    assert np.isfinite(report["probability_quality"]["calibrated_brier"])
    json.dumps(report, allow_nan=False)


def test_input_fingerprint_is_exact_and_not_lineage_approval(tmp_path, monkeypatch):
    path = tmp_path / "cohort.parquet"
    path.write_bytes(b"fixture-cohort-bytes")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    report = cohort_input_evidence(path)
    assert report["cohort_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert report["code_commit"] == "a" * 40
    assert report["upstream_source_lineage"] == "not_verified_by_model_runner"
    path.write_bytes(b"changed")
    assert cohort_input_evidence(path)["cohort_sha256"] != report["cohort_sha256"]


# --- Leakage verified behaviourally, not by a label ----------------------------
#
# "fit_partition": "validation" is a string literal: it would still read
# "validation" if the calibrator were fit on test. These check the property and
# the wiring, and a deliberately leaking calibrator must be rejected.

import numpy as _np
import pytest as _pytest
from finrisk.modeling.calibration import ProbabilityCalibrator as _Calibrator
from finrisk.modeling.calibration import array_fingerprint as _fingerprint
from finrisk.modeling.probability_evidence import probability_evidence as _evidence


def _leak_split(n, positives, seed, shift=1.25):
    rng = _np.random.default_rng(seed)
    y = _np.zeros(n, dtype=int)
    y[rng.choice(n, positives, replace=False)] = 1
    return y, 1 / (1 + _np.exp(-(rng.normal(0, 1, n) + y * shift)))


_YV, _PV = _leak_split(4000, 120, 11)
_YT, _PT = _leak_split(6000, 180, 12)


def test_test_labels_cannot_change_the_calibrator():
    """Same scores, different test labels -> identical fit. The property, not a label."""
    a = _evidence(_YV, _PV, _YT, _PT)
    b = _evidence(_YV, _PV, 1 - _YT, _PT)
    assert a["fit_fingerprint"] == b["fit_fingerprint"]
    assert a["probability_quality"]["calibrated_brier"] != b["probability_quality"]["calibrated_brier"]


def test_calibrator_receives_only_validation_arrays():
    seen = {}

    class Spy(_Calibrator):
        def fit(self, p, y):
            seen["fingerprint"] = _fingerprint(p, y)
            return super().fit(p, y)

    _evidence(_YV, _PV, _YT, _PT, _calibrator_factory=Spy)
    assert seen["fingerprint"] == _fingerprint(_PV, _YV)
    assert seen["fingerprint"] != _fingerprint(_PT, _YT)


def test_a_calibrator_fit_on_test_is_rejected():
    class FitsOnTest(_Calibrator):
        def fit(self, p, y):
            return super().fit(_PT, _YT)

    with _pytest.raises(ValueError, match="do not match the validation partition"):
        _evidence(_YV, _PV, _YT, _PT, _calibrator_factory=FitsOnTest)


def test_a_calibrator_fit_on_validation_plus_test_is_rejected():
    class FitsOnBoth(_Calibrator):
        def fit(self, p, y):
            return super().fit(_np.r_[p, _PT], _np.r_[y, _YT])

    with _pytest.raises(ValueError, match="do not match the validation partition"):
        _evidence(_YV, _PV, _YT, _PT, _calibrator_factory=FitsOnBoth)


def test_a_calibrator_that_hides_its_fit_inputs_is_rejected():
    class Silent(_Calibrator):
        def fit(self, p, y):
            super().fit(p, y)
            self.fit_fingerprint_ = None
            return self

    with _pytest.raises(ValueError, match="did not record its fit inputs"):
        _evidence(_YV, _PV, _YT, _PT, _calibrator_factory=Silent)


def test_identical_validation_and_test_partitions_are_rejected():
    with _pytest.raises(ValueError, match="fit on the test partition"):
        _evidence(_YT, _PT, _YT, _PT)


def test_fingerprint_is_sensitive_to_order_and_labels():
    assert _fingerprint(_PV, _YV) != _fingerprint(_PV[::-1], _YV[::-1])
    assert _fingerprint(_PV, _YV) != _fingerprint(_PV, 1 - _YV)


# --- Ranking invariant ---------------------------------------------------------

def test_platt_preserves_ranking_bit_identically():
    k = _evidence(_YV, _PV, _YT, _PT, "platt")["ranking"]
    assert k["calibrated_roc_auc"] == _pytest.approx(k["raw_roc_auc"], abs=1e-12)
    assert k["calibrated_pr_auc"] == _pytest.approx(k["raw_pr_auc"], abs=1e-12)


def test_isotonic_may_lose_ranking_but_never_gain_it():
    k = _evidence(_YV, _PV, _YT, _PT, "isotonic")["ranking"]
    assert k["calibrated_roc_auc"] <= k["raw_roc_auc"] + 1e-12


def test_ranking_drift_under_platt_raises_instead_of_being_reported():
    class Shuffles(_Calibrator):
        def predict(self, p):
            return _np.asarray(super().predict(p), dtype=float)[::-1]

    with _pytest.raises(ValueError, match="altered ROC-AUC"):
        _evidence(_YV, _PV, _YT, _PT, "platt", _calibrator_factory=Shuffles)
