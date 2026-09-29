# S3 gateway endpoints have no hourly PrivateLink endpoint charge and reduce
# the need to route S3 artifact traffic through NAT.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.platform.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id

  tags = {
    Name = "${var.project_name}-${var.environment}-s3-endpoint"
  }
}

# Interface endpoints (ECR API/DKR, CloudWatch, STS, etc.) are intentionally
# deferred. Each carries an hourly/AZ cost, so they will be introduced only
# when measured deployment traffic justifies them versus a short-lived NAT
# integration window. This keeps architecture evidence aligned to the $100 cap.
