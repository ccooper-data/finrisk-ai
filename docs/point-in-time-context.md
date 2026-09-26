# Point-in-time external context

FinRisk external features must be joined using information available on or before each filing date.

## Market contract
Daily issuer observations are transformed into trailing 21/63/252-day returns, 63-day realized volatility, 252-day drawdown/distance-to-high, and 63-day volume z-score. The as-of join is backward-only.

## Macro contract
Macro series are stored with an availability date. Joins are backward-only. Production ingestion must use publication/vintage availability when the source exposes it; revised values must never be treated as historically known.

Planned public sources include SEC issuer mapping plus market-price data and official macroeconomic series. Every ingestion adapter must persist source URL/identifier, retrieval timestamp, source date/vintage where available, and SHA-256 evidence.
