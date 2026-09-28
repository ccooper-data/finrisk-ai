# Follow-up diagnostics for the controlled five-case 13(f) pilot

## Established pilot result
- 5 deterministic hard cases
- 20 observations
- 15 exact observation hits
- 4/5 cases hit at least once
- controls and parser fidelity passed for every tested vintage

These are pilot existence results, not calibrated population rates.

## Diagnostic A — CIK 0000895648
Question: is the 0/4 result true 13(f)-source absence or exact-name-key failure?

Run two independent checks:
1. Extend backward one quarter at a time before 2007Q4 until first exact hit or the 1996Q1 archive boundary.
2. For each sampled quarter, retain top near-miss issuer-name candidates and scores, but do not change the exact-hit definition or promote identity.

Interpretation:
- earlier exact hit -> dated source-presence history; later absence remains list-membership evidence
- strong near-miss without exact hit -> name-key limitation requiring review
- no exact/credible near-match with passing controls -> source noncoverage remains the supported conclusion

## Diagnostic B — Bristow Group
Question: where inside 2019 did the 13(f)-list presence -> absence transition occur?

Check 2019Q1/Q2/Q3/Q4 individually using the same parser and controls.
For each quarter record:
- exact discovery hit
- any matching STATUS event
- added_to_13f_list_quarter / deleted_from_13f_list_quarter where present

A *D* row may corroborate deleted_from_13f_list_quarter. It must not be labeled delist_date without independent listing/delisting evidence.

## Guardrails
No thresholds are calibrated from these cases. No identity promotion changes. No population coverage claims. No absence is converted into negative identity evidence.
