# EODHD access preflight

Run account/access checks before the hard-case probe.

The preflight calls the EODHD User API and performs only two U.S. symbol-list discovery requests: active and delisted common stocks. It does not request per-security price history.

Current EODHD documentation states that a free account is limited to 20 calls/day and EOD history within the past year. The hard-case historical probe therefore requires account access capable of retrieving the historical windows under evaluation.

The preflight reports access; it does not infer contractual redistribution rights.
