"""Record what produced a run, so a later audit can tell drift from noise.

The seed-42 discrepancy that motivated this had two candidate causes: unstable
same-day ordering (fixed in modeling.sequences) and library drift. The second is
permanently unresolvable for that run because it recorded no versions at all --
so the discrepancy cannot be attributed, only superseded. Every run records this
now.
"""
from __future__ import annotations

import os
import platform
import sys

import numpy as np
import pandas as pd
import sklearn

# Bump when preprocessing changes the feature tensor for a fixed cohort.
# 1: original ordering (unstable same-day sort; not point-in-time reconstructible)
# 2: total stable ordering on (cik, filed, adsh)
SEQUENCE_PREPROCESSING_VERSION = 2


def _torch_state() -> dict:
    try:
        import torch
    except Exception:
        return {"available": False}
    state = {"available": True, "version": torch.__version__,
             "threads": int(torch.get_num_threads())}
    try:
        # True only if a caller opted in; recorded either way rather than assumed.
        state["deterministic_algorithms"] = bool(torch.are_deterministic_algorithms_enabled())
    except Exception:
        state["deterministic_algorithms"] = None
    try:
        state["cuda_available"] = bool(torch.cuda.is_available())
    except Exception:
        state["cuda_available"] = None
    return state


def _tensorflow_state() -> dict:
    if "tensorflow" not in sys.modules:
        return {"available": "not_imported"}
    tf = sys.modules["tensorflow"]
    return {"available": True, "version": getattr(tf, "__version__", None)}


def run_environment(*, sequence_preprocessing: bool = False) -> dict:
    env = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit_learn": sklearn.__version__,
        "torch": _torch_state(),
        "tensorflow": _tensorflow_state(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
    }
    if sequence_preprocessing:
        env["sequence_preprocessing_version"] = SEQUENCE_PREPROCESSING_VERSION
    return env
