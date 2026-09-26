# EODHD historical-depth probe

This probe answers one question before the larger hard-case experiment: can the configured account retrieve genuinely old EOD price history?

It selects at most three distressed issuers without current tickers whose SEC historical name has exactly one normalized-name candidate in the EODHD U.S. universe. That candidate is for access testing only and is not promoted to an accepted historical security mapping.

Each selected security requests at most one year of historical EOD data, prioritizing old filing periods. The probe consumes at most three per-security EOD requests after the two symbol-list discovery calls.
