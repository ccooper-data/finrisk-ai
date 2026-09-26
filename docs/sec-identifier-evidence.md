# SEC filing security-identifier evidence

Identifier evidence is collected from provenance-preserving SEC filing documents, prioritizing EX-4 security-holder instruments, EX-2 reorganization/succession plans and core 10-K/10-Q/8-K filing text.

CUSIP/ISIN-shaped strings are extraction candidates only. Every result retains CIK, accession, filing date, document type and exact SEC source URL and begins review_status=unreviewed.

The collector intentionally excludes unrelated exhibits by default to reduce false positives from subsidiary lists, compensation plans and third-party securities.
