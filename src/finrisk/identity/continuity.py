from __future__ import annotations
from dataclasses import dataclass,asdict
from typing import Literal

Relation=Literal["same_registrant","predecessor","successor","merger_survivor","bankruptcy_successor","spin_off","unknown"]

@dataclass(frozen=True)
class EntityContinuityEvidence:
    from_cik:str
    to_cik:str
    relation:Relation
    effective_date:str|None
    source:str
    source_identifier:str
    evidence_note:str

def validate_continuity(e:EntityContinuityEvidence)->None:
    if e.from_cik==e.to_cik and e.relation!="same_registrant":
        raise ValueError("Cross-entity continuity relation requires distinct CIKs")
    if e.relation!="same_registrant" and not e.effective_date:
        raise ValueError("Cross-entity continuity requires an effective date")
    if not e.source or not e.source_identifier:
        raise ValueError("Continuity evidence requires provenance")

def continuity_record(e:EntityContinuityEvidence)->dict:
    validate_continuity(e);return asdict(e)
