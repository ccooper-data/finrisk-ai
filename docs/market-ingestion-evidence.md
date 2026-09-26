# Market ingestion evidence

A historical-market dataset is frozen as a multi-file evidence package, not merely a price table.

The manifest hashes the security master and price history plus any delisting, corporate-action and benchmark files. It records provider and retrieval timestamp so model evidence can identify the exact historical-market snapshot used.

Provider terms/licensing are not inferred by this manifest and must be documented separately.
