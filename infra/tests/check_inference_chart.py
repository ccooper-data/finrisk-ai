#!/usr/bin/env python3
# Renders charts/finrisk-inference with the pinned helm and checks the output: helm lint --strict,
# kubeconform -strict against the cluster's Kubernetes schemas and the pinned ServiceMonitor CRD, Pod
# Security restricted (pod_security.py), and parity with infra/k8s/inference.yaml, which the deploy
# build still applies. It needs the tools .github/scripts/install-k8s-tools.sh installs into
# $K8S_TOOLS, so it is not named test_*.py (pytest would collect it, and ci.yml installs no helm);
# terraform-validate.yml runs it after the install. A missing or different tool fails: nothing skips.
import copy
import json
import os
import re
import subprocess
from pathlib import Path

import yaml

from pod_security import restricted

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "charts/finrisk-inference"
INSTALL = (ROOT / ".github/scripts/install-k8s-tools.sh").read_text()
MANIFEST = (ROOT / "infra/k8s/inference.yaml").read_text()
CLUSTER = re.search(r'variable "eks_cluster_version" \{[^}]*default\s*=\s*"([0-9.]+)"',
                    (ROOT / "infra/terraform/variables.tf").read_text())[1]
TOOLS = Path(os.environ.get("K8S_TOOLS") or "/nonexistent")
HELM, KUBECONFORM = TOOLS / "bin/helm", TOOLS / "bin/kubeconform"
if not (HELM.is_file() and KUBECONFORM.is_file()):
    raise SystemExit("Inference chart acceptance needs K8S_TOOLS=<dir> from .github/scripts/install-k8s-tools.sh <dir>")

PINS = dict(re.findall(r'^(\w+_VERSION)="([^"]+)"$', INSTALL, re.M))
# kubeconform's default schema location (yannh/kubernetes-json-schema), pinned to a commit rather than
# master so regenerated schemas cannot change the result. The latest 1.35 patch, as kubectl in deploy_path.tf.
KUBERNETES_VERSION = "1.35.9"
SCHEMAS = ["-schema-location", "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/"
           "8df8a883b68a24a104b4a9e43c1288090ae60b3b/{{ .NormalizedKubernetesVersion }}-standalone{{ .StrictSuffix }}/"
           "{{ .ResourceKind }}{{ .KindSuffix }}.json",
           "-schema-location", str(TOOLS / "schemas/{{ .ResourceKind }}{{ .KindSuffix }}.json")]
REPOSITORY, DIGEST = "780976819607.dkr.ecr.us-east-1.amazonaws.com/finrisk-ai-inference", "sha256:" + "a" * 64
IMAGE = f"{REPOSITORY}@{DIGEST}"
VALUES = ["--set", f"image.repository={REPOSITORY}", "--set", f"image.digest={DIGEST}"]
MONITORED = [*VALUES, "--set", "serviceMonitor.enabled=true"]
# Release names other than the chart's (Argo CD names the release), so a name or selector that followed
# the release would show as drift instead of happening to match the manifest.
RELEASE, OTHER_RELEASE = "finrisk-app", "other-app"
# The only allowed differences from the manifest: these labels on each object's own metadata (never a
# selector or the Pod template), and the image, which the deploy build substitutes for the placeholder.
CHART_LABELS = {"helm.sh/chart", "app.kubernetes.io/name", "app.kubernetes.io/instance",
                "app.kubernetes.io/version", "app.kubernetes.io/managed-by"}
logs = []


def run(*args, stdin=None):
    result = subprocess.run([str(a) for a in args], input=stdin, capture_output=True, text=True, timeout=300)
    if result.returncode:
        logs.append(f"$ {' '.join(map(str, args))}\n{result.stdout}{result.stderr}")
    return result


def render(*args, namespace="finrisk", release=RELEASE):
    """helm template output, as text and as objects; no objects when it fails."""
    out = run(HELM, "template", release, CHART, "--namespace", namespace, *args)
    return out.stdout, [d for d in yaml.safe_load_all(out.stdout) if d] if out.returncode == 0 else []


def refused(*args):
    """helm template stops on the values schema."""
    out = subprocess.run([str(HELM), "template", "x", str(CHART), *args], capture_output=True, text=True, timeout=300)
    return out.returncode != 0 and "values don't meet the specifications of the schema" in out.stderr


def kubeconform(text, count):
    """Every object validated; kubeconform fails on one it has no schema for, and none is skipped."""
    out = run(KUBECONFORM, "-strict", "-summary", "-verbose", "-output", "json",
              "-kubernetes-version", KUBERNETES_VERSION, *SCHEMAS, "-", stdin=text)
    statuses = [r["status"] for r in json.loads(out.stdout or "{}").get("resources", [])]
    return out.returncode == 0 and count > 0 and statuses == ["statusValid"] * count


def by_name(docs):
    return {(d["kind"], d["metadata"]["name"]): d for d in docs}


def comparable(docs):
    """The chart's objects without the allowed labels."""
    docs = copy.deepcopy(docs)
    for d in docs:
        labels = {k: v for k, v in d["metadata"].pop("labels", {}).items() if k not in CHART_LABELS}
        if labels:
            d["metadata"]["labels"] = labels
    return by_name(docs)


def container(template):
    return template["spec"]["containers"][0]


text, chart = render(*VALUES)
monitored_text, monitored = render(*MONITORED)
_, elsewhere = render(*VALUES, namespace="finrisk-elsewhere")
_, renamed = render(*VALUES, release=OTHER_RELEASE)
# The manifest as the deploy build applies it, with the image in place of the placeholder.
deployed = by_name(d for d in yaml.safe_load_all(MANIFEST.replace("FINRISK_IMAGE_PLACEHOLDER", IMAGE)) if d)
objects, with_monitor = by_name(chart), by_name(monitored)
service = objects.get(("Service", "finrisk-inference"), {"metadata": {}, "spec": {}})
monitor = with_monitor.get(("ServiceMonitor", "finrisk-inference"), {"metadata": {}, "spec": {}})
templates = [d["spec"]["template"] for d in chart if "template" in (d.get("spec") or {})]
results = [restricted(t) for t in templates]


def drift(change):
    """Whether the parity check sees one change to the chart's Pod template."""
    docs = copy.deepcopy(chart)
    change(next(d for d in docs if d["kind"] == "Deployment")["spec"]["template"])
    return comparable(docs) != deployed


checks = {
    "pinned helm": run(HELM, "version", "--template", "{{.Version}}").stdout == PINS.get("HELM_VERSION"),
    "pinned kubeconform": run(KUBECONFORM, "-v").stdout.strip() == PINS.get("KUBECONFORM_VERSION"),
    "schemas are the cluster's Kubernetes minor (variables.tf)": KUBERNETES_VERSION.startswith(CLUSTER + "."),
    "helm lint --strict": run(HELM, "lint", "--strict", CHART, *VALUES).returncode == 0,
    "helm lint --strict with the ServiceMonitor": run(HELM, "lint", "--strict", CHART, *MONITORED).returncode == 0,
    "renders the manifest's Deployment, Service and HPA by default": len(objects) == len(chart)
        and sorted(objects) == sorted(deployed),
    "the ServiceMonitor adds itself and changes nothing else": bool(objects)
        and with_monitor == {**objects, ("ServiceMonitor", "finrisk-inference"): monitor},
    "no Namespace; every object in the release namespace": bool(elsewhere)
        and all(d["kind"] != "Namespace" and d["metadata"]["namespace"] == "finrisk-elsewhere" for d in elsewhere),
    "another release name changes nothing but the allowed labels": bool(renamed) and comparable(renamed) == comparable(chart),
    "Deployment selector is the manifest's app: finrisk-inference (immutable)":
        [d["spec"]["selector"] for d in chart if d["kind"] == "Deployment"] == [{"matchLabels": {"app": "finrisk-inference"}}],
    f"kubeconform -strict, Kubernetes {KUBERNETES_VERSION}": kubeconform(text, len(chart)),
    "kubeconform -strict with the ServiceMonitor (pinned CRD schema)": kubeconform(monitored_text, len(monitored)),
    "chart renders a Pod template": bool(templates),
    **{name: all(r[name] for r in results) for name in (results[0] if results else {})},
    "image by digest": [container(t)["image"] for t in templates] == [IMAGE],
    "no render without an image": refused(),
    **{f"values schema rejects {name}": refused(*VALUES, "--set", value) for name, value in {
        "an image tag": "image.tag=latest",
        "a tag in the repository": f"image.repository={REPOSITORY}:latest",
        "a digest in the repository": f"image.repository={IMAGE}",
        "a malformed digest": "image.digest=sha256:" + "A" * 64,
        "an unknown value": "replicaCount=2",
    }.items()},
    "ServiceMonitor scrapes /metrics on a named Service port":
        monitor["spec"].get("endpoints") == [{"port": "http", "path": "/metrics"}]
        and "http" in [p.get("name") for p in service["spec"].get("ports", [])],
    # A rollout undo restores only the Deployment; a target by name would miss an older Pod template.
    "Service targets the container port by number": bool(templates)
        and [p.get("targetPort") for p in service["spec"].get("ports", [])]
        == [p["containerPort"] for t in templates for p in container(t).get("ports", [])],
    "ServiceMonitor selects the Service, in its namespace": "namespaceSelector" not in monitor["spec"]
        and monitor["metadata"].get("namespace", "") == service["metadata"].get("namespace")
        # matchLabels only: matchExpressions could exclude the Service.
        and set(monitor["spec"].get("selector", {})) == {"matchLabels"}
        and bool(monitor["spec"]["selector"]["matchLabels"])
        and monitor["spec"]["selector"]["matchLabels"].items() <= service["metadata"].get("labels", {}).items(),
    "same objects as infra/k8s/inference.yaml, apart from the allowed labels": bool(chart)
        and comparable(chart) == deployed,
    # Not vacuous: a change outside the allowed differences shows.
    "parity sees a probe, resource or Pod template label change": bool(chart)
        and drift(lambda t: container(t)["readinessProbe"].update(periodSeconds=11))
        and drift(lambda t: container(t)["resources"]["limits"].update(memory="1Gi"))
        and drift(lambda t: t["metadata"]["labels"].update({"app.kubernetes.io/name": "finrisk-inference"})),
}

failed = [k for k, v in checks.items() if not v]
if failed:
    print("\n".join(logs))
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("Inference chart acceptance failed: " + ", ".join(failed))
