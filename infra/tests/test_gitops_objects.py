#!/usr/bin/env python3
# The GitOps deploy objects without tools: the finrisk AppProject, the inference Application and the
# digest writer's Role and RoleBinding (infra/k8s/inference-app.yaml), and how they line up with
# Terraform, the bootstrap that fills in the placeholders, and the chart. Every property is also checked
# against a deliberately broken copy and must fail there. kubeconform validates the objects against the
# Argo CD CRDs in check_argocd_install.py; the deploy build's use of them runs in
# test_deploy_buildspec_runtime.py.
import copy
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
K8S = ROOT / "infra/k8s"
TF = (ROOT / "infra/terraform/deploy_path.tf").read_text()
VARIABLES = (ROOT / "infra/terraform/variables.tf").read_text()
BOOTSTRAP = (ROOT / "infra/terraform/deploy/bootstrap-buildspec.yml.tftpl").read_text()
APP_TEXT = (K8S / "inference-app.yaml").read_text()
OBJECTS = [d for d in yaml.safe_load_all(APP_TEXT) if d]
PROJECTS = [d for d in yaml.safe_load_all((K8S / "argocd-projects.yaml").read_text()) if d]
ARGOCD_VALUES = yaml.safe_load((K8S / "argocd-values.yaml").read_text())
CHART = ROOT / "charts/finrisk-inference"
SCHEMA = json.loads((CHART / "values.schema.json").read_text())
CHART_VALUES = yaml.safe_load((CHART / "values.yaml").read_text())
IN_CLUSTER = "https://kubernetes.default.svc"
REPOSITORY = "780976819607.dkr.ecr.us-east-1.amazonaws.com/finrisk-ai-inference"
PLACEHOLDERS = {"GITOPS_REVISION": "targetRevision", "IMAGE_REPOSITORY": "repository"}


def local(name):
    match = re.search(rf'^  {name}\s+= "([^"]*)"$', TF, re.M)
    return match[1] if match else None


REPO_URL = (local("gitops_repo_url") or "").replace(
    "${var.github_repository}", re.search(r'variable "github_repository" \{[^}]*default\s+= "([^"]+)"', VARIABLES)[1])
NAMESPACE, APP_NAME, GROUP, CHART_PATH = (local(n) for n in ("k8s_app_namespace", "k8s_app_name", "k8s_digest_writer_group",
                                                              "gitops_chart_path"))
KINDS = [{"group": "apps", "kind": "Deployment"}, {"group": "", "kind": "Service"},
         {"group": "autoscaling", "kind": "HorizontalPodAutoscaler"}, {"group": "monitoring.coreos.com", "kind": "ServiceMonitor"}]


def kind(objects, name):
    return next((d for d in objects if d["kind"] == name), {})


def properties(objects, projects):
    app, role, binding = kind(objects, "Application"), kind(objects, "Role"), kind(objects, "RoleBinding")
    spec = app.get("spec", {})
    source, sync = spec.get("source", {}), spec.get("syncPolicy", {})
    helm = source.get("helm", {})
    project = next((p.get("spec", {}) for p in projects if p["metadata"]["name"] == "finrisk"), {})
    return {
        "inference-app.yaml holds only the Role, its RoleBinding and the Application, all in finrisk":
            [d["kind"] for d in objects] == ["Role", "RoleBinding", "Application"]
            and all(d["metadata"].get("namespace") == NAMESPACE == "finrisk" for d in objects),
        "Role: get, watch and patch on the one Application, nothing else (no create, delete or list)":
            role.get("rules") == [{"apiGroups": ["argoproj.io"], "resources": ["applications"], "resourceNames": [APP_NAME],
                                   "verbs": ["get", "watch", "patch"]}],
        "RoleBinding: the Role to the access entry's group only (no ServiceAccount: Edit can impersonate those)":
            binding.get("roleRef") == {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": role.get("metadata", {}).get("name")}
            and binding.get("subjects") == [{"apiGroup": "rbac.authorization.k8s.io", "kind": "Group", "name": GROUP}]
            and GROUP == "finrisk-digest-writer",
        "Application finrisk/finrisk-inference in project finrisk, into finrisk in-cluster":
            app.get("metadata", {}).get("name") == APP_NAME and spec.get("project") == "finrisk"
            and spec.get("destination") == {"server": IN_CLUSTER, "namespace": NAMESPACE},
        "source: this repository's chart at the commit the bootstrap fills in": source.get("repoURL") == REPO_URL
            and source.get("path") == CHART_PATH and source.get("targetRevision") == "GITOPS_REVISION" and "sources" not in spec,
        "Helm: release name and values only; the repository from the bootstrap, the ServiceMonitor on; no parameters":
            helm == {"releaseName": APP_NAME, "valuesObject": {"image": {"repository": "IMAGE_REPOSITORY"},
                                                               "serviceMonitor": {"enabled": True}}},
        "automated sync with prune and self-heal, never sharing an object, bounded retry; no CreateNamespace":
            sync.get("automated") == {"enabled": True, "prune": True, "selfHeal": True}
            and sync.get("syncOptions") == ["FailOnSharedResource=true"]
            and sync.get("retry") == {"limit": 3, "backoff": {"duration": "10s", "factor": 2, "maxDuration": "1m"}},
        "no finalizer: a failed first deploy stays until DESTROY, and nothing cascades": "finalizers" not in app.get("metadata", {}),
        "AppProject finrisk: Applications from finrisk only, this repository, into finrisk":
            project.get("sourceNamespaces") == ["finrisk"] and project.get("sourceRepos") == [REPO_URL]
            and project.get("destinations") == [{"server": IN_CLUSTER, "namespace": NAMESPACE}],
        "AppProject finrisk: nothing cluster-scoped, only the chart's four kinds": project.get("clusterResourceWhitelist") == []
            and project.get("namespaceResourceWhitelist") == KINDS,
    }


def placeholders_filled(text, bootstrap):
    """Each placeholder appears once, as a whole value, and the bootstrap's sed replaces it before the apply."""
    return all(len(re.findall(rf'^\s+{key}: "{p}"$', text, re.M)) == 1 == text.count(p) for p, key in PLACEHOLDERS.items()) \
        and all(f'-e "s#{p}#$' in bootstrap for p in PLACEHOLDERS) \
        and bootstrap.find("/tmp/finrisk/inference-app.yaml > /tmp/finrisk/gitops.yaml") < bootstrap.find("apply gitops.yaml")


def broken(change, objects=OBJECTS, projects=PROJECTS):
    objects, projects = copy.deepcopy(objects), copy.deepcopy(projects)
    change(objects, projects)
    return properties(objects, projects)


def app(o):
    return kind(o, "Application")


def finrisk(p):
    return next(x["spec"] for x in p if x["metadata"]["name"] == "finrisk")


CONTROLS = {
    "create on the Role": (lambda o, p: kind(o, "Role")["rules"][0]["verbs"].append("create"),
                           "Role: get, watch and patch on the one Application, nothing else (no create, delete or list)"),
    "the Role on every Application": (lambda o, p: kind(o, "Role")["rules"][0].pop("resourceNames"),
                                      "Role: get, watch and patch on the one Application, nothing else (no create, delete or list)"),
    "a second Role rule": (lambda o, p: kind(o, "Role")["rules"].append({"apiGroups": [""], "resources": ["secrets"], "verbs": ["get"]}),
                           "Role: get, watch and patch on the one Application, nothing else (no create, delete or list)"),
    "a ServiceAccount subject": (lambda o, p: kind(o, "RoleBinding")["subjects"].append(
        {"kind": "ServiceAccount", "name": "default", "namespace": "finrisk"}),
        "RoleBinding: the Role to the access entry's group only (no ServiceAccount: Edit can impersonate those)"),
    "a ServiceAccount in the file": (lambda o, p: o.insert(0, {"apiVersion": "v1", "kind": "ServiceAccount",
                                                               "metadata": {"name": "writer", "namespace": "finrisk"}}),
                                     "inference-app.yaml holds only the Role, its RoleBinding and the Application, all in finrisk"),
    "the Application in argocd": (lambda o, p: app(o)["metadata"].update(namespace="argocd"),
                                  "inference-app.yaml holds only the Role, its RoleBinding and the Application, all in finrisk"),
    "the default project": (lambda o, p: app(o)["spec"].update(project="default"),
                            "Application finrisk/finrisk-inference in project finrisk, into finrisk in-cluster"),
    "a branch instead of the commit": (lambda o, p: app(o)["spec"]["source"].update(targetRevision="main"),
                                       "source: this repository's chart at the commit the bootstrap fills in"),
    "Helm parameters (a digest the bootstrap would own)": (
        lambda o, p: app(o)["spec"]["source"]["helm"].update(parameters=[{"name": "image.digest", "value": "sha256:" + "a" * 64}]),
        "Helm: release name and values only; the repository from the bootstrap, the ServiceMonitor on; no parameters"),
    "an image tag value": (lambda o, p: app(o)["spec"]["source"]["helm"]["valuesObject"]["image"].update(tag="latest"),
                           "Helm: release name and values only; the repository from the bootstrap, the ServiceMonitor on; no parameters"),
    "self-heal off": (lambda o, p: app(o)["spec"]["syncPolicy"]["automated"].update(selfHeal=False),
                      "automated sync with prune and self-heal, never sharing an object, bounded retry; no CreateNamespace"),
    "CreateNamespace=true": (lambda o, p: app(o)["spec"]["syncPolicy"]["syncOptions"].append("CreateNamespace=true"),
                             "automated sync with prune and self-heal, never sharing an object, bounded retry; no CreateNamespace"),
    "a resources finalizer": (lambda o, p: app(o)["metadata"].update(finalizers=["resources-finalizer.argocd.argoproj.io"]),
                              "no finalizer: a failed first deploy stays until DESTROY, and nothing cascades"),
    "argocd in the project's sourceNamespaces": (lambda o, p: finrisk(p)["sourceNamespaces"].append("argocd"),
                                                 "AppProject finrisk: Applications from finrisk only, this repository, into finrisk"),
    "any repository": (lambda o, p: finrisk(p)["sourceRepos"].append("*"),
                       "AppProject finrisk: Applications from finrisk only, this repository, into finrisk"),
    "any namespace": (lambda o, p: finrisk(p)["destinations"][0].update(namespace="*"),
                      "AppProject finrisk: Applications from finrisk only, this repository, into finrisk"),
    "a cluster-scoped Namespace": (lambda o, p: finrisk(p)["clusterResourceWhitelist"].append({"group": "", "kind": "Namespace"}),
                                   "AppProject finrisk: nothing cluster-scoped, only the chart's four kinds"),
    "Secrets": (lambda o, p: finrisk(p)["namespaceResourceWhitelist"].append({"group": "", "kind": "Secret"}),
                "AppProject finrisk: nothing cluster-scoped, only the chart's four kinds"),
    "every namespaced kind (no list)": (lambda o, p: finrisk(p).pop("namespaceResourceWhitelist"),
                                        "AppProject finrisk: nothing cluster-scoped, only the chart's four kinds"),
}

found = properties(OBJECTS, PROJECTS)
image = SCHEMA["properties"]["image"]
checks = {
    **found,
    "each placeholder once, as a whole quoted value, replaced by the bootstrap's sed before the apply":
        placeholders_filled(APP_TEXT, BOOTSTRAP),
    # Unquoted, a commit of digits only (or digits around one "e") would load as a number.
    "the filled-in commit stays a string even when it is all digits": isinstance(app(
        [d for d in yaml.safe_load_all(APP_TEXT.replace("GITOPS_REVISION", "0" * 40)) if d])["spec"]["source"]["targetRevision"], str),
    # Before the deploy sets image.digest the chart cannot render, so Argo CD deploys nothing.
    "without image.digest the chart does not render (values schema): nothing deploys before the first digest":
        "digest" in image.get("required", []) and CHART_VALUES["image"]["digest"] == ""
        and re.fullmatch(image["properties"]["digest"]["pattern"], "") is None,
    "the Application's values are the chart's, and the filled-in repository passes its schema":
        set(app(OBJECTS)["spec"]["source"]["helm"]["valuesObject"]) <= set(SCHEMA["properties"])
        and re.fullmatch(image["properties"]["repository"]["pattern"], REPOSITORY) is not None,
    "Argo CD watches Applications in finrisk (applications in any namespace)":
        ARGOCD_VALUES["configs"]["params"]["application.namespaces"] == NAMESPACE,
    "Terraform's GitOps values match the objects: repository URL, chart path, namespace, name, group":
        REPO_URL == "https://github.com/ccooper-data/finrisk-ai.git" and CHART_PATH == "charts/finrisk-inference"
        and (NAMESPACE, APP_NAME, GROUP) == ("finrisk", "finrisk-inference", "finrisk-digest-writer"),
}
for name, (change, prop) in CONTROLS.items():
    checks[f"negative control: {name} fails '{prop}'"] = found[prop] and not broken(change)[prop]
twice = APP_TEXT.replace("    path: charts/finrisk-inference", "    path: charts/finrisk-inference\n    # GITOPS_REVISION", 1)
checks["negative control: a placeholder twice is caught"] = twice != APP_TEXT and not placeholders_filled(twice, BOOTSTRAP)
checks["negative control: a placeholder the bootstrap does not replace is caught"] = not placeholders_filled(
    APP_TEXT, BOOTSTRAP.replace('-e "s#IMAGE_REPOSITORY#$R#"', ""))
checks["negative control: an unquoted placeholder is caught"] = not placeholders_filled(
    APP_TEXT.replace('"GITOPS_REVISION"', "GITOPS_REVISION"), BOOTSTRAP)

failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("GitOps objects acceptance failed: " + ", ".join(failed))
