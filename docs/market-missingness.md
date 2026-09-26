# Market missingness policy

Unresolved securities and missing historical prices remain in the labeled modeling population.

Market enrichment adds explicit availability and per-feature missingness indicators. Downstream preprocessing may impute numeric market features using training-era statistics, but it may not drop unmatched rows.

This policy allows a fair financial-only versus financial-plus-market comparison on the same observations and prevents survivorship bias from re-entering through preprocessing.
