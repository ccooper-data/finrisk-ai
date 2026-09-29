"""Persisted sweep evidence tests with synthetic training and file loading.

The sweep, shared runtime recorder, JSON serialization and summary are real.
Only the heavyweight trainer, parquet loading and PyTorch runtime are fixtures;
these tests do not train historical models or assert historical performance.
They run even in development-only CI without installing an ML framework.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from finrisk.modeling import seed_sweep as sweep
from finrisk.modeling.run_environment import SEQUENCE_PREPROCESSING_VERSION


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    state = {"threads": 2, "failed_seed": None, "drift_after_seed": None}
    calls = []
    torch = ModuleType("torch")
    torch.__version__ = "synthetic-torch"
    torch.get_num_threads = lambda: state["threads"]
    torch.are_deterministic_algorithms_enabled = lambda: False
    torch.cuda = SimpleNamespace(is_available=lambda: False)
    torch.save = lambda value, path: Path(path).write_bytes(b"synthetic-checkpoint")
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "synthetic-run")
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    path = tmp_path / "cohort.parquet"
    path.write_bytes(b"synthetic-cohort-not-performance-evidence")
    monkeypatch.setattr(sweep, "COHORT_SHA256", sweep.file_sha256(path))
    frame = pd.DataFrame({
        "filed": ["2019-01-01", "2021-01-01", "2022-01-01", "2023-01-01"],
        "distress_12m": [0, 0, 1, np.nan],
        "assets": [1.0, 2.0, 3.0, np.inf],
    })
    monkeypatch.setattr(sweep.pd, "read_parquet", lambda _: frame.copy())

    def train(partition, *, seed, validation_only, calibration_out_dir, **kwargs):
        assert validation_only is True
        assert kwargs == {"epochs": 40, "batch_size": 2048}
        assert pd.to_datetime(partition["filed"]).max() <= pd.Timestamp("2022-12-31")
        assert len(partition) == 3
        assert np.isfinite(partition["assets"]).all()
        assert partition["distress_12m"].notna().all()
        calls.append(seed)
        if seed == state["failed_seed"]:
            raise RuntimeError("synthetic failure to test retained evidence")
        calibration_out_dir.mkdir(parents=True)
        np.savez_compressed(
            calibration_out_dir / "validation_predictions.npz",
            validation_observation_id=np.array(["0000000001:a", "0000000002:b"]),
            y_validation=np.array([0, 1]), p_validation=np.array([0.1, 0.8]),
        )
        if seed == state["drift_after_seed"]:
            state["threads"] = 3
        return (SimpleNamespace(state_dict=lambda: {}),
                {"validation": {"rows": 2, "positives": 1, "prevalence": 0.5,
                                "pr_auc": 1.0, "roc_auc": 1.0}},
                {"test_evaluated": False}, [])

    monkeypatch.setattr(sweep, "train_pytorch_gru", train)
    return SimpleNamespace(path=path, output=tmp_path / "out", state=state, calls=calls)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("failed_seed", [None, 23])
def test_shared_environment_persists_in_plan_all_seed_results_and_summary(experiment, failed_seed):
    experiment.state["failed_seed"] = failed_seed
    report = sweep.run_seed_sweep(experiment.path, experiment.output)
    plan = _read(experiment.output / "plan.json")
    summary = _read(experiment.output / "summary.json")
    assert summary == report
    assert experiment.calls == list(sweep.SEEDS)
    assert summary["test_evaluated"] is False
    assert summary["selected_seed"] is None
    assert summary["status"] == ("complete" if failed_seed is None else "incomplete")
    if failed_seed is not None:
        assert summary["summary"] is None
    environment = plan["environment"]
    assert environment["sequence_preprocessing_version"] == SEQUENCE_PREPROCESSING_VERSION == 2
    runtime = environment["runtime"]
    assert runtime["sequence_preprocessing_version"] == 2
    assert runtime["github_sha"] == "a" * 40
    assert runtime["github_run_id"] == "synthetic-run"
    assert runtime["pythonhashseed"] == "0"
    assert runtime["torch"]["cuda_available"] is False
    assert "tensorflow" in runtime
    for field in ("python", "platform", "numpy", "pandas", "scikit_learn"):
        assert isinstance(environment[field], str)
        assert environment[field] == runtime[field]
    # Keep the old flat schema, including the type of the torch version field.
    assert environment["torch"] == runtime["torch"]["version"] == "synthetic-torch"
    assert isinstance(environment["torch"], str)
    assert environment["torch_threads"] == runtime["torch"]["threads"] == 2
    assert environment["deterministic_algorithms"] is False
    for row in summary["runs"]:
        saved = _read(experiment.output / f"seed-{row['seed']}" / "result.json")
        assert saved == row
        assert saved["environment"] == environment
        assert saved["environment"]["runtime"]["sequence_preprocessing_version"] == 2
        assert saved["status"] == ("failed" if row["seed"] == failed_seed else "success")


def test_actual_recorder_is_called_for_plan_and_again_before_every_seed(experiment, monkeypatch):
    original = sweep.run_environment
    calls = []

    def recorder(*, sequence_preprocessing=False):
        calls.append(sequence_preprocessing)
        result = original(sequence_preprocessing=sequence_preprocessing)
        result["integration_probe"] = "observed-shared-recorder"
        return result

    monkeypatch.setattr(sweep, "run_environment", recorder)
    report = sweep.run_seed_sweep(experiment.path, experiment.output)
    assert calls == [True] * (1 + len(sweep.SEEDS))
    plan = _read(experiment.output / "plan.json")
    assert plan["environment"]["runtime"]["integration_probe"] == "observed-shared-recorder"
    for row in report["runs"]:
        assert row["environment"]["runtime"]["integration_probe"] == "observed-shared-recorder"


def test_runtime_drift_between_seeds_is_observed_not_hidden_by_plan_copy(experiment):
    experiment.state["drift_after_seed"] = sweep.SEEDS[0]
    with pytest.raises(ValueError, match="environment"):
        sweep.run_seed_sweep(experiment.path, experiment.output)
    assert experiment.calls == list(sweep.SEEDS)
    first = _read(experiment.output / f"seed-{sweep.SEEDS[0]}" / "result.json")
    second = _read(experiment.output / f"seed-{sweep.SEEDS[1]}" / "result.json")
    assert first["environment"]["torch_threads"] == 2
    assert second["environment"]["torch_threads"] == 3
    assert not (experiment.output / "summary.json").exists()
    assert all((experiment.output / f"seed-{seed}" / "result.json").is_file()
               for seed in sweep.SEEDS)


def test_hash_mismatch_still_prevents_training_and_output(experiment):
    experiment.path.write_bytes(b"wrong-frozen-input")
    with pytest.raises(ValueError, match="SHA-256"):
        sweep.run_seed_sweep(experiment.path, experiment.output)
    assert experiment.calls == []
    assert not experiment.output.exists()


def test_existing_output_is_not_overwritten(experiment):
    experiment.output.mkdir()
    existing = experiment.output / "prior-evidence.txt"
    existing.write_text("preserve")
    with pytest.raises(FileExistsError):
        sweep.run_seed_sweep(experiment.path, experiment.output)
    assert existing.read_text() == "preserve"
    assert experiment.calls == []
