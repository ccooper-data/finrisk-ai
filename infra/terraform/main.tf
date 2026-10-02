provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "FinRisk-AI"
      Environment = var.environment
      ManagedBy   = "Terraform"
      CostCenter  = "Portfolio"
    }
  }
}

locals {
  budget_thresholds = toset(["10", "25", "50", "75", "100"])
}

resource "aws_budgets_budget" "portfolio" {
  name         = "${var.project_name}-${var.environment}-validation-alerts"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = nonsensitive(var.budget_alert_email == null) ? toset([]) : local.budget_thresholds
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = tonumber(notification.value)
      threshold_type             = "ABSOLUTE_VALUE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }
}

check "portfolio_budget_ceiling" {
  assert {
    condition     = var.monthly_budget_limit_usd <= 100
    error_message = "Deployment blocked: requested budget exceeds the FinRisk-AI $100 hard ceiling."
  }
}
