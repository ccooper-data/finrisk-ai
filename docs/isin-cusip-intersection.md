# ISIN-CUSIP identifier intersection

For U.S. ISINs, positions 3-11 contain the nine-character national security identifier (CUSIP). FinRisk uses that structural relationship only for syntactically valid US-prefixed ISINs.

The diagnostic intersects the candidate security's embedded CUSIP with SEC common-equity CUSIPs already corroborated across at least two independent accessions. Exact intersection is strong review evidence but does not itself accept a mapping; every result remains unreviewed and must pass the promotion gate.
