# FinRisk AI

**Point-in-time corporate financial-distress ML research with auditable temporal, calibration, and evidence controls.**

FinRisk AI is a production-shaped ML research pipeline for estimating 12-month corporate financial-distress risk without look-ahead leakage. The project is designed around a question a skeptical reviewer can audit: *what information was actually knowable on the prediction date?*

## Why this project is different

- Official SEC EDGAR / Financial Statement Data Sets as the fundamentals backbone.
- Filing-date knowledge cutoffs instead of random train/test splitting.
- High-confidence distress labels based on SEC 8-K Item 1.03 bankruptcy/receivership events.
- Correct SEC duration semantics so quarterly facts are not confused with YTD values.
- Point-in-time macro and market feature contracts are implemented as exploratory research capabilities; they are not part of the promoted Version 1 headline model.
- Logistic-regression baseline plus boosted-tree, PyTorch, and TensorFlow model families.
- Version 1 promoted results are based on the audited SEC-fundamentals cohort; broader context integrations remain research extensions.
- Reproducible evidence manifests and SHA-256 source/cohort lineage.
- GitHub Actions smoke/full SEC cohort execution.

## Version 1 research architecture

```text
SEC fundamentals ──> point-in-time observation ──> maturity gate ──> temporal evaluation
                                                               │
                                                               ├─ Logistic baseline
                                                               ├─ Boosted tree
                                                               └─ PyTorch GRU

Exploratory extensions: FRED/ALFRED macro context and market-behavior contracts.
```

## Validated AWS lifecycle

The portfolio cloud architecture has been exercised against a real AWS account, not only statically planned.

- GitHub Actions authenticates to AWS through short-lived OIDC credentials; no long-lived AWS key is stored in the repository.
- Terraform state is remote, encrypted, versioned, and lock-protected.
- Deployment promotion applies the exact reviewed binary plan after provenance and SHA-256 verification.
- EKS uses a private API endpoint, scoped bootstrap permissions, and per-role permissions boundaries.
- Cost controls combine AWS Budget alerts with a persisted teardown lease and an independent scheduled reaper.
- Commit `d0096e9536b3b77597fc820ac391abccb0951c09` was exercised in the bounded live-AWS validation window: reviewed APPLY, reaper check, DESTROY, and final empty-state verification all completed successfully.
- Post-validation hardening commit `4361a69c54280537b1c8f1351eb2b4062b0dd257` is CI/static-validated; it was not the commit exercised during the live AWS window.
- Application deployment is intentionally out of scope for the private-only infrastructure validation window.

See [AWS validation closeout](docs/AWS_VALIDATION_CLOSEOUT.md) and [bounded AWS validation contract](docs/bounded-aws-validation.md).

## Leakage controls

Every historical observation is bounded by its SEC filing date. Future filings, post-cutoff prices, later macro revisions, and future distress events cannot enter model features. Primary evaluation uses chronological train/validation/test partitions.

## Real SEC build

The network-enabled workflow supports a smoke build before the full historical cohort.

```bash
export SEC_USER_AGENT="FinRisk AI your-real-email@example.com"
finrisk build-sec-cohort --start-year 2025 --end-year 2025 --end-quarter 4
```

See [docs/REAL_RUN.md](docs/REAL_RUN.md).

## Version 1 evidence freeze

Version 1 uses a source-hashed SEC cohort with 365-day outcome-window maturity enforced before modelling. The chronological test population contains 64,194 complete-window observations, including 669 SEC 8-K Item 1.03 distress positives (1.042% prevalence). Sequence models require prior history, so the final PyTorch GRU evaluates 63,322 observations with 666 positives (1.052% prevalence).

The predeclared seed-42 PyTorch GRU achieved **ROC-AUC 0.8103**, **average precision 0.0540**, and **5.13x average-precision lift over prevalence** on its maturity-filtered held-out population. This is a single fitted-model test result, not a multi-seed test estimate. A separate five-seed validation sensitivity experiment was completed before the Version 1 freeze.

The boosted tree and PyTorch GRU both show predictive value, but Version 1 does **not** claim one architecture outperforms the other. On their common 63,322-observation test population, issuer-clustered paired bootstrap intervals crossed zero for average precision, ROC-AUC, calibrated Brier score, and calibrated log loss.

Both promoted nonlinear models improved probability-quality metrics over their validation-fitted constant benchmarks. Calibration is reported component-wise: the final GRU's joint recalibration slope is approximately 1.001, while its calibration-in-the-large offset remains positive, consistent with underprediction of the later test-period event level.

Earlier experimental figures from pre-repair sequence ordering or incomplete outcome windows are superseded and are not Version 1 performance claims.

See [docs/V1_MODEL_CARD.md](docs/V1_MODEL_CARD.md) for the evidence scope, limitations, and interpretation.\n\nFor a fast review: [Version 1 results](docs/RESULTS.md) · [engineering rigor case study](docs/CASE_STUDY.md) · [5–10 minute demo guide](docs/DEMO_GUIDE.md).
