# Five-case historical 13(f) coverage probe

## Purpose
Test source suitability before scaling historical official-list parsing.

## Date rule
The repository does not currently contain populated delisting-date evidence for these hard cases. Therefore this experiment does not use or infer delisting dates.

For each selected case, use the last observed SEC filing quarter as an explicitly labeled proxy observation date. Test the official 13(f) list for that quarter (or immediately preceding available quarter).

## Case selection
Select five cases deterministically from the 100 hard cases across the observed last-filing-year range; do not hand-pick based on expected source hits.

## Extraction
Use positional PDF extraction. CUSIP is reconstructed from the CUSIP column and must pass checksum validation. Issuer name and issuer description are separate positional columns. Drop CALL and PUT descriptions before matching. Strip repeated page furniture.

## Interpretation
A match is discovery coverage, not security acceptance. Absence may mean non-13(f)-eligible/OTC, source-list omission, or name mismatch. No absence is treated as negative identity evidence.

No threshold is calibrated from five cases.
