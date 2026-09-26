from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class IdentifierEvidence:
    identifier_corroborated:bool
    security_context:str
    cik_matches_filing:bool
    filing_date:str
    candidate_valid_from:str|None
    candidate_valid_to:str|None
    ambiguous_identifier:bool=False

def identifier_promotion_gate(e:IdentifierEvidence)->dict:
    reasons=[]
    if not e.identifier_corroborated:reasons.append("identifier not independently corroborated")
    if e.security_context!="common_equity":reasons.append("identifier not in explicit common-equity context")
    if not e.cik_matches_filing:reasons.append("filing CIK does not match issuer under review")
    if e.ambiguous_identifier:reasons.append("identifier evidence is ambiguous")
    if e.candidate_valid_from and e.filing_date<e.candidate_valid_from:reasons.append("filing predates candidate validity")
    if e.candidate_valid_to and e.filing_date>e.candidate_valid_to:reasons.append("filing postdates candidate validity")
    return {"eligible_for_security_acceptance_review":not reasons,"reasons":reasons}
