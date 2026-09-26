# SEC identifier evidence target selection

Real filing retrieval begins with the candidate-strength rows where EODHD exposes an ISIN. Targets are prioritized by existing evidence tier: high-margin first, then strong-but-ambiguous.

Selection is only an evidence-collection queue. It does not imply the EODHD security is correct and does not change accepted_security.

This bounded cohort keeps SEC retrieval focused on candidates where independent identifier corroboration can directly resolve the current ambiguity.
