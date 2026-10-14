#!/usr/bin/env python3
# Renders the pinned argo-cd chart with infra/k8s/argocd-values.yaml, as the bootstrap build installs
# it, and checks what the bootstrap and the AppProjects rely on: digest-pinned images, Pod Security
# restricted, nothing exposed, a headless install, and no cluster rights beyond the application
# controller's. Every property is also checked against a deliberately broken copy of the values and
# must fail there. kubeconform -strict validates the render, and the AppProjects and Applications in
# infra/k8s against the chart's own CRDs (with the digest writer's Role and RoleBinding against the
# Kubernetes schemas). It needs the tools .github/scripts/install-k8s-tools.sh
# installs into $K8S_TOOLS, so it is not named test_*.py; terraform-validate.yml runs it after the install.
import copy
import hashlib
import re

import yaml

from k8s_tools import (ARGOCD_CHART, DIGEST, HELM, K8S, KUBECONFORM, PINS, ROOT, argocd, containers, kubeconform,
                       load_all, manifest, pod_templates, report, require, run)
from pod_security import restricted

require("Argo CD install acceptance")
VALUES = yaml.safe_load((K8S / "argocd-values.yaml").read_text())
IMAGES = {f'{VALUES["global"]["image"]["repository"]}:{VALUES["global"]["image"]["tag"]}',
          f'{VALUES["redis"]["image"]["repository"]}:{VALUES["redis"]["image"]["tag"]}'}
APP_NAMESPACE = re.search(r'k8s_app_namespace\s+= "([^"]+)"', (ROOT / "infra/terraform/deploy_path.tf").read_text())[1]
RUNNING = {("StatefulSet", "argocd-application-controller"), ("Deployment", "argocd-repo-server"),
           ("Deployment", "argocd-redis")}
STOPPED = {("Deployment", "argocd-server"), ("Deployment", "argocd-applicationset-controller")}
UNEXPOSED = {"Ingress", "HTTPRoute", "GRPCRoute", "Route", "Gateway", "NetworkPolicy", "PersistentVolumeClaim"}


def properties(docs):
    """What the bootstrap and the AppProjects rely on, by name; each is False when it does not hold."""
    by = {(d["kind"], d["metadata"]["name"]): d for d in docs}
    templates = pod_templates(docs)
    every = [c for _, _, t in templates for c in containers(t)]
    # Pods that run: the hook Job and every workload not scaled to zero.
    running = [c for kind, name, t in templates if (by[(kind, name)]["spec"].get("replicas", 1) != 0)
               for c in containers(t)]
    services = [d for d in docs if d["kind"] == "Service"]
    roles = [d for d in docs if d["kind"] == "ClusterRole"]

    def data(name):
        return (by.get(("ConfigMap", name)) or {}).get("data") or {}

    def replicas(key):
        return (by.get(key) or {}).get("spec", {}).get("replicas")

    def env(key, name):
        spec = (by.get(key) or {}).get("spec", {}).get("template", {"spec": {}})
        return next((e.get("valueFrom") or {} for c in containers(spec) for e in c.get("env") or [] if e["name"] == name), {})

    hook_job = [d for d in docs if d["kind"] == "Job"]
    cm = data("argocd-cm")
    return {
        "renders": bool(docs),
        "images are exactly the two digest-pinned ones": {c["image"] for c in every} == IMAGES
            and all(DIGEST.fullmatch(i) for i in IMAGES),
        "every Pod template, the hook Job's included, meets Pod Security restricted": bool(templates)
            and all(all(restricted(t).values()) for _, _, t in templates),
        "Services are ClusterIP only, without externalIPs": bool(services)
            and all(s["spec"].get("type", "ClusterIP") == "ClusterIP" and not s["spec"].get("externalIPs") for s in services),
        "no Ingress, route, NetworkPolicy or PersistentVolumeClaim": not {d["kind"] for d in docs} & UNEXPOSED,
        "API server and ApplicationSet controller at zero replicas": all(replicas(k) == 0 for k in STOPPED),
        "application controller, repo-server and Redis one replica each": all(replicas(k) == 1 for k in RUNNING),
        "no Dex or notifications controller": not any(re.search(r"dex|notifications", name) for kind, name in by
                                                      if kind in {"Deployment", "StatefulSet", "Service"}),
        "argocd-cm: admin, anonymous access and exec off": (cm.get("admin.enabled"), cm.get("users.anonymous.enabled"),
                                                            cm.get("exec.enabled")) == ("false", "false", "false"),
        "applications in any namespace: finrisk only, wired into the controller":
            data("argocd-cmd-params-cm").get("application.namespaces") == APP_NAMESPACE
            and env(("StatefulSet", "argocd-application-controller"), "ARGOCD_APPLICATION_NAMESPACES").get(
                "configMapKeyRef") == {"name": "argocd-cmd-params-cm", "key": "application.namespaces", "optional": True},
        "no ClusterRole aggregates into admin, edit or view": not any(
            k.startswith("rbac.authorization.k8s.io/aggregate-to-") for d in roles for k in d["metadata"].get("labels") or {}),
        # The controller's is cluster-admin equivalent (stated in infra/k8s/argocd-projects.yaml); the
        # never-running API server keeps an empty one.
        "only the application controller's ClusterRole grants anything": sorted(d["metadata"]["name"] for d in roles)
            == ["argocd-application-controller", "argocd-server"]
            and [d["metadata"]["name"] for d in roles if d.get("rules")] == ["argocd-application-controller"],
        "Redis requires the password from Secret argocd-redis, created by the hook Job":
            env(("Deployment", "argocd-redis"), "REDIS_PASSWORD").get("secretKeyRef", {}).get("name") == "argocd-redis"
            and [j["metadata"]["annotations"].get("helm.sh/hook") for j in hook_job] == ["pre-install,pre-upgrade"],
        # The capacity budget (check_capacity_budget.py) adds up requests; a container without them hides load.
        "every container that runs requests CPU and memory and has a memory limit": bool(running) and all(
            {"cpu", "memory"} <= set((c.get("resources") or {}).get("requests") or {})
            and "memory" in ((c.get("resources") or {}).get("limits") or {}) for c in running),
        "CRDs: Application, AppProject, ApplicationSet": sorted(d["metadata"]["name"] for d in docs
                                                                if d["kind"] == "CustomResourceDefinition")
            == ["applications.argoproj.io", "applicationsets.argoproj.io", "appprojects.argoproj.io"],
    }


def broken(change):
    values = copy.deepcopy(VALUES)
    change(values)
    return values


# One deliberately broken copy per property: the property must fail on it, and the copy must still
# render, or the control proves nothing.
CONTROLS = {
    "the Argo CD image by tag only": (lambda v: v["global"]["image"].update(tag="v3.5.3"),
                                      "images are exactly the two digest-pinned ones"),
    "the Redis image by tag only": (lambda v: v["redis"]["image"].update(tag="8.6.4-alpine"),
                                    "images are exactly the two digest-pinned ones"),
    "a container allowed to run as root": (lambda v: v["controller"].update(containerSecurityContext={"runAsNonRoot": False}),
                                           "every Pod template, the hook Job's included, meets Pod Security restricted"),
    "a LoadBalancer API server Service": (lambda v: v["server"].update(service={"type": "LoadBalancer"}),
                                          "Services are ClusterIP only, without externalIPs"),
    "an API server Ingress": (lambda v: v["server"].update(ingress={"enabled": True}),
                              "no Ingress, route, NetworkPolicy or PersistentVolumeClaim"),
    "NetworkPolicies": (lambda v: v["global"]["networkPolicy"].update(create=True),
                        "no Ingress, route, NetworkPolicy or PersistentVolumeClaim"),
    "the API server scaled up": (lambda v: v["server"].update(replicas=1), "API server and ApplicationSet controller at zero replicas"),
    "Dex enabled": (lambda v: v["dex"].update(enabled=True), "no Dex or notifications controller"),
    "notifications enabled": (lambda v: v["notifications"].update(enabled=True), "no Dex or notifications controller"),
    "the admin user enabled": (lambda v: v["configs"]["cm"].update({"admin.enabled": True}),
                               "argocd-cm: admin, anonymous access and exec off"),
    "applications in every namespace": (lambda v: v["configs"]["params"].update({"application.namespaces": "*"}),
                                        "applications in any namespace: finrisk only, wired into the controller"),
    "aggregated roles": (lambda v: v.update(createAggregateRoles=True), "no ClusterRole aggregates into admin, edit or view"),
    "the API server's default ClusterRole": (lambda v: v["server"].pop("clusterRoleRules"),
                                             "only the application controller's ClusterRole grants anything"),
    "the repo-server without resources": (lambda v: v["repoServer"].pop("resources"),
                                           "every container that runs requests CPU and memory and has a memory limit"),
}

_, docs = argocd(VALUES)
found = properties(docs)
chart = yaml.safe_load(run(HELM, "show", "chart", ARGOCD_CHART).stdout or "{}") or {}
projects, application = manifest("argocd-projects.yaml"), manifest("monitoring-app.yaml")
# As the bootstrap applies it: the PLAN's commit and the image repository in place of the placeholders.
gitops = load_all((K8S / "inference-app.yaml").read_text().replace("GITOPS_REVISION", "0" * 40).replace(
    "IMAGE_REPOSITORY", "780976819607.dkr.ecr.us-east-1.amazonaws.com/finrisk-ai-inference"))
misspelled = copy.deepcopy(gitops)
next(d for d in misspelled if d["kind"] == "Application")["spec"]["source"]["helm"]["parameter"] = []
# The pinned Kubernetes schemas have none for CustomResourceDefinition; the API server validates the
# chart's three CRDs at install, and the Argo CD objects are validated against them below.
objects = [d for d in docs if d["kind"] != "CustomResourceDefinition"]
checks = {
    "pinned helm": run(HELM, "version", "--template", "{{.Version}}").stdout == PINS.get("HELM_VERSION"),
    "pinned kubeconform": run(KUBECONFORM, "-v").stdout.strip() == PINS.get("KUBECONFORM_VERSION"),
    "chart is the pinned file and version": hashlib.sha256(ARGOCD_CHART.read_bytes()).hexdigest() == PINS.get("ARGOCD_CHART_SHA256")
        and chart.get("name") == "argo-cd" and chart.get("version") == PINS.get("ARGOCD_CHART_VERSION"),
    "Argo CD image tag is the chart's appVersion": bool(chart)
        and VALUES["global"]["image"]["tag"].startswith(chart.get("appVersion", "?") + "@sha256:"),
    **found,
    "kubeconform -strict, every rendered object but the chart's own CRDs, Kubernetes 1.35":
        len(objects) == len(docs) - 3 and kubeconform(yaml.safe_dump_all(objects), len(objects)),
    "kubeconform -strict, AppProjects and Application against the chart's CRDs": kubeconform(
        yaml.safe_dump_all(projects + application), len(projects + application)),
    "kubeconform -strict, the inference Application, its Role and RoleBinding": [d["kind"] for d in gitops]
        == ["Role", "RoleBinding", "Application"] and kubeconform(yaml.safe_dump_all(gitops), 3),
    "negative control: a misspelled Application field fails kubeconform -strict": not kubeconform(yaml.safe_dump_all(misspelled), 3),
}
for name, (change, prop) in CONTROLS.items():
    _, mutated = argocd(broken(change))
    checks[f"negative control: {name} fails '{prop}'"] = bool(mutated) and found[prop] and not properties(mutated)[prop]

report("Argo CD install acceptance", checks)
