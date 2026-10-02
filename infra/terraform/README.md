# FinRisk-AI AWS Infrastructure

Terraform for the production-shaped portfolio deployment.

## Safety first
The configured AWS Budget limit is capped at **$100 USD**. The budget only sends alerts; it does not stop spend. Spend is bounded by tearing the environment down (manual DESTROY, with the hourly reaper as a backstop). The engineering target remains **$25–$50 total project spend**.

No `terraform apply` should be run from an unreviewed branch. Phase 1 introduces only the budget guardrail foundation; network and compute resources follow in later phases.

When `budget_alert_email` is intentionally configured, AWS Budget notifications are created at $10, $25, $50, $75, and $100 actual spend.

## Local validation
```bash
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

## Teardown principle
Billable validation infrastructure is ephemeral. Later phases must document and test `terraform destroy` before the platform is considered portfolio-complete.
