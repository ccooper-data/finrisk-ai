from __future__ import annotations
from dataclasses import dataclass,asdict
from typing import Literal
import pandas as pd
from finrisk.identity.resolution import candidate_score,classify_candidate

Decision=Literal["accepted_identifier","review_exact_name","review_candidate","rejected"]

@dataclass(frozen=True)
class SecurityCandidateEvidence:
    cik:str
    sec_name:str
    security_id:str
    security_name:str
    issuer_start:str
    issuer_end:str
    security_start:str
    security_end:str
    source:str
    source_identifier:str
    name_score:float
    date_overlap:bool
    identifier_evidence:bool
    decision:Decision

def overlap(a0,a1,b0,b1)->bool:
    return max(pd.Timestamp(a0),pd.Timestamp(b0))<=min(pd.Timestamp(a1),pd.Timestamp(b1))

def evaluate_candidate(cik,sec_name,issuer_start,issuer_end,candidate:dict)->SecurityCandidateEvidence:
    date_ok=overlap(issuer_start,issuer_end,candidate["valid_from"],candidate["valid_to"])
    score=candidate_score(sec_name,candidate["security_name"])
    strong=bool(candidate.get("identifier_evidence",False))
    decision=classify_candidate(score,date_ok,strong)
    return SecurityCandidateEvidence(cik=str(cik),sec_name=sec_name,security_id=str(candidate["security_id"]),
      security_name=str(candidate["security_name"]),issuer_start=str(issuer_start),issuer_end=str(issuer_end),
      security_start=str(candidate["valid_from"]),security_end=str(candidate["valid_to"]),source=str(candidate["source"]),
      source_identifier=str(candidate["source_identifier"]),name_score=score,date_overlap=date_ok,
      identifier_evidence=strong,decision=decision)

def candidate_frame(items:list[SecurityCandidateEvidence])->pd.DataFrame:
    return pd.DataFrame([asdict(x) for x in items])
