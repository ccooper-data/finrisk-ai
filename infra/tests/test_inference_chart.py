#!/usr/bin/env python3
# charts/finrisk-inference without helm: image by digest only, no Namespace, the ServiceMonitor off by
# default, and CI that installs the pinned tools and runs check_inference_chart.py (which needs them).
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "charts/finrisk-inference"
templates = {p.name: p.read_text() for p in sorted((CHART / "templates").glob("*.yaml"))}
values = yaml.safe_load((CHART / "values.yaml").read_text())
schema = json.loads((CHART / "values.schema.json").read_text())
image = schema["properties"]["image"]
install = (ROOT / ".github/scripts/install-k8s-tools.sh").read_text()
# PyYAML reads the bare `on:` key as True.
workflow = yaml.safe_load((ROOT / ".github/workflows/terraform-validate.yml").read_text())
job = workflow["jobs"]["validate"]
runs = [s.get("run", "") for s in job["steps"]]
pinned = dict(re.findall(r'^(\w+)="([^"]+)"$', install, re.M))
fetched = re.findall(r'^fetch \S+ "(https://[^"]+)" "\$(\w+_SHA256)"$', install, re.M)


def step(command):
    return next((i for i, run in enumerate(runs) if run.strip() == command), -1)


def plain(i):
    # Runs every time and fails the job: no condition, no continue-on-error.
    return i >= 0 and not {"if", "continue-on-error"} & set(job["steps"][i]) and "continue-on-error" not in job


installed, checked, pip = (step('bash .github/scripts/install-k8s-tools.sh "$K8S_TOOLS"'),
                           step("python infra/tests/check_inference_chart.py"), step("pip install -e '.[dev]'"))
tools_dir = "${{ runner.temp }}/k8s-tools"
checks = {
    "chart creates no Namespace": bool(templates)
        and not any(re.search(r"^kind:\s*Namespace\b", t, re.M) for t in templates.values()),
    "every object in the release namespace": all(
        re.findall(r"^  namespace: .*$", t, re.M) == ["  namespace: {{ .Release.Namespace }}"] for t in templates.values()),
    "values schema: image by repository and digest only, no tag": schema.get("additionalProperties") is False
        and image.get("additionalProperties") is False and set(image["properties"]) == {"repository", "digest"}
        and set(image.get("required", [])) == {"repository", "digest"}
        and image["properties"]["digest"].get("pattern") == "^sha256:[0-9a-f]{64}$"
        and not any(re.fullmatch(image["properties"]["repository"]["pattern"], r) for r in
                    ("registry.example/finrisk:latest", "registry.example/finrisk@sha256:" + "a" * 64, "")),
    "ServiceMonitor off by default": values["serviceMonitor"] == {"enabled": False}
        and templates.get("servicemonitor.yaml", "").startswith("{{- if .Values.serviceMonitor.enabled }}\n")
        and templates["servicemonitor.yaml"].endswith("{{- end }}\n"),
    "install script pins exact versions": all(re.fullmatch(r"v\d+\.\d+\.\d+", pinned.get(k, "")) for k in
                                              ("HELM_VERSION", "KUBECONFORM_VERSION", "PROMETHEUS_OPERATOR_VERSION")),
    "install script verifies every download against a fixed sha256": "set -euo pipefail" in install
        and len(fetched) == 4 and install.count("curl ") == 1
        and 'curl -fsSLo "$1" "$2"\n  echo "$3  $1" | sha256sum --check --strict\n' in install
        and all(re.fullmatch(r"[0-9a-f]{64}", pinned.get(var, "")) for _, var in fetched),
    "CI installs linux-amd64 builds": "helm-${HELM_VERSION}-linux-amd64.tar.gz" in install
        and "kubeconform-linux-amd64.tar.gz" in install,
    "CI installs the pinned tools, then runs the chart acceptance": 0 <= pip < installed < checked
        and plain(installed) and plain(checked)
        and all(job["steps"][i].get("env") == {"K8S_TOOLS": tools_dir} for i in (installed, checked)),
    "CI runs on chart, manifest, test and install script changes": {
        "charts/**", "infra/k8s/**", "infra/tests/**", ".github/scripts/**"} <= set(workflow[True]["pull_request"]["paths"]),
}

failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("Inference chart static acceptance failed: " + ", ".join(failed))
