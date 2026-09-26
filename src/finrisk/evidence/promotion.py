from __future__ import annotations

def promotion_gate(model_evidence:dict,experiment:dict,extra:dict|None=None)->dict:
    reasons=[]
    if experiment.get("status") not in {"candidate","promoted"}:reasons.append("experiment status is not candidate/promoted")
    if not model_evidence.get("data_artifacts"):reasons.append("missing frozen data lineage")
    if "test" not in model_evidence.get("metrics",{}):reasons.append("missing out-of-time test metrics")
    if not model_evidence.get("code_sha"):reasons.append("missing code SHA")
    if model_evidence.get("limitations") is None:reasons.append("limitations not declared")
    extra=extra or {}
    if extra.get("market_model") and not extra.get("survivorship_gate_passed"):reasons.append("market survivorship gate not passed")
    if extra.get("current_vintage_macro"):reasons.append("current-vintage macro evidence is exploratory")
    return {"passed":not reasons,"reasons":reasons}

def require_promotion(model_evidence:dict,experiment:dict,extra:dict|None=None):
    result=promotion_gate(model_evidence,experiment,extra)
    if not result["passed"]:raise ValueError(f"Promotion blocked: {result['reasons']}")
    return result
