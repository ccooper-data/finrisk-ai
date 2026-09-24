# FinRisk AI

**Point-in-time financial distress and risk intelligence with SEC fundamentals, macroeconomic context, market behavior, PyTorch, and TensorFlow.**

FinRisk AI is a production-shaped ML research platform for estimating 12-month corporate financial-distress risk without look-ahead leakage. The project is designed around a question a skeptical reviewer can audit: *what information was actually knowable on the prediction date?*

## Why this project is different

- Official SEC EDGAR / Financial Statement Data Sets as the fundamentals backbone.
- Filing-date knowledge cutoffs instead of random train/test splitting.
- High-confidence distress labels based on SEC 8-K Item 1.03 bankruptcy/receivership events.
- Correct SEC duration semantics so quarterly facts are not confused with YTD values.
- Point-in-time macro and market feature contracts.
- Logistic-regression baseline plus PyTorch and TensorFlow model families.
- Multimodal temporal architecture for fundamentals + market + macro histories.
- Reproducible evidence manifests and SHA-256 source/cohort lineage.
- GitHub Actions smoke/full SEC cohort execution.

## Research architecture

```text
SEC fundamentals ─────┐
FRED/ALFRED macro ────┼──> point-in-time observation ──> temporal evaluation
Market behavior ──────┘                                  │
                                                         ├─ Logistic baseline
                                                         ├─ PyTorch
                                                         └─ TensorFlow
```

## Leakage controls

Every historical observation is bounded by its SEC filing date. Future filings, post-cutoff prices, later macro revisions, and future distress events cannot enter model features. Primary evaluation uses chronological train/validation/test partitions.

## Real SEC build

The network-enabled workflow supports a smoke build before the full historical cohort.

```bash
export SEC_USER_AGENT="FinRisk AI your-real-email@example.com"
finrisk build-sec-cohort --start-year 2025 --end-year 2025 --end-quarter 4
```

See [docs/REAL_RUN.md](docs/REAL_RUN.md).

## Status

The research system has been developed through a validated local Milestone 14 baseline. The public repository is being populated in controlled increments, with CI verifying the published execution contract before real model metrics are reported.

No recruiter-facing performance number is published until it is tied to a source-hashed real historical cohort.
