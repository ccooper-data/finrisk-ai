# SEC 13(f) official-list coverage experiment

## Question
Can the SEC Official List of Section 13(f) Securities provide a useful dated CUSIP-to-issuer-name bridge for the 100 distressed/no-current-ticker hard cases?

## Source contract
Use the SEC-published quarterly Official List of Section 13(f) Securities. The SEC defines the fixed-width text fields as CUSIP (positions 1-9), issuer name, issuer description, and status; quarterly archives provide dated vintages.

## Pre-committed interpretation
- CUSIP must pass the repository's hard checksum validator.
- Issuer-name similarity is discovery/ranking evidence only, never automatic identity acceptance.
- A hit means a hard-case SEC issuer alias has at least one candidate official-list issuer above a declared discovery threshold; it is not a promoted security mapping.
- Report coverage by filing era/vintage availability and do not calibrate general thresholds on the 100 hard cases alone.
- If historical archived list coverage does not reach the cohort era, report that as a source limitation rather than extrapolating.
- N-PORT is a later-era supplemental source, not a substitute for historical coverage outside its reporting period.

## Metrics
- hard cases evaluated
- hard cases with any official-list candidate
- exact normalized-name candidates
- fuzzy candidate counts and score distribution
- unique valid CUSIPs discovered
- vintage/era coverage
- unresolved hard cases

No model or promotion-gate change is permitted from this experiment alone.
