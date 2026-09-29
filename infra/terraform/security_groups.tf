# Security-group boundaries are intentionally split by responsibility.
# ALB accepts HTTP only for the portfolio demonstration path; TLS is added when
# a real DNS/certificate path exists rather than fabricating certificate state.
resource "aws_security_group" "alb" {
  name_prefix = "${var.project_name}-${var.environment}-alb-"
  description = "Internet-facing ingress boundary for FinRisk-AI"
  vpc_id      = aws_vpc.platform.id

  ingress {
    description = "Portfolio HTTP ingress; replace with HTTPS when ACM/DNS is configured"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Forward traffic to application targets"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-alb-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "application" {
  name_prefix = "${var.project_name}-${var.environment}-app-"
  description = "Private application workload boundary for FinRisk-AI"
  vpc_id      = aws_vpc.platform.id

  ingress {
    description     = "Inference API traffic from ALB only"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "HTTPS egress for AWS APIs and bounded dependency access"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-app-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "vpc_endpoints" {
  name_prefix = "${var.project_name}-${var.environment}-vpce-"
  description = "PrivateLink endpoint boundary for FinRisk-AI"
  vpc_id      = aws_vpc.platform.id

  ingress {
    description     = "HTTPS from application workloads"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.application.id]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-vpce-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}
