from __future__ import annotations
from dataclasses import dataclass,asdict

@dataclass(frozen=True)
class DataUsageRights:
    provider:str
    research_use:bool
    artifact_redistribution:bool
    derived_feature_redistribution:bool
    public_demo:bool
    attribution_required:bool
    notes:str=""

def publication_gate(rights:DataUsageRights)->dict:
    blockers=[]
    if not rights.research_use:blockers.append("research use not permitted")
    if not rights.public_demo:blockers.append("public demo not permitted")
    return {"provider":rights.provider,"public_demo_allowed":not blockers,"blockers":blockers,
            "raw_artifact_publishable":rights.artifact_redistribution,
            "derived_features_publishable":rights.derived_feature_redistribution,
            "rights":asdict(rights)}
