# Delisting data contract

Historical market enrichment must preserve delisting events explicitly. A disappearing price series is not equivalent to a zero return or a healthy censoring event.

Required fields include security ID, delisting date/code/return and source provenance. Missing delisting returns remain missing unless a documented source-specific rule is approved; they are never silently imputed as zero.

This contract exists to prevent a market model from becoming optimistic by ignoring terminal losses of failed securities.
