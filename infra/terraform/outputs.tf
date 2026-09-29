output "budget_name" {
  description = "AWS Budget used as the FinRisk-AI portfolio cost guardrail."
  value       = aws_budgets_budget.portfolio.name
}

output "hard_ceiling_usd" {
  description = "Maximum permitted monthly budget value for this portfolio environment."
  value       = var.monthly_budget_limit_usd
}
