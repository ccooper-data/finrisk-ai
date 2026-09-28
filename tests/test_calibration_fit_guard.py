"""Fit-guard regressions must execute the helper, not inspect metadata labels."""
import joblib
import numpy as np
import pytest

from finrisk.modeling.calibration import ProbabilityCalibrator as _Calibrator
from finrisk.modeling.calibration import array_fingerprint as _fingerprint
from finrisk.modeling.probability_evidence import probability_evidence

_YV = np.array([0, 0, 0, 1, 1, 1])
_PV = np.array([.1, .2, .3, .7, .8, .9])
_YT = np.array([0, 0, 1, 0, 1])
_PT = np.array([.15, .25, .65, .35, .85])


@pytest.mark.parametrize("method", ["platt", "isotonic"])
def test_recorded_fit_fingerprint_survives_artifact_replay(tmp_path, method):
    report = probability_evidence(_YV, _PV, _YT, _PT, method, artifact_dir=tmp_path)
    saved = joblib.load(tmp_path / "probability_calibrator.joblib")
    with np.load(tmp_path / "calibration_predictions.npz") as arrays:
        expected = _fingerprint(arrays["p_validation"], arrays["y_validation"])
        assert saved.fit_fingerprint_ == report["fit_fingerprint"] == expected
        assert expected != _fingerprint(arrays["p_test"], arrays["y_test"])


@pytest.mark.parametrize("fault", ["test", "combined", "missing", "identical"])
def test_fit_guard_rejects_before_prediction_or_artifact_write(tmp_path, fault):
    class InvalidFit(_Calibrator):
        def fit(self, p, y):
            if fault == "test":
                return super().fit(_PT, _YT)
            if fault == "combined":
                return super().fit(np.r_[p, _PT], np.r_[y, _YT])
            super().fit(p, y)
            if fault == "missing":
                self.fit_fingerprint_ = None
            return self

        def predict(self, p):
            raise AssertionError("fit guard allowed invalid provenance to reach prediction")

    out = tmp_path / "must_not_exist"
    yv, pv = (_YT, _PT) if fault == "identical" else (_YV, _PV)
    with pytest.raises(ValueError, match="fit inputs|test partition"):
        probability_evidence(
            yv, pv, _YT, _PT, artifact_dir=out, _calibrator_factory=InvalidFit,
        )
    assert not out.exists()
