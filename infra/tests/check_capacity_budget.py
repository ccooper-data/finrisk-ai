#!/usr/bin/env python3
# Worker capacity for the bounded window: the requests of everything that runs at once must fit the
# allocatable CPU and memory of each worker type infra/terraform/variables.tf allows, with pods to
# spare. Counted from the rendered charts (Argo CD with its hook Job, the lean Prometheus stack with
# the operator-generated Prometheus Pod, the inference chart at HPA max plus one surge Pod), kube-system
# as EKS 1.35 runs it, and PR 3's load Job. A t3.small (V1's type) must not fit: the check is not
# vacuous. It needs the tools .github/scripts/install-k8s-tools.sh installs into $K8S_TOOLS, so it is
# not named test_*.py; terraform-validate.yml runs it after the install.
import copy
import math
import re

import yaml

from k8s_tools import K8S, ROOT, argocd, containers, manifest, monitoring, pod_templates, report, require, template

require("Capacity budget acceptance")
VARIABLES = (ROOT / "infra/terraform/variables.tf").read_text()
ALLOWED = re.findall(r'"([a-z0-9-]+\.[a-z0-9]+)"', re.search(r'contains\(\[([^]]+)\]', VARIABLES)[1])
DEFAULT = re.search(r'variable "eks_node_instance_types" \{.*?default\s+= \["([^"]+)"\]', VARIABLES, re.S)[1]


def memory_mi(maxpods, capacity_mi=7680):
    """EKS AMI kubelet: allocatable = capacity - kube-reserved (255Mi + 11Mi per pod) - 100Mi eviction.
    capacity_mi is below an 8 GiB instance's reported memory, to stay conservative."""
    return capacity_mi - (255 + 11 * maxpods) - 100


# CPU: 2 vCPUs less kube-reserved (6% of the first core, 1% of the second). maxPods from the VPC CNI's
# eni-max-pods table (ENIs x (IPv4 per ENI - 1) + 2).
NODES = {
    "t3.large": {"cpu_m": 1930, "memory_mi": memory_mi(35), "pods": 35},
    "m7i-flex.large": {"cpu_m": 1930, "memory_mi": memory_mi(29), "pods": 29},
}
SMALL = {"cpu_m": 1930, "memory_mi": memory_mi(11, capacity_mi=1900), "pods": 11}  # t3.small, 2 GiB
# kube-system on a one-node EKS 1.35 cluster: aws-node (VPC CNI and its network policy agent),
# kube-proxy, two CoreDNS and two metrics-server replicas, at their EKS default requests.
KUBE_SYSTEM = [("aws-node", 1, 50, 64), ("kube-proxy", 1, 100, 0), ("coredns", 2, 100, 70), ("metrics-server", 2, 100, 200)]
LOAD_JOB = ("PR 3 load Job", 1, 100, 64)


def cpu_m(q):
    q = str(q)
    return int(q[:-1]) if q.endswith("m") else int(float(q) * 1000)


def mem_mi(q):
    units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "k": 1000 / 1048576, "M": 1e6 / 1048576, "G": 1e9 / 1048576}
    number, unit = re.fullmatch(r"([0-9.]+)([A-Za-z]*)", str(q)).groups()
    return float(number) * units.get(unit, 1 / 1048576)


def requests(resources):
    r = (resources or {}).get("requests") or {}
    return (cpu_m(r["cpu"]), mem_mi(r["memory"])) if {"cpu", "memory"} <= set(r) else None


def pod(template):
    """A Pod's effective requests: its containers together, or its largest init container if larger."""
    spec = template["spec"]
    main = [requests(c.get("resources")) for c in spec["containers"]]
    init = [requests(c.get("resources")) for c in spec.get("initContainers") or []]
    if None in main + init:
        return None
    return tuple(max(sum(m[i] for m in main), max((x[i] for x in init), default=0)) for i in (0, 1))


def workloads(docs, scale=lambda kind, name, replicas: replicas):
    """(name, pods, cpu_m, memory_mi) per workload, from rendered objects."""
    rows = []
    for kind, name, t in pod_templates(docs):
        count = scale(kind, name, 1 if kind == "Job" else docs_by(docs)[(kind, name)]["spec"].get("replicas", 1))
        if count:
            rows.append((name, count, *(pod(t) or (math.inf, math.inf))))
    return rows


def docs_by(docs):
    return {(d["kind"], d["metadata"]["name"]): d for d in docs}


def prometheus_pod(docs):
    """The Pod the operator generates: Prometheus plus its config reloader (init container alike)."""
    spec = docs_by(docs)[("Prometheus", "monitoring")]["spec"]
    operator = next(c for _, name, t in pod_templates(docs) if name == "monitoring-operator" for c in containers(t))
    args = dict(a[2:].split("=", 1) for a in operator["args"] if "=" in a)
    reloader = (cpu_m(args["config-reloader-cpu-request"]), mem_mi(args["config-reloader-memory-request"]))
    main = requests(spec.get("resources")) or (math.inf, math.inf)
    return ("prometheus-monitoring", spec.get("replicas", 1), main[0] + reloader[0], main[1] + reloader[1])


def inference(docs):
    """The inference Deployment at the HPA's maximum, plus the surge Pod a rollout adds."""
    hpa = next(d for d in docs if d["kind"] == "HorizontalPodAutoscaler")["spec"]["maxReplicas"]
    surge = math.ceil(hpa * 0.25)  # Deployment default maxSurge 25%; the chart sets no strategy
    return workloads(docs, lambda kind, name, replicas: hpa + surge)


def budget(rows, node):
    cpu = sum(n * c for _, n, c, _ in rows)
    memory = sum(n * m for _, n, _, m in rows)
    pods = sum(n for _, n, _, _ in rows)
    fits = cpu <= node["cpu_m"] and memory <= node["memory_mi"] and pods <= node["pods"] - 3
    return fits, f"{cpu:,.0f}m of {node['cpu_m']:,}m CPU, {memory:,.0f}Mi of {node['memory_mi']:,}Mi memory, " \
                 f"{pods} of {node['pods']} pods (3 spare)"


_, argo = argocd(yaml.safe_load((K8S / "argocd-values.yaml").read_text()))
_, stack = monitoring(manifest("monitoring-app.yaml")[0]["spec"]["source"]["helm"]["valuesObject"])
_, app = template(ROOT / "charts/finrisk-inference", "finrisk-inference", "finrisk", {
    "image": {"repository": "780976819607.dkr.ecr.us-east-1.amazonaws.com/finrisk-ai-inference", "digest": "sha256:" + "a" * 64}})
rows = [*KUBE_SYSTEM, *workloads(argo), *workloads(stack), prometheus_pod(stack), *inference(app), LOAD_JOB]
for row in rows:
    print(f"  {row[0]}: {row[1]} x ({row[2]:.0f}m, {row[3]:.0f}Mi)")

checks = {
    "renders Argo CD, the monitoring stack and the inference chart": bool(argo and stack and app),
    "every counted Pod declares CPU and memory requests": all(math.isfinite(r[2]) and math.isfinite(r[3]) for r in rows),
    "the allowed worker types are the ones budgeted here, and the default is one of them":
        sorted(ALLOWED) == sorted(NODES) and DEFAULT in NODES,
}
for name, node in NODES.items():
    fits, detail = budget(rows, node)
    checks[f"fits one {name}: {detail}"] = fits
fits, detail = budget(rows, SMALL)
checks[f"negative control: does not fit a t3.small ({detail})"] = not fits
missing = copy.deepcopy(argo)
docs_by(missing)[("Deployment", "argocd-repo-server")]["spec"]["template"]["spec"]["containers"][0].pop("resources")
checks["negative control: a container without requests is caught"] = not all(
    math.isfinite(r[2]) for r in workloads(missing))

report("Capacity budget acceptance", checks)
