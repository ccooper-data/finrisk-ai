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
