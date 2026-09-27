# Tier-A live SEC identifier pilot runner

The runner composes the previously tested boundaries: frozen Tier-A accessions, bounded accession index retrieval, bounded document selection, source-hashed document fetch, identifier extraction and local security-type context.

It sleeps between SEC requests and never performs global EDGAR discovery. Extracted evidence remains unreviewed and cannot accept a security mapping.

The pilot measures retrieval/extraction yield only; identifier-to-candidate corroboration is evaluated separately.
