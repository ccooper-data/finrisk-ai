from __future__ import annotations
from finrisk.market.capabilities import ProviderCapabilities,assess_provider
from finrisk.market.licensing import DataUsageRights,publication_gate

def compare_provider(provider:ProviderCapabilities,rights:DataUsageRights)->dict:
    capability=assess_provider(provider);publication=publication_gate(rights)
    blockers=list(capability["blockers"])
    if not rights.research_use:blockers.append("research use not permitted")
    return {"provider":provider.name,"eligible_for_probe":not blockers,
            "capability":capability,"publication":publication,"blockers":blockers}

def rank_for_probe(reports:list[dict])->list[dict]:
    # This is not a predictive-model ranking; it prioritizes providers satisfying hard data-governance requirements.
    eligible=[r for r in reports if r["eligible_for_probe"]]
    return sorted(eligible,key=lambda r:(len(r["capability"]["warnings"]),not r["publication"]["public_demo_allowed"],r["provider"]))
