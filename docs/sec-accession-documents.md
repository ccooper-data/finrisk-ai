# SEC accession document selection

Within each frozen accession, FinRisk selects the known primary filing plus text-like documents whose filenames indicate EX-2 or EX-4 exhibits. EX-21 and unrelated attachments are excluded by construction.

Selection is capped at eight documents per accession and every selected URL is validated to remain beneath the frozen accession archive directory.

Filename selection is only a retrieval optimization; actual document type/context is still evaluated after text retrieval.
