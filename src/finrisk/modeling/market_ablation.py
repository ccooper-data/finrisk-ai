from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

def ablation_contract(financial:dict,market:dict,combined:dict)->dict:
    return {"financial_only":financial,"market_only":market,"financial_plus_market":combined,
            "comparison_rule":"same labeled rows and temporal boundaries required",
            "primary_metric":"pr_auc","secondary_metrics":["roc_auc","brier"]}

def write_ablation_contract(out:Path,**kwargs):
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(ablation_contract(**kwargs),indent=2))
