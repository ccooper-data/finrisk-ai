# SEC filing document retrieval

Selected SEC documents are fetched only beneath the frozen accession archive URL. Raw response bytes are SHA-256 hashed before text analysis.

Documents larger than 8 MB are rejected rather than silently truncating evidence. HTML is flattened to text for identifier/context extraction while the raw-byte hash preserves exact-source provenance.

Transport success does not imply identifier or security acceptance.
