"""Small synthetic runner tests, not historical-performance evidence."""
import importlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import brier_score_loss
from threadpoolctl import threadpool_limits


@pytest.fixture
def cohort():
    rng = np.random.default_rng(42)
    records = []
    for year in (2019, 2020, 2021, 2023):
        for cik in range(80):
            # Different prevalence makes validation/test argument swaps detectable.
            label = int(cik % (5 if year == 2021 else 8) == 0)
            records.append({
                "cik": str(cik), "adsh": f"{cik}-{year}", "filed": f"{year}-06-01",
                "distress_12m": label, "current_ratio": 2-label+rng.normal(0, .4),
                "roa": .1-.2*label+rng.normal(0, .04),
            })
    return pd.DataFrame(records)


@pytest.mark.parametrize("module_name,train_name,metrics_position", [
    ("baseline", "train_logistic_baseline", 1),
    ("boosted_tree", "train_boosted_tree", 2),
    ("pytorch_gru", "train_pytorch_gru", 1),
    ("tensorflow_gru", "train_tensorflow_gru", 1),
])
def test_real_training_runner_calls_validation_only_calibration(
    module_name, train_name, metrics_position, cohort, tmp_path, monkeypatch,
):
    if module_name == "pytorch_gru":
        torch = pytest.importorskip("torch")
        previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)
    elif module_name == "tensorflow_gru":
        pytest.importorskip("tensorflow")
    module = importlib.import_module(f"finrisk.modeling.{module_name}")
    observed = []
    original = module.probability_evidence

    def spy(yv, pv, yt, pt, **kwargs):
        observed.append(tuple(np.asarray(v).copy() for v in (yv, pv, yt, pt)))
        return original(yv, pv, yt, pt, **kwargs)

    monkeypatch.setattr(module, "probability_evidence", spy)
    kwargs = {"epochs": 1, "batch_size": 128} if module_name.endswith("gru") else {}
    try:
        with threadpool_limits(limits=1):
            trained = getattr(module, train_name)(cohort, calibration_out_dir=tmp_path, **kwargs)
    finally:
        if module_name == "pytorch_gru":
            torch.set_num_threads(previous_threads)
    metrics = trained[metrics_position]
    assert len(observed) == 1
    yv, pv, yt, pt = observed[0]
    assert len(yv) == metrics["validation"]["rows"] == 80
    assert len(yt) == metrics["test"]["rows"] == 80
    assert yv.sum() == 16 and yt.sum() == 10
    # Derive expected order from each runner's actual input partition convention.
    if module_name.endswith("gru"):
        _, labels, masks, _, _, _ = module.build_sequence_arrays(cohort)
        expected_validation, expected_test = labels[masks["validation"]], labels[masks["test"]]
    else:
        _, validation, test = module.temporal_split(cohort)
        expected_validation, expected_test = validation["distress_12m"], test["distress_12m"]
    np.testing.assert_array_equal(yv, expected_validation)
    np.testing.assert_array_equal(yt, expected_test)
    report = metrics["test"]["calibration"]
    assert report["calibration_method"] == "platt"
    assert report["probability_quality"]["raw_brier"] == pytest.approx(metrics["test"]["brier"])
    with np.load(tmp_path / "calibration_predictions.npz") as saved:
        np.testing.assert_array_equal(saved["p_test"], pt)
        np.testing.assert_array_equal(saved["p_validation"], pv)
        replay = joblib.load(tmp_path / "probability_calibrator.joblib").predict(pt)
        assert brier_score_loss(yt, replay) == pytest.approx(report["probability_quality"]["calibrated_brier"])
    assert json.loads((tmp_path / "probability_evidence.json").read_text()) == report


@pytest.mark.parametrize("module_name,train_name,run_name,metric_file", [
    ("baseline", "train_logistic_baseline", "run_baseline", "baseline_metrics.json"),
    ("boosted_tree", "train_boosted_tree", "run_boosted_tree", "boosted_tree_metrics.json"),
    ("pytorch_gru", "train_pytorch_gru", "run_pytorch_gru", "pytorch_gru_metrics.json"),
    ("tensorflow_gru", "train_tensorflow_gru", "run_tensorflow_gru", "tensorflow_gru_metrics.json"),
])
def test_run_wrapper_passes_artifact_destination_and_records_input_hash(
    module_name, train_name, run_name, metric_file, cohort, tmp_path, monkeypatch,
):
    module = importlib.import_module(f"finrisk.modeling.{module_name}")
    path = tmp_path / "cohort.parquet"
    path.write_bytes(b"synthetic-input-placeholder")
    out_dir = tmp_path / "out"
    seen = []

    class FakeModel:
        def state_dict(self):
            return {}
        def save(self, path):
            Path(path).write_text("synthetic-model-placeholder")

    def fake_train(frame, *, calibration_out_dir):
        assert frame is cohort
        seen.append(calibration_out_dir)
        if module_name == "baseline":
            return {"fixture": True}, {}, {}
        if module_name == "boosted_tree":
            return {"fixture": True}, {"fixture": True}, {}, {}
        return FakeModel(), {}, {}, []

    monkeypatch.setattr(module, train_name, fake_train)
    monkeypatch.setattr(module.pd, "read_parquet", lambda _: cohort)
    if module_name == "pytorch_gru":
        class FakeTorch:
            @staticmethod
            def save(state, path):
                Path(path).write_text("synthetic-model-placeholder")
        monkeypatch.setattr(module, "_torch", lambda: (FakeTorch(), None))
    result = getattr(module, run_name)(path, out_dir)
    assert seen == [out_dir]
    assert len(result["input"]["cohort_sha256"]) == 64
    assert result["input"]["upstream_source_lineage"] == "not_verified_by_model_runner"
    assert json.loads((out_dir / metric_file).read_text()) == result
