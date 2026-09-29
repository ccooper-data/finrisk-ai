variable "aws_region" {
  description = "AWS region for the portfolio platform."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project tag/name."
  type        = string
  default     = "finrisk-ai"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "portfolio"
}

variable "monthly_budget_limit_usd" {
  description = "Hard AWS budget ceiling for this portfolio environment."
  type        = number
  default     = 100

  validation {
    condition     = var.monthly_budget_limit_usd > 0 && var.monthly_budget_limit_usd <= 100
    error_message = "FinRisk-AI portfolio budget must be greater than $0 and cannot exceed the $100 hard ceiling."
  }
}

variable "budget_alert_email" {
  description = "Optional email for AWS Budget notifications. Leave null until an address is intentionally configured."
  type        = string
  default     = null
  nullable    = true
}

variable "vpc_cidr" {
  description = "CIDR block for the FinRisk-AI portfolio VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "availability_zones" {
  description = "Two AZs used for the production-shaped network."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]

  validation {
    condition     = length(var.availability_zones) == 2
    error_message = "FinRisk-AI network design requires exactly two Availability Zones."
  }
}

variable "enable_nat_gateway" {
  description = "Create NAT only during active integration tests. Default false protects the portfolio budget."
  type        = bool
  default     = false
}
