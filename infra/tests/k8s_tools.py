# Shared by the check_*.py scripts for the cluster add-ons: the pinned tools and charts that
# .github/scripts/install-k8s-tools.sh installs into $K8S_TOOLS, helm and kubeconform runners, and
# the platform manifests in infra/k8s. A missing or different tool fails: nothing skips.
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
K8S = ROOT / "infra/k8s"
INSTALL = (ROOT / ".github/scripts/install-k8s-tools.sh").read_text()
PINS = dict(re.findall(r'^(\w+)="([^"]+)"$', INSTALL, re.M))
TOOLS = Path(os.environ.get("K8S_TOOLS") or "/nonexistent")
HELM, KUBECONFORM = TOOLS / "bin/helm", TOOLS / "bin/kubeconform"
ARGOCD_CHART, MONITORING_CHART = TOOLS / "charts/argo-cd.tgz", TOOLS / "charts/kube-prometheus-stack.tgz"
MONITORING_MANIFEST = TOOLS / "charts/kube-prometheus-stack.oci-manifest.json"
# As check_inference_chart.py: the cluster's Kubernetes schemas at a pinned commit, then the CRD
# schemas the install script converted (ServiceMonitor, Argo CD Application and AppProject).
KUBERNETES_VERSION = "1.35.9"
SCHEMAS = ["-schema-location", "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/"
           "8df8a883b68a24a104b4a9e43c1288090ae60b3b/{{ .NormalizedKubernetesVersion }}-standalone{{ .StrictSuffix }}/"
           "{{ .ResourceKind }}{{ .KindSuffix }}.json",
           "-schema-location", str(TOOLS / "schemas/{{ .ResourceKind }}{{ .KindSuffix }}.json")]
DIGEST = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")
logs = []


def require(name):
    if not all(p.is_file() for p in (HELM, KUBECONFORM, ARGOCD_CHART, MONITORING_CHART, MONITORING_MANIFEST)):
        raise SystemExit(f"{name} needs K8S_TOOLS=<dir> from .github/scripts/install-k8s-tools.sh <dir>")


class Loader(yaml.SafeLoader):
    """Rendered CRDs list a bare `=` (an enum value), which PyYAML would read as its unsupported value tag."""


Loader.add_constructor("tag:yaml.org,2002:value", Loader.construct_yaml_str)


def load_all(text):
    return [d for d in yaml.load_all(text, Loader=Loader) if d]


def manifest(name):
    return load_all((K8S / name).read_text())


def run(*args, stdin=None):
    result = subprocess.run([str(a) for a in args], input=stdin, capture_output=True, text=True, timeout=300)
    if result.returncode:
        logs.append(f"$ {' '.join(map(str, args))}\n{result.stdout}{result.stderr}")
    return result


def template(chart, release, namespace, values, *extra):
    """helm template with these values, as text and objects; no objects when it fails."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(values, f)
    try:
        out = run(HELM, "template", release, chart, "--namespace", namespace, "--values", f.name, *extra)
    finally:
        os.unlink(f.name)
    return out.stdout, load_all(out.stdout) if out.returncode == 0 else []


def argocd(values):
    return template(ARGOCD_CHART, "argocd", "argocd", values)


def monitoring(values):
    # Argo CD renders Helm sources with --include-crds unless the source says skipCrds.
    return template(MONITORING_CHART, "monitoring", "monitoring", values, "--include-crds")


def kubeconform(text, count):
    """Every object validated; kubeconform fails on one it has no schema for, and none is skipped."""
    out = run(KUBECONFORM, "-strict", "-summary", "-verbose", "-output", "json",
              "-kubernetes-version", KUBERNETES_VERSION, *SCHEMAS, "-", stdin=text)
    statuses = [r["status"] for r in json.loads(out.stdout or "{}").get("resources", [])]
    return out.returncode == 0 and count > 0 and statuses == ["statusValid"] * count


def pod_templates(docs):
    return [(d["kind"], d["metadata"]["name"], d["spec"]["template"]) for d in docs
            if "template" in (d.get("spec") or {}) and "spec" in d["spec"]["template"]]


def containers(template):
    spec = template["spec"]
    return [c for key in ("initContainers", "containers") for c in spec.get(key) or []]


def report(title, checks):
    failed = [k for k, v in checks.items() if not v]
    if failed:
        print("\n".join(logs))
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'}: {k}")
    if failed:
        raise SystemExit(f"{title} failed: " + ", ".join(failed))
