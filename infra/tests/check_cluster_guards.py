#!/usr/bin/env python3
# kubeconform -strict for infra/k8s/cluster-guards.yaml against the cluster's Kubernetes schemas
# (admissionregistration.k8s.io/v1), and for the five objects the bootstrap dry-runs to prove it, so a
# live denial can only come from admission, never from a malformed probe. Negative controls: a
# misspelled field must fail. Its expressions and their meaning are pinned without tools in
# test_cluster_guards.py, and the bootstrap proves the policy live. It needs the tools
# .github/scripts/install-k8s-tools.sh installs into $K8S_TOOLS, so it is not named test_*.py;
# terraform-validate.yml runs it after the install.
import copy
import json
import re

import yaml

from k8s_tools import KUBECONFORM, KUBERNETES_VERSION, PINS, ROOT, kubeconform, manifest, report, require, run

require("Cluster guard schema acceptance")
guard = manifest("cluster-guards.yaml")
misspelled = copy.deepcopy(guard)
misspelled[0]["spec"]["validation"] = misspelled[0]["spec"].pop("validations")

# The probes as the bootstrap's probe() builds them: its spec literals, in the app namespace.
BOOTSTRAP = (ROOT / "infra/terraform/deploy/bootstrap-buildspec.yml.tftpl").read_text()
KINDS = {"lb": "Service", "ips": "Service", "clusterip": "Service", "ingress": "Ingress", "pvc": "PersistentVolumeClaim"}
specs = dict(re.findall(r"^\s+(lb|ips|clusterip|ingress|pvc)='(\{.*\})'$", BOOTSTRAP, re.M))
probes = [{"apiVersion": "networking.k8s.io/v1" if KINDS[name] == "Ingress" else "v1", "kind": KINDS[name],
           "metadata": {"name": "finrisk-guard-probe", "namespace": "finrisk"}, "spec": json.loads(spec)}
          for name, spec in specs.items()]
bad_probe = copy.deepcopy(probes)
for p in bad_probe:
    if p["kind"] == "PersistentVolumeClaim":
        p["spec"]["accessMode"] = p["spec"].pop("accessModes")

report("Cluster guard schema acceptance", {
    "pinned kubeconform": run(KUBECONFORM, "-v").stdout.strip() == PINS.get("KUBECONFORM_VERSION"),
    f"policy and binding pass kubeconform -strict, Kubernetes {KUBERNETES_VERSION}":
        [d["kind"] for d in guard] == ["ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding"]
        and kubeconform(yaml.safe_dump_all(guard), 2),
    "negative control: a misspelled field fails kubeconform -strict": not kubeconform(yaml.safe_dump_all(misspelled), 2),
    "the bootstrap's five dry-run objects pass kubeconform -strict": sorted(specs) == sorted(KINDS)
        and kubeconform(yaml.safe_dump_all(probes), 5),
    "negative control: a misspelled probe field fails kubeconform -strict": not kubeconform(yaml.safe_dump_all(bad_probe), 5),
})
