from __future__ import annotations
from dataclasses import dataclass,asdict

@dataclass(frozen=True)
class ProviderCapabilities:
    name:str
    historical_delisted:bool
    delisting_returns:bool
    identifier_history:bool
    corporate_actions:bool
    adjusted_prices:bool
    provenance:bool
    point_in_time_identifiers:bool

def assess_provider(c:ProviderCapabilities)->dict:
    required={"historical_delisted":c.historical_delisted,"identifier_history":c.identifier_history,
              "provenance":c.provenance,"point_in_time_identifiers":c.point_in_time_identifiers}
    blockers=[k for k,v in required.items() if not v]
    warnings=[]
    if not c.delisting_returns:warnings.append("no explicit delisting returns")
    if not c.corporate_actions:warnings.append("no corporate-action feed")
    return {"provider":c.name,"eligible_for_historical_ablation":not blockers,"blockers":blockers,
            "warnings":warnings,"capabilities":asdict(c)}
