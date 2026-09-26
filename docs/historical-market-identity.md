# Historical market identity policy

CIK is the authoritative issuer identity. Current ticker symbols are never treated as historical identifiers.

Historical market enrichment must:
1. retain delisted/distressed issuers;
2. carry source identifier, valid-from/valid-to dates and provenance;
3. reject ambiguous name-only candidates from automatic acceptance;
4. require date overlap for any historical-security candidate;
5. never drop unmatched rows silently;
6. pass survivorship gates before a market ablation is considered comparable.

Exact normalized-name matches are review candidates, not automatic truth. Automatic acceptance requires stronger identifier evidence plus temporal overlap.

The SEC cumulative CIK/name artifact is an identity bridge, not a historical ticker source. EDGAR filing headers can also contain dated former company names, which may be incorporated later as primary-source alias evidence.
