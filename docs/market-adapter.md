# Governed market adapter

Provider-specific integrations inherit one adapter boundary.

The adapter capability gate executes before historical ingestion. Security-master and price outputs then pass the shared provider-neutral validation contracts. This prevents provider-specific code from bypassing historical-identity, provenance or price-quality controls.

Provider credentials and source-specific terms remain outside the generic adapter.
