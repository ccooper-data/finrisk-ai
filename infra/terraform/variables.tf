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
  description = "Monthly AWS Budget alert limit for this portfolio environment (capped at $100). Alerts only; teardown is what stops spend."
  type        = number
  default     = 100

  validation {
    condition     = var.monthly_budget_limit_usd > 0 && var.monthly_budget_limit_usd <= 100
    error_message = "FinRisk-AI portfolio budget must be greater than $0 and cannot exceed the $100 cap."
  }
}

variable "budget_alert_email" {
  description = "Optional email for AWS Budget notifications. Supply through protected runtime configuration."
  type        = string
  default     = null
  nullable    = true
  sensitive   = true
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

variable "enable_eks" {
  description = "Create the billable EKS validation environment. Defaults false to protect the portfolio budget."
  type        = bool
  default     = false
}

variable "eks_cluster_version" {
  description = "Pinned Kubernetes minor version for the portfolio EKS cluster."
  type        = string
  default     = "1.35"
}

variable "eks_node_instance_types" {
  description = "Worker type for bounded portfolio validation: one t3.large holds kube-system, Argo CD, Prometheus and the inference pods at HPA max (infra/tests/check_capacity_budget.py). m7i-flex.large, the same size, is the only budgeted alternative."
  type        = list(string)
  default     = ["t3.large"]

  validation {
    condition     = length(var.eks_node_instance_types) == 1 && alltrue([for t in var.eks_node_instance_types : contains(["t3.large", "m7i-flex.large"], t)])
    error_message = "Exactly one worker type, t3.large or m7i-flex.large: the capacity budget is checked for those two only."
  }
}

variable "eks_node_desired_size" {
  description = "Desired worker count during a bounded EKS validation window."
  type        = number
  default     = 1

  validation {
    condition     = var.eks_node_desired_size >= 1 && var.eks_node_desired_size <= 2
    error_message = "Portfolio EKS desired capacity is capped at two workers."
  }
}

variable "eks_public_access_cidrs" {
  description = "Explicit operator CIDRs allowed to reach the EKS public API during bounded validation. Empty means private-only API access."
  type        = list(string)
  default     = []

  validation {
    condition     = !contains(var.eks_public_access_cidrs, "0.0.0.0/0")
    error_message = "EKS API access must never be open to 0.0.0.0/0."
  }
}

variable "github_repository" {
  description = "GitHub owner/repository allowed to federate into AWS through OIDC."
  type        = string
  default     = "ccooper-data/finrisk-ai"
}

variable "github_deploy_ref" {
  description = "Only this GitHub ref may assume the deployment role."
  type        = string
  default     = "refs/heads/main"
}

variable "enable_audit_trail" {
  description = "Enable the billable/operational CloudTrail evidence path during bounded deployment validation."
  type        = bool
  default     = false
}

variable "gitops_revision" {
  description = "Commit Argo CD deploys charts/finrisk-inference from: the PLAN's own commit (provision-bounded-aws.yml passes GITHUB_SHA). Null outside PLAN (DESTROY, the reaper); both builds then refuse to run."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.gitops_revision == null || can(regex("^[0-9a-f]{40}$", var.gitops_revision))
    error_message = "gitops_revision must be a full 40-character lowercase commit SHA."
  }
}
