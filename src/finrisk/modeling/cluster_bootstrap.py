"""Paired issuer-cluster uncertainty for an already-fitted model/calibrator."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import brier_score_loss, log_loss


def _losses(y, p):
    return {
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
    }


def paired_cik_cluster_bootstrap(
    y,
    p_model,
    baseline_probability,
    ciks,
    *,
    replicates=10000,
    seed=42,
    baseline_fit_partition="validation",
):
    y = np.asarray(y, dtype=int)
    p_model = np.asarray(p_model, dtype=float)
    ciks = np.asarray(ciks, dtype=str)
    if not (len(y) == len(p_model) == len(ciks)) or not len(y):
        raise ValueError("aligned nonempty arrays required")
    baseline_probability = float(baseline_probability)
    if not np.isfinite(baseline_probability) or not 0 < baseline_probability < 1:
        raise ValueError("validation-fitted baseline probability must be in (0,1)")
    if np.any(ciks == "unavailable") or np.any(ciks == ""):
        raise ValueError("complete usable CIK coverage required")
    unique_ciks, inverse = np.unique(ciks, return_inverse=True)
    if len(unique_ciks) < 2:
        raise ValueError("at least two issuer clusters required")

    p_baseline = np.full(len(y), baseline_probability, dtype=float)
    groups = [np.flatnonzero(inverse == i) for i in range(len(unique_ciks))]
    model_point = _losses(y, p_model)
    baseline_point = _losses(y, p_baseline)
    point = {k: baseline_point[k] - model_point[k] for k in model_point}

    rng = np.random.default_rng(seed)
    draws = {k: np.empty(replicates) for k in point}
    for replicate in range(replicates):
        sampled = rng.integers(0, len(groups), len(groups))
        index = np.concatenate([groups[i] for i in sampled])
        model_loss = _losses(y[index], p_model[index])
        baseline_loss = _losses(y[index], p_baseline[index])
        for metric in draws:
            draws[metric][replicate] = baseline_loss[metric] - model_loss[metric]

    metrics = {}
    for metric, values in draws.items():
        lower, upper = np.quantile(values, [0.025, 0.975])
        metrics[metric] = {
            "baseline_minus_model": point[metric],
            "interval_95": [float(lower), float(upper)],
            "replicates_model_better": int(np.sum(values > 0)),
            "replicates_model_not_better": int(np.sum(values <= 0)),
        }

    return {
        "method": "paired_cik_cluster_bootstrap",
        "seed": seed,
        "replicates": replicates,
        "test_rows": int(len(y)),
        "unique_test_ciks": int(len(unique_ciks)),
        "comparison": "validation-fitted constant minus calibrated model; positive favors model",
        "baseline_fit_partition": baseline_fit_partition,
        "baseline_probability": baseline_probability,
        "metrics": metrics,
        "scope": {
            "conditional_on_fitted_model_and_calibrator": True,
            "includes_retraining_uncertainty": False,
            "includes_calibrator_refit_uncertainty": False,
            "addresses_cross_issuer_macro_dependence": False,
            "population_generalization_interval": False,
        },
    }
