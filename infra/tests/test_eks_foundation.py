#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
eks = (ROOT / "terraform" / "eks.tf").read_text()
variables = (ROOT / "terraform" / "variables.tf").read_text()
manifest = (ROOT / "k8s" / "inference.yaml").read_text()

checks = {
    "EKS defaults disabled": 'variable "enable_eks"' in variables and "default     = false" in variables,
    "worker max capped at 2": "max_size     = 2" in eks,
    "private subnet placement": "subnet_ids      = aws_subnet.private[*].id" in eks,
    "non-root pod": "runAsNonRoot: true" in manifest,
    "no privilege escalation": "allowPrivilegeEscalation: false" in manifest,
    "all capabilities dropped": 'drop: ["ALL"]' in manifest,
    "resource requests": "requests:" in manifest,
    "resource limits": "limits:" in manifest,
    "liveness probe": "/health/live" in manifest,
    "readiness probe": "/health/ready" in manifest,
    "HPA capped": "maxReplicas: 3" in manifest,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("EKS acceptance failed: " + ", ".join(failed))
