#!/usr/bin/env python3
"""Static acceptance checks for the FinRisk-AI AWS network foundation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "terraform"


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def main() -> None:
    network = read("network.tf")
    security = read("security_groups.tf")
    endpoints = read("vpc_endpoints.tf")
    variables = read("variables.tf")

    assertions = {
        "two public subnets": 'resource "aws_subnet" "public"' in network and "count = 2" in network,
        "two private subnets": 'resource "aws_subnet" "private"' in network,
        "NAT defaults off": 'variable "enable_nat_gateway"' in variables and "default     = false" in variables,
        "private route uses conditional NAT": 'for_each = var.enable_nat_gateway ? [1] : []' in network,
        "application ingress is SG-referenced": "security_groups = [aws_security_group.alb.id]" in security,
        "application inference port": "from_port       = 8000" in security and "to_port         = 8000" in security,
        "S3 gateway endpoint": 'vpc_endpoint_type = "Gateway"' in endpoints and '.s3"' in endpoints,
        "no interface endpoints yet": 'vpc_endpoint_type = "Interface"' not in endpoints,
    }

    failures = [name for name, passed in assertions.items() if not passed]
    for name, passed in assertions.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")

    if failures:
        raise SystemExit(f"Network acceptance failed: {', '.join(failures)}")


if __name__ == "__main__":
    main()
