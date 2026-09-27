# SEC accession retrieval boundary

Live identifier evidence retrieval starts from frozen CIK/accession pairs and requests only the SEC accession index. The index response is source-hashed before document selection.

All subsequent document URLs must remain under that accession's EDGAR archive directory. The retriever does not search EDGAR globally or discover additional issuers/accessions.

This module provides transport/provenance only; identifier extraction and security acceptance remain separate stages.
