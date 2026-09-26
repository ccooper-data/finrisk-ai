# Drift monitoring framework

FinRisk distinguishes feature drift from model-performance drift.

Feature monitoring uses population stability and null-rate changes against a declared reference population. A drift signal is evidence for investigation, not automatic proof that a model is invalid.

Performance drift requires labels and therefore arrives later than feature drift. Production-style monitoring should keep those concepts separate.
