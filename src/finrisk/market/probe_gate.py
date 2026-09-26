from __future__ import annotations

def provider_probe_gate(report:dict,min_hard_resolution=.80,min_hard_priced=.70,min_overall_priced=.80)->dict:
    hard=report.get("by_group",{}).get("distressed_no_current_ticker",{})
    hc=max(1,int(hard.get("companies",0)));hard_resolved=hard.get("resolved",0)/hc;hard_priced=hard.get("priced",0)/hc
    overall=report.get("priced_rate",0.0);reasons=[]
    if hard_resolved<min_hard_resolution:reasons.append("insufficient hard-case historical security resolution")
    if hard_priced<min_hard_priced:reasons.append("insufficient hard-case historical price coverage")
    if overall<min_overall_priced:reasons.append("insufficient overall probe price coverage")
    return {"passed":not reasons,"hard_resolution_rate":hard_resolved,"hard_priced_rate":hard_priced,
            "overall_priced_rate":overall,"thresholds":{"hard_resolution":min_hard_resolution,
            "hard_priced":min_hard_priced,"overall_priced":min_overall_priced},"reasons":reasons}
