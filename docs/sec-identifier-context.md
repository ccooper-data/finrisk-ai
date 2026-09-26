# SEC identifier document context

A syntactically valid CUSIP/ISIN is not sufficient security evidence because filings can mention debt, preferred stock, subsidiaries or third-party securities.

FinRisk stores a local text window around each extracted identifier and classifies the nearby security type. Only explicit common-equity context can support a common-stock candidate; debt, preferred, ambiguous and unknown contexts remain non-promotable without additional review.

Context classification is evidence triage, not final legal/security interpretation.
