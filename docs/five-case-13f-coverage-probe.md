# Five-case historical 13(f) coverage probe

## Purpose
Test source suitability before scaling historical official-list parsing. Parser fidelity and cohort coverage are separate outcomes.

## Mandatory positive controls
Each tested quarter must include two predeclared exchange-listed positive-control issuers expected to appear in the official list. If either control is not recovered, that quarter is invalid and contributes no coverage result.

## Date rule
The repository does not contain populated delisting-date evidence for these hard cases. Do not infer delist_date.

For each selected case, anchor on the last observed SEC filing quarter and test a back-series at offsets 0, -4, -8, and -12 quarters, using the nearest available official-list quarter where necessary.

A presence-to-absence boundary may be recorded only as:
- last_13f_eligible_quarter
- first_13f_absent_quarter

It is dated market-eligibility evidence, not a delist_date.

## Case selection
Select five cases deterministically. Coverage inference should be reported within controlled era bands; format/parser fidelity should be reported separately across vintages.

## Positional extraction
Use positional PDF extraction, not regex over flattened text.
- CUSIP is reconstructed from its positional column and must pass checksum validation.
- Issuer name, issuer description, and STATUS are separate positional fields.
- Preserve a leading * marker separately as a potential list-change signal.
- Drop CALL and PUT descriptions before issuer coverage matching.
- Strip repeated page furniture.
- Enforce a plausible row-count floor; partial extraction invalidates that quarter.

## Name matching
Name is the discovery join key for this probe only.
- Normalize both SEC aliases and list issuer names.
- Compare against the historical list's truncated issuer-name field width.
- Account explicitly for common list abbreviations such as HLDGS, ASSUR, GENERAT, INTL, LTD/LT.
- Report exact normalized hits and near-misses separately.
- Name evidence never promotes a security identity.

## Interpretation
A match is discovery coverage, not security acceptance.
An absence is not negative identity evidence; it may mean non-13(f)-eligible/OTC, source omission, name mismatch, or genuine absence.
No threshold is calibrated from five cases.
A control failure voids the affected quarter rather than counting as an absence.
