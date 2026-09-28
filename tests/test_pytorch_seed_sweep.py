"""Synthetic execution tests; no fixture score is historical performance evidence."""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from finrisk.modeling import pytorch_gru as gru
from finrisk.modeling import seed_sweep as sweep


def records():
    return [{"seed": seed, "status": "success", "average_precision": .02 + i*.001,
             "average_precision_over_prevalence": 2. + i*.1, "roc_auc": .7 + i*.01,
             "validation_rows": 10, "validation_positives": 1,
             "validation_identity_sha256": "i", "validation_labels_sha256": "y",
             "cohort_sha256": "c", "code_commit": "s", "environment": {"torch": "fixture"}}
            for i, seed in enumerate(sweep.SEEDS)]


def test_fixed_budget_summary_reports_all_seeds_and_never_selects_winner():
    report = sweep.summarize_runs(records())
    assert report["status"] == "complete" and report["selected_seed"] is None
    assert report["summary"]["average_precision"]["median"] == pytest.approx(.022)
    assert report["summary"]["average_precision"]["minimum"] == .02
    assert report["summary"]["average_precision"]["maximum"] == .024
    assert report["spread_is_confidence_interval"] is False


@pytest.mark.parametrize("change", ["missing", "duplicate", "other_seed"])
def test_seed_set_cannot_be_changed_after_seeing_results(change):
    rows = records()
    if change == "missing": rows.pop()
    elif change == "duplicate": rows[-1] = rows[0].copy()
    else: rows[-1]["seed"] = 999
    with pytest.raises(ValueError, match="predeclared"):
        sweep.summarize_runs(rows)


def test_failed_seed_is_preserved_and_blocks_survivor_summary():
    rows = records(); rows[0] = {"seed": sweep.SEEDS[0], "status": "failed"}
    report = sweep.summarize_runs(rows)
    assert report["status"] == "incomplete" and report["summary"] is None
    assert len(report["runs"]) == 5


@pytest.mark.parametrize("field", ["validation_identity_sha256", "validation_labels_sha256",
    "validation_rows", "validation_positives", "cohort_sha256", "code_commit", "environment"])
def test_seed_comparison_requires_same_population_and_environment(field):
    rows = records(); rows[-1][field] = "different"
    with pytest.raises(ValueError, match=field): sweep.summarize_runs(rows)


@pytest.mark.parametrize("seed", [-1, 2**32, True, 1.5, "42"])
def test_invalid_seed_fails_before_training(seed, monkeypatch):
    monkeypatch.setattr(gru, "_torch", lambda: pytest.fail("training must not start"))
    with pytest.raises(ValueError, match="seed"):
        gru.train_pytorch_gru(None, seed=seed)


@pytest.fixture
def frame():
    return pd.DataFrame({
        "cik": [f"{i+1:010d}" for i in range(10)] * 3,
        "adsh": [f"fixture-{i}" for i in range(30)],
        "filed": ["2019-06-01"]*10 + ["2021-06-01"]*10 + ["2023-06-01"]*10,
        "distress_12m": ([0, 1]*5)*3,
        "feature": np.linspace(-1., 1., 30),
    })


def fake_sequences(frame):
    # Controlled fixture preprocessing; the real GRU and optimizer execute.
    labels = frame["distress_12m"].to_numpy(dtype=np.float32)
    sequences = np.repeat(frame["feature"].to_numpy(dtype=np.float32)[:, None, None], 3, axis=1)
    dates = pd.to_datetime(frame["filed"]).to_numpy()
    masks = {"train": dates <= np.datetime64("2020-12-31"),
             "validation": (dates > np.datetime64("2020-12-31")) & (dates <= np.datetime64("2022-12-31")),
             "test": dates > np.datetime64("2022-12-31")}
    ids = {"cik": frame["cik"].to_numpy(), "adsh": frame["adsh"].to_numpy(),
           "filed": frame["filed"].to_numpy(),
           "observation_id": (frame["cik"]+":"+frame["adsh"]).to_numpy(),
           "event_id": np.full(len(frame), "unavailable")}
    return sequences, labels, masks, np.full(len(frame), 3), {"features": ["feature"]}, ids


def test_validation_only_poisoned_test_data_never_reaches_builder_or_calibration(frame, tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    seen = []
    def builder(partition):
        assert pd.to_datetime(partition["filed"]).max() <= pd.Timestamp("2022-12-31")
        seen.append(len(partition)); return fake_sequences(partition)
    monkeypatch.setattr(gru, "build_sequence_arrays", builder)
    monkeypatch.setattr(gru, "probability_evidence", lambda *a, **k: pytest.fail("no test calibration"))
    old_threads = torch.get_num_threads(); torch.set_num_threads(1)
    try:
        a = gru.train_pytorch_gru(frame, epochs=1, batch_size=10, validation_only=True,
                                  seed=42, calibration_out_dir=tmp_path/"a")
        changed = frame.copy(); changed.loc[20:, "distress_12m"] = np.nan
        changed.loc[20:, "feature"] = np.inf
        b = gru.train_pytorch_gru(changed, epochs=1, batch_size=10, validation_only=True,
                                  seed=42, calibration_out_dir=tmp_path/"b")
        c = gru.train_pytorch_gru(frame, epochs=1, batch_size=10, validation_only=True, seed=71)
    finally:
        torch.set_num_threads(old_threads)
    assert seen == [20, 20, 20] and a[1] == b[1] and a[3] == b[3]
    assert set(a[1]) == {"train", "validation"} and not a[2]["test_evaluated"]
    for key, value in a[0].state_dict().items():
        torch.testing.assert_close(value, b[0].state_dict()[key], rtol=0, atol=0)
    assert any(not torch.equal(v, c[0].state_dict()[k]) for k, v in a[0].state_dict().items())
    with np.load(tmp_path/"a/validation_predictions.npz", allow_pickle=False) as saved:
        assert not any("test" in name for name in saved.files)
        assert saved["validation_observation_id"].tolist() == [
            f"{i+1:010d}:fixture-{10+i}" for i in range(10)]
    assert not (tmp_path/"a/probability_calibrator.joblib").exists()


def test_default_seed_and_test_evaluation_remain_unchanged(frame, monkeypatch):
    torch = pytest.importorskip("torch")
    monkeypatch.setattr(gru, "build_sequence_arrays", fake_sequences)
    calls = []
    def calibration(yv, pv, yt, pt, **kwargs):
        calls.append((yv.copy(), yt.copy())); return {"fixture": True}
    monkeypatch.setattr(gru, "probability_evidence", calibration)
    previous = torch.get_num_threads(); torch.set_num_threads(1)
    try:
        default = gru.train_pytorch_gru(frame, epochs=1, batch_size=10)
        explicit = gru.train_pytorch_gru(frame, epochs=1, batch_size=10, seed=42, validation_only=False)
    finally: torch.set_num_threads(previous)
    assert default[1:] == explicit[1:] and len(calls) == 2
    for key, value in default[0].state_dict().items():
        torch.testing.assert_close(value, explicit[0].state_dict()[key], rtol=0, atol=0)


def test_sweep_hash_mismatch_prevents_training(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    path = tmp_path/"fixture.parquet"; path.write_bytes(b"not-the-frozen-cohort")
    monkeypatch.setattr(sweep, "train_pytorch_gru", lambda *a, **k: pytest.fail("must not train"))
    with pytest.raises(ValueError, match="SHA-256"):
        sweep.run_seed_sweep(path, tmp_path/"out")
    assert not (tmp_path/"out").exists()


def test_sweep_runs_every_seed_and_records_failures_without_test_data(frame, tmp_path, monkeypatch):
    pytest.importorskip("torch")
    path = tmp_path/"fixture.parquet"; path.write_bytes(b"synthetic")
    monkeypatch.setattr(sweep, "COHORT_SHA256", sweep.file_sha256(path))
    monkeypatch.setattr(sweep.pd, "read_parquet", lambda p: frame.copy())
    seen = []
    def runner(partition, *, seed, validation_only, calibration_out_dir, **kwargs):
        assert validation_only and len(partition) == 20
        seen.append(seed)
        if seed == 23: raise RuntimeError("synthetic seed failure")
        calibration_out_dir.mkdir(parents=True)
        np.savez_compressed(calibration_out_dir/"validation_predictions.npz",
                            validation_observation_id=np.array(["1:a", "2:b"]),
                            y_validation=np.array([0, 1]))
        class Model:
            def state_dict(self): return {}
        return Model(), {"validation": {"rows": 2, "positives": 1, "pr_auc": .6,
            "prevalence": .5, "roc_auc": .7}}, {"test_evaluated": False}, []
    monkeypatch.setattr(sweep, "train_pytorch_gru", runner)
    report = sweep.run_seed_sweep(path, tmp_path/"out")
    assert seen == list(sweep.SEEDS)
    assert report["status"] == "incomplete" and report["summary"] is None
    assert json.loads((tmp_path/"out/plan.json").read_text())["seed_42_previously_observed"]
    assert (tmp_path/"out/seed-23/result.json").exists()
