from __future__ import annotations

def provider_scorecard(capability:dict,rights:dict,probe:dict|None=None)->dict:
    blockers=[];warnings=[]
    if not capability.get("eligible_for_historical_ablation",False):blockers.extend(capability.get("blockers",["capability gate failed"]))
    if not rights.get("public_demo_allowed",False):warnings.append("public demo rights not confirmed")
    if probe is not None and not probe.get("passed",False):blockers.extend(probe.get("reasons",["probe gate failed"]))
    return {"eligible_for_full_ingestion":not blockers,"blockers":sorted(set(blockers)),
            "warnings":sorted(set(warnings+capability.get("warnings",[]))),
            "raw_artifact_publishable":rights.get("raw_artifact_publishable",False),
            "derived_features_publishable":rights.get("derived_features_publishable",False)}
