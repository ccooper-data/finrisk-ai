output "budget_name" {
  description = "AWS Budget used as the FinRisk-AI portfolio cost guardrail."
  value       = aws_budgets_budget.portfolio.name
}

output "hard_ceiling_usd" {
  description = "Maximum permitted monthly budget value for this portfolio environment."
  value       = var.monthly_budget_limit_usd
}

output "vpc_id" {
  description = "FinRisk-AI platform VPC ID."
  value       = aws_vpc.platform.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs reserved for internet-facing ingress."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs reserved for application/EKS workloads."
  value       = aws_subnet.private[*].id
}

output "nat_gateway_enabled" {
  description = "Whether the intentionally opt-in NAT Gateway is enabled."
  value       = var.enable_nat_gateway
}

output "inference_ecr_repository_url" {
  description = "Immutable ECR repository URL for FinRisk inference images."
  value       = aws_ecr_repository.inference.repository_url
}
