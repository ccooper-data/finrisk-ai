# Bounded SEC filing retrieval plan

Identifier corroboration should not crawl an issuer's entire EDGAR history.

For each ISIN-bearing target, FinRisk selects at most six recent core filings already present in the filing-era SEC evidence: 10-K, 10-Q and 8-K families. Accession numbers and filing dates are frozen before document retrieval.

This creates a bounded, reproducible retrieval plan. Exhibit discovery happens within those selected accessions; unrelated historical filings are not crawled by default.
