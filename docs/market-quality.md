# Historical price quality gates

Before feature engineering, price histories must pass structural and plausibility checks: required provenance fields, unique security/date keys, positive closes and non-negative volume.

Calendar gaps are reported rather than automatically filled. Long gaps can reflect suspensions, sparse trading, source limitations or delisting; forward-filling them into artificial daily prices is prohibited.
