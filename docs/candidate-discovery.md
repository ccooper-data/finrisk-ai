# Historical security candidate discovery v2

Discovery may be broad; acceptance remains strict.

Candidate generation uses every authoritative SEC historical alias plus normalized token overlap and string similarity. Its purpose is recall: surface plausible securities for evidence gathering.

A discovery score is never identifier evidence and can never by itself produce an accepted CIK-to-security link. Candidates still pass the separate security-resolution layer, temporal checks and ambiguity rules.

This separation lets FinRisk search broadly without converting fuzzy matching into ground truth.
