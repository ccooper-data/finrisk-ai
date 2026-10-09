#!/usr/bin/env python3
# Renders charts/finrisk-inference with the pinned helm and checks the output: helm lint --strict,
# kubeconform -strict against the cluster's Kubernetes schemas and the pinned ServiceMonitor CRD, Pod
# Security restricted (pod_security.py), the finrisk AppProject's limits (Argo CD syncs it with the
# ServiceMonitor on), and the wiring the deploy build relies on (the smoke test's Service address, the
# port the image listens on, the container it execs into). The chart is the only deploy artifact. It
# needs the tools .github/scripts/install-k8s-tools.sh installs into $K8S_TOOLS, so it is not named
# test_*.py (pytest would collect it, and ci.yml installs no helm); terraform-validate.yml runs it after
# the install. A missing or different tool fails: nothing skips.
import copy
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml

from pod_security import restricted

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "charts/finrisk-inference"
INSTALL = (ROOT / ".github/scripts/install-k8s-tools.sh").read_text()
APPLICATION = next(d for d in yaml.safe_load_all((ROOT / "infra/k8s/inference-app.yaml").read_text()) if d and d["kind"] == "Application")
PROJECT = next(d for d in yaml.safe_load_all((ROOT / "infra/k8s/argocd-projects.yaml").read_text())
               if d and d["metadata"]["name"] == APPLICATION["spec"]["project"])
DEPLOY = (ROOT / "infra/terraform/deploy/deploy-buildspec.yml.tftpl").read_text()
PATH_TF = (ROOT / "infra/terraform/deploy_path.tf").read_text()
LISTEN_PORT = int(re.search(r'"--port", "(\d+)"', (ROOT / "Dockerfile").read_text())[1])
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
# Release names other than the chart's, so a name or selector that followed the release would show.
RELEASE, OTHER_RELEASE = "finrisk-app", "other-app"
# The only labels another release name may change: each object's own metadata, never a selector or the Pod template.
CHART_LABELS = {"helm.sh/chart", "app.kubernetes.io/name", "app.kubernetes.io/instance",
                "app.kubernetes.io/version", "app.kubernetes.io/managed-by"}
# The deploy build's names: the Deployment and Service it addresses, the container it execs into, and the
# smoke test's Service address (http://<app>.<namespace>.svc.cluster.local, port 80).
APP = re.search(r'k8s_app_name\s+= "([^"]+)"', PATH_TF)[1]
CLUSTER_SCOPED = {"Namespace", "ClusterRole", "ClusterRoleBinding", "CustomResourceDefinition", "PersistentVolume",
                  "StorageClass", "PriorityClass", "ValidatingWebhookConfiguration", "MutatingWebhookConfiguration"}
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


def fits_project(docs):
    """Argo CD's AppProject rule for the finrisk project: namespaced kinds by group and kind, into its
    destination; it whitelists nothing cluster-scoped."""
    spec = PROJECT["spec"]
    return bool(docs) and spec["clusterResourceWhitelist"] == [] and all(
        d["kind"] not in CLUSTER_SCOPED and {"group": d["apiVersion"].rpartition("/")[0], "kind": d["kind"]}
        in spec["namespaceResourceWhitelist"] and {"server": "https://kubernetes.default.svc", "namespace": d["metadata"]["namespace"]}
        in spec["destinations"] for d in docs)


def wired(docs):
    """The smoke test reaches the image through Service <app> port 80, which targets the port the image
    listens on, and the deploy execs into container "inference"; the HPA alone sets the replica count."""
    by = by_name(docs)
    deployment, service = by.get(("Deployment", APP)), by.get(("Service", APP))
    if not deployment or not service:
        return False
    template, selector = deployment["spec"]["template"], service["spec"].get("selector") or {}
    containers = template["spec"]["containers"]
    return 'BASE = "http://${app}.${namespace}.svc.cluster.local"' in DEPLOY and "-c inference -- python -" in DEPLOY \
        and [c["name"] for c in containers] == ["inference"] \
        and [p["containerPort"] for c in containers for p in c.get("ports", [])] == [LISTEN_PORT] \
        and [(p["port"], p.get("targetPort")) for p in service["spec"]["ports"]] == [(80, LISTEN_PORT)] \
        and bool(selector) and selector.items() <= template["metadata"]["labels"].items() \
        and "replicas" not in deployment["spec"]


def changed(docs, change):
    docs = copy.deepcopy(docs)
    change(by_name(docs))
    return docs


# As Argo CD renders the Application: its valuesObject (the bootstrap's repository in place of the
# placeholder) as a values file, and the deploy's image.digest parameter as --set-string.
with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as values_file:
    yaml.safe_dump(json.loads(json.dumps(APPLICATION["spec"]["source"]["helm"]["valuesObject"]).replace(
        '"IMAGE_REPOSITORY"', json.dumps(REPOSITORY))), values_file)
try:
    _, as_argocd = render("--values", values_file.name, "--set-string", f"image.digest={DIGEST}",
                          release=APPLICATION["spec"]["source"]["helm"]["releaseName"])
    before_first_digest = refused("--values", values_file.name)
finally:
    os.unlink(values_file.name)
text, chart = render(*VALUES)
monitored_text, monitored = render(*MONITORED)
_, elsewhere = render(*VALUES, namespace="finrisk-elsewhere")
_, renamed = render(*VALUES, release=OTHER_RELEASE)
objects, with_monitor = by_name(chart), by_name(monitored)
service = objects.get(("Service", "finrisk-inference"), {"metadata": {}, "spec": {}})
monitor = with_monitor.get(("ServiceMonitor", "finrisk-inference"), {"metadata": {}, "spec": {}})
templates = [d["spec"]["template"] for d in chart if "template" in (d.get("spec") or {})]
results = [restricted(t) for t in templates]


checks = {
    "pinned helm": run(HELM, "version", "--template", "{{.Version}}").stdout == PINS.get("HELM_VERSION"),
    "pinned kubeconform": run(KUBECONFORM, "-v").stdout.strip() == PINS.get("KUBECONFORM_VERSION"),
    "schemas are the cluster's Kubernetes minor (variables.tf)": KUBERNETES_VERSION.startswith(CLUSTER + "."),
    "helm lint --strict": run(HELM, "lint", "--strict", CHART, *VALUES).returncode == 0,
    "helm lint --strict with the ServiceMonitor": run(HELM, "lint", "--strict", CHART, *MONITORED).returncode == 0,
    "renders the Deployment, Service and HPA by default": len(objects) == len(chart) and sorted(objects)
        == [("Deployment", APP), ("HorizontalPodAutoscaler", APP), ("Service", APP)],
    "the ServiceMonitor adds itself and changes nothing else": bool(objects)
        and with_monitor == {**objects, ("ServiceMonitor", "finrisk-inference"): monitor},
    "no Namespace; every object in the release namespace": bool(elsewhere)
        and all(d["kind"] != "Namespace" and d["metadata"]["namespace"] == "finrisk-elsewhere" for d in elsewhere),
    "another release name changes nothing but the allowed labels": bool(renamed) and comparable(renamed) == comparable(chart),
    "Deployment selector is app: finrisk-inference (immutable)":
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
    "as Argo CD renders the Application with the deploy's digest: the ServiceMonitor render": bool(as_argocd)
        and by_name(as_argocd) == by_name(render(*MONITORED, release=APPLICATION["spec"]["source"]["helm"]["releaseName"])[1]),
    "before the first digest the Application's values do not render (nothing to deploy)": before_first_digest,
    # Argo CD syncs the chart with the ServiceMonitor on, under the finrisk AppProject.
    "with the ServiceMonitor, every object fits the finrisk AppProject (its kinds, into finrisk)": fits_project(monitored),
    "negative control: a kind outside the project (a ConfigMap) is caught": not fits_project(
        monitored + [{"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "x", "namespace": "finrisk"}}]),
    "negative control: another namespace is caught": not fits_project(
        changed(monitored, lambda b: b[("Service", APP)]["metadata"].update(namespace="default"))),
    "the deploy build's wiring: Service port 80 to the image's port, container inference, no replicas": wired(chart),
    **{f"negative control: {name} is caught": not wired(changed(chart, change)) for name, change in {
        "a renamed container": lambda b: container(b[("Deployment", APP)]["spec"]["template"]).update(name="app"),
        "another Service port": lambda b: b[("Service", APP)]["spec"]["ports"][0].update(port=8080),
        "a targetPort the image does not listen on": lambda b: b[("Service", APP)]["spec"]["ports"][0].update(targetPort=8001),
        "a fixed replica count": lambda b: b[("Deployment", APP)]["spec"].update(replicas=2),
        "a selector that misses the Pods": lambda b: b[("Service", APP)]["spec"].update(selector={"app": "other"}),
    }.items()},
}

failed = [k for k, v in checks.items() if not v]
if failed:
    print("\n".join(logs))
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("Inference chart acceptance failed: " + ", ".join(failed))
