# Market ablation protocol

A market-data experiment is valid only after historical identity resolution and the survivorship gate pass.

Comparisons must use identical labeled rows across financial-only, market-only, and combined models. Unmatched securities remain explicit missingness; they are never silently removed to improve coverage.

Primary metric: out-of-time PR-AUC.
Secondary: ROC-AUC and Brier score.

Market features are trailing and filing-date as-of only. No price, volume, corporate action, identifier change, or delisting information dated after the filing may enter its feature vector.

The first approved market experiment will compare:
- financial only;
- market only;
- financial + market;
- later, financial trajectory + market trajectory.
