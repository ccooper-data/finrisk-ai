#!/usr/bin/env python3
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
eks = (ROOT / "terraform" / "eks.tf").read_text()
variables = (ROOT / "terraform" / "variables.tf").read_text()
manifest = (ROOT / "k8s" / "inference.yaml").read_text()
bootstrap = (ROOT / "terraform" / "deploy" / "bootstrap-buildspec.yml.tftpl").read_text()

# Pod Security "restricted" at the latest version, which includes "baseline": the checks in
# k8s.io/pod-security-admission/policy (v1.35), for every Pod template in the manifest. Enforce applies
# to the Pods a workload creates, so a violation would otherwise surface only after the apply. Stricter
# than admission only for hostUsers: false, where it allows root inside the Pod's user namespace.
templates = [d["spec"]["template"] for d in yaml.safe_load_all(manifest) if d and "template" in (d.get("spec") or {})]
RESTRICTED_VOLUMES = {"configMap", "csi", "downwardAPI", "emptyDir", "ephemeral", "image", "persistentVolumeClaim",
                      "projected", "secret"}
PROFILES = {"RuntimeDefault", "Localhost"}  # seccomp and AppArmor
SELINUX_TYPES = {"", "container_t", "container_init_t", "container_kvm_t", "container_engine_t"}
SAFE_SYSCTLS = {"kernel.shm_rmid_forced", "net.ipv4.ip_local_port_range", "net.ipv4.tcp_syncookies",
                "net.ipv4.ping_group_range", "net.ipv4.ip_unprivileged_port_start",
                "net.ipv4.ip_local_reserved_ports", "net.ipv4.tcp_keepalive_time", "net.ipv4.tcp_fin_timeout",
                "net.ipv4.tcp_keepalive_intvl", "net.ipv4.tcp_keepalive_probes", "net.ipv4.tcp_rmem",
                "net.ipv4.tcp_wmem"}


def field(obj, key, name):
    return (obj.get(key) or {}).get(name)


def seccomp(ctx):
    return field(ctx, "seccompProfile", "type")


def capabilities(ctx, key):
    return field(ctx, "capabilities", key) or []


def hosts(container):
    handlers = [container.get(k) for k in ("livenessProbe", "readinessProbe", "startupProbe")]
    handlers += [field(container, "lifecycle", k) for k in ("postStart", "preStop")]
    return [field(h, kind, "host") for h in handlers if h for kind in ("httpGet", "tcpSocket")]


def restricted(template):
    pod = template["spec"]
    pod_sc = pod.get("securityContext") or {}
    containers = [c for key in ("initContainers", "containers", "ephemeralContainers") for c in pod.get(key) or []]
    container_sc = [c.get("securityContext") or {} for c in containers]
    every_sc = [pod_sc, *container_sc]
    apparmor = [v for k, v in (field(template, "metadata", "annotations") or {}).items()
                if k.startswith("container.apparmor.security.beta.kubernetes.io/")]
    return {
        "restricted: every container runs as non-root, never UID 0": bool(containers)
            and pod_sc.get("runAsNonRoot") is not False
            and all(s.get("runAsNonRoot", pod_sc.get("runAsNonRoot")) is True for s in container_sc)
            and all(s.get("runAsUser") != 0 for s in every_sc),
        "restricted: allowPrivilegeEscalation false on every container": all(
            s.get("allowPrivilegeEscalation") is False for s in container_sc),
        "restricted: capabilities drop ALL, add at most NET_BIND_SERVICE": all(
            "ALL" in capabilities(s, "drop") and set(capabilities(s, "add")) <= {"NET_BIND_SERVICE"}
            for s in container_sc),
        "restricted: seccomp RuntimeDefault or Localhost for every container": seccomp(pod_sc) in PROFILES | {None}
            and all((seccomp(s) or seccomp(pod_sc)) in PROFILES for s in container_sc),
        "restricted: no host network, PID or IPC": not any(pod.get(k) for k in ("hostNetwork", "hostPID", "hostIPC")),
        "restricted: only allowed volume types (no hostPath)": all(
            set(v) - {"name"} <= RESTRICTED_VOLUMES for v in pod.get("volumes") or []),
        "restricted: no hostPort": not any(p.get("hostPort") for c in containers for p in c.get("ports") or []),
        "restricted: no privileged container": not any(s.get("privileged") for s in container_sc),
        "restricted: default /proc mount": all(s.get("procMount") in (None, "Default") for s in container_sc),
        "restricted: AppArmor RuntimeDefault or Localhost when set": all(
            s.get("appArmorProfile") is None or field(s, "appArmorProfile", "type") in PROFILES for s in every_sc)
            and all(v in ("", "runtime/default") or v.startswith("localhost/") for v in apparmor),
        "restricted: SELinux type allowed, no custom SELinux user or role": all(
            (field(s, "seLinuxOptions", "type") or "") in SELINUX_TYPES and not field(s, "seLinuxOptions", "user")
            and not field(s, "seLinuxOptions", "role") for s in every_sc),
        "restricted: only safe sysctls": all(s.get("name") in SAFE_SYSCTLS for s in pod_sc.get("sysctls") or []),
        "restricted: no Windows hostProcess": not any(field(s, "windowsOptions", "hostProcess") for s in every_sc),
        "restricted: no host in probes or lifecycle handlers": not any(any(hosts(c)) for c in containers),
    }


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
    "manifest has a Pod template": bool(templates),
    **{name: all(r[name] for r in results) for name in (results[0] if results else {})},
    # The deploy build's dry run fails on the warning the warn level returns for a violating Deployment.
    "namespace enforces and warns Pod Security restricted, latest version": 'label namespace "${namespace}" --overwrite'
        in bootstrap and psa_labels == {"enforce": ["restricted"], "enforce-version": ["latest"],
                                        "warn": ["restricted"], "warn-version": ["latest"]},
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("EKS acceptance failed: " + ", ".join(failed))
