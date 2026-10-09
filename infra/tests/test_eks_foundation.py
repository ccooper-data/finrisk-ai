#!/usr/bin/env python3
import re
from pathlib import Path

import yaml

from pod_security import restricted

ROOT = Path(__file__).resolve().parents[1]
eks = (ROOT / "terraform" / "eks.tf").read_text()
variables = (ROOT / "terraform" / "variables.tf").read_text()
chart = ROOT.parent / "charts" / "finrisk-inference" / "templates"
# The chart, the only deploy artifact: its Deployment and HPA templates.
manifest = (chart / "deployment.yaml").read_text() + (chart / "hpa.yaml").read_text()
bootstrap = (ROOT / "terraform" / "deploy" / "bootstrap-buildspec.yml.tftpl").read_text()

# Pod Security "restricted" (pod_security.py) for the chart's Pod template, without helm: the template
# lines (labels, the image) are dropped and the rest loads as plain YAML. check_inference_chart.py checks
# the real render. Enforce applies to the Pods a workload creates, so a violation would otherwise surface
# only after Argo CD syncs.
untemplated = "\n".join(line for line in (chart / "deployment.yaml").read_text().splitlines() if "{{" not in line)
templates = [d["spec"]["template"] for d in yaml.safe_load_all(untemplated) if d and "template" in (d.get("spec") or {})]
results = [restricted(t) for t in templates]
psa_labels = {key: re.findall(rf"pod-security\.kubernetes\.io/{key}=(\S+)", bootstrap)
              for key in ("enforce", "enforce-version", "warn", "warn-version")}
checks = {
    "EKS defaults disabled": 'variable "enable_eks"' in variables and "default     = false" in variables,
    "worker max capped at 2": "max_size     = 2" in eks,
    "private subnet placement": "subnet_ids      = aws_subnet.private[*].id" in eks,
    "private-only API by default": "endpoint_public_access  = length(var.eks_public_access_cidrs) > 0" in eks,
    "world-open API prohibited": '!contains(var.eks_public_access_cidrs, "0.0.0.0/0")' in variables,
    "non-root pod": "runAsNonRoot: true" in manifest,
    "no privilege escalation": "allowPrivilegeEscalation: false" in manifest,
    "all capabilities dropped": 'drop: ["ALL"]' in manifest,
    "resource requests": "requests:" in manifest,
    "resource limits": "limits:" in manifest,
    "liveness probe": "/health/live" in manifest,
    "readiness probe": "/health/ready" in manifest,
    "HPA capped": "maxReplicas: 3" in manifest,
    "chart Deployment has a Pod template": bool(templates),
    **{name: all(r[name] for r in results) for name in (results[0] if results else {})},
    # One loop labels the app namespace and the add-on namespaces (Argo CD, monitoring) alike.
    "namespaces enforce and warn Pod Security restricted, latest version":
        'for ns in "${namespace}" "$A" "$M"; do' in bootstrap
        and 'label namespace "$ns" --overwrite' in bootstrap
        and psa_labels == {"enforce": ["restricted"], "enforce-version": ["latest"],
                           "warn": ["restricted"], "warn-version": ["latest"]},
    "worker type sized for the add-ons, validated to the budgeted types":
        'default     = ["t3.large"]' in variables and 'contains(["t3.large", "m7i-flex.large"], t)' in variables,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("EKS acceptance failed: " + ", ".join(failed))
