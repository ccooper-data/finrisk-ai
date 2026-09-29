variable "enable_observability" {
  description = "Enable CloudWatch operational resources during bounded runtime validation."
  type        = bool
  default     = false
}

variable "inference_log_retention_days" {
  description = "Short retention for portfolio inference logs to control cost."
  type        = number
  default     = 7

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30], var.inference_log_retention_days)
    error_message = "Use a bounded CloudWatch Logs retention period."
  }
}

resource "aws_cloudwatch_log_group" "inference" {
  count             = var.enable_observability ? 1 : 0
  name              = "/finrisk/${var.environment}/inference"
  retention_in_days = var.inference_log_retention_days

  tags = {
    Purpose = "Bounded FinRisk inference telemetry"
  }
}

resource "aws_cloudwatch_metric_alarm" "inference_errors" {
  count               = var.enable_observability ? 1 : 0
  alarm_name          = "${var.project_name}-${var.environment}-inference-errors"
  alarm_description   = "Portfolio SLO guardrail: sustained server-side inference failures."
  namespace           = "FinRisk/Inference"
  metric_name         = "ServerErrors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "latency_p95" {
  count               = var.enable_observability ? 1 : 0
  alarm_name          = "${var.project_name}-${var.environment}-latency-p95"
  alarm_description   = "Portfolio SLO guardrail: p95 inference latency >= 300 ms."
  namespace           = "FinRisk/Inference"
  metric_name         = "InferenceLatency"
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 1
  threshold           = 300
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
}
