#!/usr/bin/env python3
# kubeconform -strict for the HPA load test's Job (infra/k8s/load-job.yaml) against the cluster's
# Kubernetes schemas, as the deploy build creates it: the image placeholder replaced by a digest-pinned
# URI, exactly as its sed does. Negative controls: a misspelled and a mistyped field must fail. Its
# properties are pinned without tools in test_load_job.py. It needs the tools
# .github/scripts/install-k8s-tools.sh installs into $K8S_TOOLS, so it is not named test_*.py;
# terraform-validate.yml runs it after the install.
import copy
import re

import yaml

from k8s_tools import KUBERNETES_VERSION, ROOT, kubeconform, load_all, report, require

require("Load Job schema acceptance")
DEPLOY = (ROOT / "infra/terraform/deploy/deploy-buildspec.yml.tftpl").read_text()
URI = "780976819607.dkr.ecr.us-east-1.amazonaws.com/finrisk-ai-inference@sha256:" + "a" * 64
# The deploy's own substitution, applied to the file.
old, new = re.search(r'sed "s#(\w+)#\$(\w+)#" /tmp/load-job\.yaml \| kq -n "\$NS" create -f -', DEPLOY).groups()
created = (ROOT / "infra/k8s/load-job.yaml").read_text().replace(old, URI if new == "FINRISK_IMAGE_URI" else new)
job = load_all(created)
misspelled, mistyped = copy.deepcopy(job), copy.deepcopy(job)
misspelled[0]["spec"]["template"]["spec"]["containers"][0]["resource"] = misspelled[0]["spec"]["template"]["spec"]["containers"][0].pop(
    "resources")
mistyped[0]["spec"]["backoffLimit"] = "none"

report("Load Job schema acceptance", {
    f"the load Job as the deploy creates it passes kubeconform -strict, Kubernetes {KUBERNETES_VERSION}":
        [d["kind"] for d in job] == ["Job"] and job[0]["spec"]["template"]["spec"]["containers"][0]["image"] == URI
        and kubeconform(created, 1),
    "negative control: a misspelled field fails kubeconform -strict": not kubeconform(yaml.safe_dump_all(misspelled), 1),
    "negative control: a mistyped field fails kubeconform -strict": not kubeconform(yaml.safe_dump_all(mistyped), 1),
})
