"""Fixed-budget, validation-only PyTorch GRU seed sensitivity experiment."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from finrisk.modeling.baseline import TemporalSplit
from finrisk.modeling.pytorch_gru import train_pytorch_gru
from finrisk.modeling.run_environment import run_environment

SEEDS = (11, 23, 42, 71, 101)
COHORT_SHA256 = "c759d1223f5c7b6454ac17b31943cff8aa4b0f260a3097fe7b5b35dd50d24491"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def summarize_runs(runs: list[dict]) -> dict:
    """Do not select a seed or hide failed runs; summaries require all five."""
    if len(runs) != len(SEEDS) or sorted(r["seed"] for r in runs) != sorted(SEEDS):
        raise ValueError("exactly one record per predeclared seed is required")
    result = {"seeds": list(SEEDS), "runs": runs, "selected_seed": None,
              "test_evaluated": False, "spread_is_confidence_interval": False}
    if any(r["status"] != "success" for r in runs):
        return {**result, "status": "incomplete", "summary": None}
    for field in ("validation_identity_sha256", "validation_labels_sha256", "validation_rows",
                  "validation_positives", "cohort_sha256", "code_commit", "environment"):
        values = [r[field] for r in runs]
        if any(value != values[0] for value in values[1:]):
            raise ValueError(f"seed runs disagree on {field}")
    summary = {}
    for field in ("average_precision", "average_precision_over_prevalence", "roc_auc"):
        values = np.asarray([r[field] for r in runs], dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"nonfinite {field}")
        q1, median, q3 = np.quantile(values, [.25, .5, .75])
        summary[field] = {"median": float(median), "minimum": float(values.min()),
                          "maximum": float(values.max()), "q1": float(q1), "q3": float(q3)}
    return {**result, "status": "complete", "summary": summary,
            "interpretation": "checkpoint-selected validation sensitivity, not held-out performance"}


def _sweep_environment() -> dict:
    """Capture shared runtime evidence, retaining the original flat field types.

    The complete recorder output is retained under ``runtime``. In particular,
    legacy ``torch`` remains a version string rather than becoming a dictionary.
    Capture anew before each seed; equal metadata must not be assumed by copying
    the plan's snapshot into every result.
    """
    runtime = run_environment(sequence_preprocessing=True)
    torch_state = runtime["torch"]
    return {
        "python": runtime["python"], "platform": runtime["platform"],
        "numpy": runtime["numpy"], "pandas": runtime["pandas"],
        "scikit_learn": runtime["scikit_learn"],
        "torch": torch_state.get("version"),
        "torch_threads": torch_state.get("threads"),
        "deterministic_algorithms": torch_state.get("deterministic_algorithms"),
        "sequence_preprocessing_version": runtime["sequence_preprocessing_version"],
        "runtime": runtime,
    }


def run_seed_sweep(cohort_path: Path, output: Path) -> dict:
    """Use the frozen cohort; exclude test rows before invoking any trainer."""
    import torch

    cohort_path, output = Path(cohort_path), Path(output)
    digest = file_sha256(cohort_path)
    if digest != COHORT_SHA256:
        raise ValueError("frozen cohort SHA-256 mismatch; no training started")
    # Never silently mix outputs from a previous or partially completed sweep.
    output.mkdir(parents=True, exist_ok=False)
    environment = _sweep_environment()
    plan = {"seeds": list(SEEDS), "seed_42_previously_observed": True,
            "epochs_max": 40, "batch_size": 2048, "patience": 7,
            "minimum_validation_ap_improvement": 1e-5,
            "train_end": TemporalSplit().train_end,
            "validation_end": TemporalSplit().validation_end,
            "code_commit": os.environ.get("GITHUB_SHA"), "cohort_sha256": digest,
            "environment": environment, "test_evaluated": False,
            "test_already_inspected_in_earlier_research": True,
            "selection_policy": "no seed selected; report every run and median/spread",
            "calibration_policy": "not fitted in this validation-only sensitivity run"}
    (output / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
    frame = pd.read_parquet(cohort_path)
    dates = pd.to_datetime(frame["filed"], errors="raise")
    if dates.isna().any():
        raise ValueError("filing dates must be present")
    frame = frame.loc[dates <= pd.Timestamp(TemporalSplit().validation_end)].copy()
    runs = []
    for seed in SEEDS:
        directory = output / f"seed-{seed}"
        row = {"seed": seed, "cohort_sha256": digest, "code_commit": plan["code_commit"],
               "environment": _sweep_environment()}
        try:
            model, metrics, config, history = train_pytorch_gru(
                frame.copy(deep=True), epochs=40, batch_size=2048, seed=seed,
                validation_only=True, calibration_out_dir=directory)
            if "test" in metrics or config.get("test_evaluated") is not False:
                raise ValueError("validation-only result contract violated")
            with np.load(directory / "validation_predictions.npz", allow_pickle=False) as saved:
                ids = saved["validation_observation_id"]
                labels = saved["y_validation"]
                if len(set(ids)) != len(ids) or any("unavailable" in v for v in ids):
                    raise ValueError("unique complete validation observation IDs required")
                ids_digest = hashlib.sha256(json.dumps(ids.tolist()).encode()).hexdigest()
                labels_digest = hashlib.sha256(np.asarray(labels, dtype="<i8").tobytes()).hexdigest()
            values = metrics["validation"]
            row.update(status="success", validation_identity_sha256=ids_digest,
                       validation_labels_sha256=labels_digest,
                       validation_rows=values["rows"], validation_positives=values["positives"],
                       average_precision=values["pr_auc"], roc_auc=values["roc_auc"],
                       average_precision_over_prevalence=values["pr_auc"] / values["prevalence"],
                       config=config, history=history)
            torch.save(model.state_dict(), directory / "pytorch_gru_state.pt")
            del model
        except Exception as exc:
            # Preserve failures; do not replace unlucky/failed seeds or summarize survivors.
            row.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        runs.append(row)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "result.json").write_text(
            json.dumps(row, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    report = summarize_runs(runs)
    (output / "summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    return report
