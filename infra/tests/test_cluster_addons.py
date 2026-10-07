#!/usr/bin/env python3
# The cluster add-ons without tools: pins shared by Terraform and CI, the AppProjects, the monitoring
# Application, and the bootstrap buildspec's own discipline (downloads and embedded files checked by
# sha256, one terminal evidence line, every wait and download bounded within build_timeout).
# Properties that can be broken by an edit are also checked against a deliberately broken copy and
# must fail there. The rendered charts, and the OCI manifest that binds the Application's digest to
# the pinned chart, are checked by the check_*.py scripts, which CI runs after installing the pinned
# tools; this file also pins that they run.
import copy
import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
K8S = ROOT / "infra/k8s"
TF = (ROOT / "infra/terraform/deploy_path.tf").read_text()
BOOTSTRAP = (ROOT / "infra/terraform/deploy/bootstrap-buildspec.yml.tftpl").read_text()
INSTALL = (ROOT / ".github/scripts/install-k8s-tools.sh").read_text()
PINS = dict(re.findall(r'^(\w+)="([^"]+)"$', INSTALL, re.M))
LOCALS = dict(re.findall(r'^  (\w+)\s+= "([^"]*)"$', TF, re.M))
VALUES = yaml.safe_load((K8S / "argocd-values.yaml").read_text())
PROJECTS = [d for d in yaml.safe_load_all((K8S / "argocd-projects.yaml").read_text()) if d]
APP = yaml.safe_load((K8S / "monitoring-app.yaml").read_text())
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/terraform-validate.yml").read_text())
BUILD_TIMEOUT = int(re.search(r'resource "aws_codebuild_project" "k8s_bootstrap" \{.*?build_timeout\s+= (\d+)', TF, re.S)[1])
DIGEST = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")
HEX = re.compile(r"[0-9a-f]{64}")
EMBEDDED = {"cluster_guards": "cluster-guards.yaml", "argocd_values": "argocd-values.yaml",
            "argocd_projects": "argocd-projects.yaml", "monitoring_app": "monitoring-app.yaml"}
MONITORING_CHART = "oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack"
IN_CLUSTER = "https://kubernetes.default.svc"


# --- AppProjects ---------------------------------------------------------------------------------
def project_properties(projects):
    by = {p["metadata"]["name"]: p.get("spec", {}) for p in projects}
    monitoring = by.get("finrisk-monitoring", {})
    return {
        "AppProjects: default and finrisk-monitoring, in argocd": sorted(by) == ["default", "finrisk-monitoring"]
            and all(p["metadata"].get("namespace") == "argocd" for p in projects),
        "default is locked: no source, destination or kind": {k: by.get("default", {}).get(k) for k in (
            "sourceRepos", "destinations", "clusterResourceWhitelist", "namespaceResourceWhitelist")}
            == dict.fromkeys(("sourceRepos", "destinations", "clusterResourceWhitelist", "namespaceResourceWhitelist"), []),
        # Only Applications in argocd, which only the bootstrap writes, may use a project without them.
        "no project lists sourceNamespaces": not any("sourceNamespaces" in p for p in by.values()),
        "finrisk-monitoring: the chart's OCI repository only, into monitoring only":
            monitoring.get("sourceRepos") == [MONITORING_CHART]
            and monitoring.get("destinations") == [{"server": IN_CLUSTER, "namespace": "monitoring"}],
        "finrisk-monitoring: cluster-scoped only monitoring.coreos.com CRDs and the release's ClusterRoles and bindings":
            monitoring.get("clusterResourceWhitelist") == [
                {"group": "apiextensions.k8s.io", "kind": "CustomResourceDefinition", "name": "*.monitoring.coreos.com"},
                {"group": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": "monitoring-*"},
                {"group": "rbac.authorization.k8s.io", "kind": "ClusterRoleBinding", "name": "monitoring-*"}],
        "finrisk-monitoring: namespaced only ServiceAccount, Service, Deployment, Prometheus, ServiceMonitor":
            monitoring.get("namespaceResourceWhitelist") == [
                {"group": "", "kind": "ServiceAccount"}, {"group": "", "kind": "Service"}, {"group": "apps", "kind": "Deployment"},
                {"group": "monitoring.coreos.com", "kind": "Prometheus"}, {"group": "monitoring.coreos.com", "kind": "ServiceMonitor"}],
    }


def project(projects, name):
    return next(p["spec"] for p in projects if p["metadata"]["name"] == name)


PROJECT_CONTROLS = {
    "argocd in sourceNamespaces": (lambda ps: project(ps, "finrisk-monitoring").update(sourceNamespaces=["argocd"]),
                                   "no project lists sourceNamespaces"),
    "a wildcard sourceNamespaces on default": (lambda ps: project(ps, "default").update(sourceNamespaces=["*"]),
                                               "no project lists sourceNamespaces"),
    "any repository": (lambda ps: project(ps, "finrisk-monitoring")["sourceRepos"].append("*"),
                       "finrisk-monitoring: the chart's OCI repository only, into monitoring only"),
    "any namespace": (lambda ps: project(ps, "finrisk-monitoring")["destinations"][0].update(namespace="*"),
                      "finrisk-monitoring: the chart's OCI repository only, into monitoring only"),
    "default given a repository": (lambda ps: project(ps, "default")["sourceRepos"].append(MONITORING_CHART),
                                   "default is locked: no source, destination or kind"),
    "default without a namespaced list (nil permits every kind)": (
        lambda ps: project(ps, "default").pop("namespaceResourceWhitelist"), "default is locked: no source, destination or kind"),
    "ClusterRoleBindings of any name": (
        lambda ps: project(ps, "finrisk-monitoring")["clusterResourceWhitelist"][2].pop("name"),
        "finrisk-monitoring: cluster-scoped only monitoring.coreos.com CRDs and the release's ClusterRoles and bindings"),
    "Secrets": (lambda ps: project(ps, "finrisk-monitoring")["namespaceResourceWhitelist"].append({"group": "", "kind": "Secret"}),
                "finrisk-monitoring: namespaced only ServiceAccount, Service, Deployment, Prometheus, ServiceMonitor"),
}


# --- Monitoring Application ----------------------------------------------------------------------
def app_properties(app):
    spec = app.get("spec", {})
    source, sync = spec.get("source", {}), spec.get("syncPolicy", {})
    values = source.get("helm", {}).get("valuesObject", {})
    prometheus = values.get("prometheus", {}).get("prometheusSpec", {})
    operator = values.get("prometheusOperator", {})
    shas = [values.get("kube-state-metrics", {}).get("image", {}).get("sha", ""), operator.get("image", {}).get("sha", ""),
            operator.get("prometheusConfigReloader", {}).get("image", {}).get("sha", ""),
            operator.get("thanosImage", {}).get("sha", ""), prometheus.get("image", {}).get("sha", "")]
    return {
        "Application argocd/finrisk-monitoring in project finrisk-monitoring, into monitoring": app.get("metadata", {}).get("name")
            == "finrisk-monitoring" and app["metadata"].get("namespace") == "argocd" and spec.get("project") == "finrisk-monitoring"
            and spec.get("destination") == {"server": IN_CLUSTER, "namespace": "monitoring"},
        "source: the chart's OCI manifest by the digest CI fetches and checks, release monitoring":
            source.get("repoURL") == MONITORING_CHART and source.get("path") == "."
            and HEX.fullmatch(PINS.get("KUBE_PROMETHEUS_STACK_MANIFEST_SHA256", "")) is not None
            and source.get("targetRevision") == "sha256:" + PINS["KUBE_PROMETHEUS_STACK_MANIFEST_SHA256"]
            and set(source.get("helm", {})) == {"releaseName", "valuesObject"} and source["helm"]["releaseName"] == "monitoring",
        "automated sync with prune and self-heal, bounded retry": sync.get("automated") == {"enabled": True, "prune": True, "selfHeal": True}
            and sync.get("retry", {}).get("limit") == 5,
        "server-side apply and diff; never Replace or CreateNamespace": sync.get("syncOptions") == ["ServerSideApply=true"]
            and app["metadata"].get("annotations", {}).get("argocd.argoproj.io/compare-options") == "ServerSideDiff=true",
        "no finalizers": "finalizers" not in app.get("metadata", {}),
        "Prometheus reloads by signal (no lifecycle API)": prometheus.get("reloadStrategy") == "ProcessSignal",
        "ServiceMonitors cannot read Prometheus's files or select other namespaces":
            prometheus.get("arbitraryFSAccessThroughSMs") == {"deny": True} and prometheus.get("ignoreNamespaceSelectors") is True,
        "Prometheus storage is a size-limited emptyDir": prometheus.get("storageSpec") == {"emptyDir": {"sizeLimit": "1Gi"}},
        "app ServiceMonitors in finrisk are selected": "finrisk" in json.dumps(prometheus.get("serviceMonitorNamespaceSelector"))
            and prometheus.get("serviceMonitorSelectorNilUsesHelmValues") is False,
        "no Alertmanager, Grafana, node-exporter, webhooks or operator TLS": all(
            values.get(k, {}).get("enabled") is False for k in ("alertmanager", "grafana", "nodeExporter"))
            and operator.get("admissionWebhooks", {}).get("enabled") is False and operator.get("tls", {}).get("enabled") is False,
        # kube-state-metrics takes the prefix; the parent chart's templates add it to the rest.
        "image digests: sha256: prefix for kube-state-metrics only": shas[0].startswith("sha256:")
            and HEX.fullmatch(shas[0][7:]) is not None and all(HEX.fullmatch(s) for s in shas[1:]),
    }


def changed_app(change):
    app = copy.deepcopy(APP)
    change(app)
    return app


def prom(app):
    return app["spec"]["source"]["helm"]["valuesObject"]["prometheus"]["prometheusSpec"]


APP_CONTROLS = {
    "a version tag instead of the digest": (lambda a: a["spec"]["source"].update(targetRevision="91.9.0"),
                                            "source: the chart's OCI manifest by the digest CI fetches and checks, release monitoring"),
    "Helm parameters beside valuesObject": (lambda a: a["spec"]["source"]["helm"].update(parameters=[{"name": "x", "value": "y"}]),
                                            "source: the chart's OCI manifest by the digest CI fetches and checks, release monitoring"),
    "Replace=true": (lambda a: a["spec"]["syncPolicy"]["syncOptions"].append("Replace=true"),
                     "server-side apply and diff; never Replace or CreateNamespace"),
    "CreateNamespace=true": (lambda a: a["spec"]["syncPolicy"]["syncOptions"].append("CreateNamespace=true"),
                             "server-side apply and diff; never Replace or CreateNamespace"),
    "a resources finalizer": (lambda a: a["metadata"].update(finalizers=["resources-finalizer.argocd.argoproj.io"]), "no finalizers"),
    "the default project": (lambda a: a["spec"].update(project="default"),
                            "Application argocd/finrisk-monitoring in project finrisk-monitoring, into monitoring"),
    "the HTTP reload strategy": (lambda a: prom(a).pop("reloadStrategy"), "Prometheus reloads by signal (no lifecycle API)"),
    "file access through ServiceMonitors": (lambda a: prom(a).pop("arbitraryFSAccessThroughSMs"),
                                            "ServiceMonitors cannot read Prometheus's files or select other namespaces"),
    "a bare kube-state-metrics digest": (lambda a: a["spec"]["source"]["helm"]["valuesObject"]["kube-state-metrics"]["image"].update(
        sha="42cfe3723a5f058171c627537fb57a3ea0f26e4380fa18555a95cb1a1b4cfc5b"), "image digests: sha256: prefix for kube-state-metrics only"),
}


# --- Bootstrap buildspec discipline --------------------------------------------------------------
def evidence(template):
    return re.findall(r'echo "FINRISK_EVIDENCE (\S+)', template)


def terminal_last(template):
    """run-codebuild.sh stops reading logs at the first line matching the terminal regex, so only the
    last evidence line may carry bootstrap= (or result=, the default terminal)."""
    lines = re.findall(r'echo "FINRISK_EVIDENCE ([^"]*)"', template)
    return bool(lines) and [bool(re.search(r"bootstrap=|result=", line)) for line in lines] == [False] * (len(lines) - 1) + [True] \
        and lines[-1].startswith("bootstrap=complete ")


def script_lines(template):
    """The build command as bash runs it: comment lines dropped, continuation lines joined."""
    script = yaml.safe_load(template)["phases"]["build"]["commands"][0].replace("$${", "${")
    return [line for line in script.replace("\\\n", " ").splitlines() if not line.lstrip().startswith("#")]


def functions(lines):
    """name -> body of each shell function (one-line, or closed by a `}` line at column 0), and the
    lines outside them."""
    defs, main, i = {}, [], 0
    while i < len(lines):
        m = re.match(r"(\w+)\(\) \{(.*)$", lines[i])
        if m and m[2].rstrip().endswith("}"):
            defs[m[1]] = m[2].rstrip()[:-1]
        elif m:
            end = lines.index("}", i)
            defs[m[1]], i = "\n".join(lines[i + 1:end]), end
        else:
            main.append(lines[i])
        i += 1
    return defs, main


# A word at command position: line start, after ; & | ( { ! or $(, or after a shell keyword.
CMD = r"(?:^|[;&|({!]|\$\(|\b(?:if|then|else|do|until|while)\s)\s*"
WAIT_FOR = """  local deadline=$(( $(date +%s) + $1 ))
  shift
  until "$@"; do
    [ "$(date +%s)" -lt "$deadline" ] || return 1
    sleep 5
  done"""


def kubectl_calls(name, defs, seen=()):
    """kubectl calls one run of a shell function makes, all through kq; None if any is direct (no
    request timeout), helm runs, or the functions recurse."""
    body = defs[name]
    if name in seen or re.search(CMD + r'(?:"?\$\{?[KH]\b|\S*(?:kubectl|helm)\b)', body, re.M):
        return None
    calls = len(re.findall(CMD + r"kq\b", body, re.M))
    for f in set(defs) - {"kq"}:
        n = len(re.findall(CMD + re.escape(f) + r"\b", body, re.M))
        inner = kubectl_calls(f, defs, (*seen, name)) if n else 0
        if inner is None:
            return None
        calls += n * inner
    return calls


def wait_budget(template):
    """Seconds the bootstrap can spend waiting and downloading at worst, or None when one of them has
    no recognised bound. A wait_for may run one more 5 s poll and one more check past its bound, each
    kubectl call of the check held to kq's request timeout; helm waits up to its timeout for the hook
    Job, then again for the workloads; rollout status and kubectl wait up to their --timeout, times
    the loop around them; a download up to curl's retry window plus one attempt."""
    lines = script_lines(template)
    script, (defs, main) = "\n".join(lines), functions(lines)
    kq = re.fullmatch(r' "\$K" --request-timeout=(\d+)s "\$@"; ', defs.get("kq", ""))
    fetch = re.search(r"^  curl -fsSL --retry \d+ --retry-connrefused --retry-max-time (\d+) --max-time (\d+) ",
                      defs.get("fetch", ""), re.M)
    if not kq or not fetch or defs.get("wait_for") != WAIT_FOR or script.count("curl ") != 1 \
            or len(re.findall(r"\b(?:sleep|until)\b", script)) != 2 or re.search(r"\bwhile\b|--watch\b|\s-w\b", script):
        return None  # one sleep and one loop, wait_for's; every kubectl poll through kq; downloads through fetch
    blocking = re.compile(r"--timeout\b|--wait\b|rollout status|\bwait_for\b|(?:\"\$K\"|kq) wait\b")
    if any(blocking.search(body) for name, body in defs.items() if name != "wait_for"):
        return None  # a wait inside a function would run once per call
    seconds, loops = 0, []
    for line in main:
        loop = re.match(r"\s*for \w+ in (.+?); do(.*)$", line)
        if loop and "done" in loop[2] and blocking.search(line):
            return None
        if loop and "done" not in loop[2]:
            loops.append(len(loop[1].split()))
        elif line.strip() == "done":
            loops.pop()
        times = 1
        for n in loops:
            times *= n
        accounted = 0
        if re.search(r'"\$H" .*--wait\b', line):
            bound = re.search(r" --wait --timeout (\d+)s\b", line)
            if not bound:
                return None
            seconds, accounted = seconds + 2 * int(bound[1]) * times, accounted + 1
        if "rollout status" in line or re.search(r'(?:"\$K"|kq) wait\b', line):
            bound = re.search(r" --timeout=(\d+)s\b", line)
            if not bound:
                return None
            seconds, accounted = seconds + int(bound[1]) * times, accounted + 1
        for n, check in re.findall(CMD + r"wait_for (\d+) (\w+)\b", line):
            calls = kubectl_calls(check, defs) if check in defs else None
            if calls is None:
                return None
            seconds += (int(n) + 5 + int(kq[1]) * calls) * times
        if len(re.findall(r"--timeout\b", line)) != accounted:
            return None  # a bound on something not modelled here
        if re.match(r"fetch \S+ ", line):
            seconds += (int(fetch[1]) + int(fetch[2])) * times
    uses = len(re.findall(r"\bwait_for\b", script)) - 1
    if uses != len(re.findall(CMD + r"wait_for \d+ \w+\b", script, re.M)):
        return None  # a wait_for whose bound is not a literal
    return seconds


BUDGET = wait_budget(BOOTSTRAP)
OVERHEAD = 4 * 60  # provisioning in the VPC, the applies and the checks between waits
early = BOOTSTRAP.replace('echo "FINRISK_EVIDENCE node ', 'echo "FINRISK_EVIDENCE bootstrap=started node ', 1)
WAIT_CONTROLS = {
    "a longer wait breaks the budget": ("wait_for 60 authorized", "wait_for 600 authorized"),
    "kubectl wait with an unbounded timeout": ("--for=condition=Established --timeout=30s", "--for=condition=Established --timeout=-1s"),
    "kubectl wait without --timeout": ("--for=condition=Established --timeout=30s", "--for=condition=Established"),
    "helm --wait without --timeout (Helm's default is 5 min)": (" --wait --timeout 150s", " --wait"),
    "rollout status without --timeout (kubectl waits forever)": (' rollout status "$workload" --timeout=10s', ' rollout status "$workload"'),
    "an added rollout status without --timeout": ('        digest_pinned "$A"\n',
                                                  '        "$K" -n "$A" rollout status deployment/argocd-repo-server\n        digest_pinned "$A"\n'),
    "a polled kubectl call without the request timeout": ('$(kq auth can-i', '$("$K" auth can-i'),
    "a check that polls kubectl by its path": ('query="$(kq get --raw', 'query="$(/opt/finrisk/bin/kubectl get --raw'),
    "a second polling loop": ('        digest_pinned "$A"\n', '        while ! digest_pinned "$A"; do sleep 5; done\n'),
    "a download without --max-time": (" --max-time 40 ", " "),
    "a wait_for whose bound is a variable": ("wait_for 90 scraping", 'wait_for "$${PROM_WAIT:-90}" scraping'),
}


def changed(old, new):
    return BOOTSTRAP.replace(old, new, 1) if old in BOOTSTRAP else ""


def budget_fails(template):
    try:
        budget = wait_budget(template)
    except (ValueError, IndexError, yaml.YAMLError):
        budget = None
    return budget is None or budget + OVERHEAD > BUILD_TIMEOUT * 60


FETCH = """fetch() {
  curl -fsSL --retry 3 --retry-connrefused --retry-max-time 20 --max-time 40 -o "$1" "$2"
  echo "$3  $1" | sha256sum --check --strict
}"""
DOWNLOADS = {  # each fetched file and its first use
    'fetch /tmp/kubectl "https://dl.k8s.io/release/${kubectl_version}/bin/linux/amd64/kubectl" "${kubectl_sha256}"':
        "install -m 0755 /tmp/kubectl ",
    'fetch /tmp/helm.tar.gz "https://get.helm.sh/helm-${helm_version}-linux-amd64.tar.gz" "${helm_sha256}"':
        "tar -xzOf /tmp/helm.tar.gz ",
    'fetch /tmp/finrisk/argo-cd.tgz "https://github.com/argoproj/argo-helm/releases/download/argo-cd-${argocd_chart_version}/'
    'argo-cd-${argocd_chart_version}.tgz" "${argocd_chart_sha256}"': '"$H" upgrade --install argocd /tmp/finrisk/argo-cd.tgz ',
}


def downloads_checked(template):
    """Every download goes through fetch, which fails unless the file has the sha256 fixed in the plan,
    and nothing uses a file before its fetch."""
    script = "\n".join(script_lines(template)) if template else ""
    return FETCH in script and script.count("curl ") == 1 and len(re.findall(r"^fetch ", script, re.M)) == len(DOWNLOADS) \
        and all(line in script.splitlines() and use in script and script.index(line) < script.index(use) for line, use in DOWNLOADS.items())


DOWNLOAD_CONTROLS = {
    "kubectl downloaded without its checksum": (
        'fetch /tmp/kubectl "https://dl.k8s.io/release/${kubectl_version}/bin/linux/amd64/kubectl" "${kubectl_sha256}"',
        'curl -fsSLo /tmp/kubectl "https://dl.k8s.io/release/${kubectl_version}/bin/linux/amd64/kubectl"'),
    "fetch without the checksum": ('          echo "$3  $1" | sha256sum --check --strict\n', ""),
    "the chart checked against another sha256": ('/argo-cd-${argocd_chart_version}.tgz" "${argocd_chart_sha256}"',
                                                 '/argo-cd-${argocd_chart_version}.tgz" "${helm_sha256}"'),
    "helm unpacked before it is fetched": (
        '        fetch /tmp/helm.tar.gz "https://get.helm.sh/helm-${helm_version}-linux-amd64.tar.gz" "${helm_sha256}"\n'
        '        tar -xzOf /tmp/helm.tar.gz linux-amd64/helm > /tmp/helm\n',
        '        tar -xzOf /tmp/helm.tar.gz linux-amd64/helm > /tmp/helm\n'
        '        fetch /tmp/helm.tar.gz "https://get.helm.sh/helm-${helm_version}-linux-amd64.tar.gz" "${helm_sha256}"\n'),
}

# --- Repository-wide ---------------------------------------------------------------------------------
tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split() \
    or [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]


def argocd_source_files(paths):
    """Argo CD merges .argocd-source*.yaml from a source path over the Application's own parameters,
    where CI's plain Helm render would not see it."""
    return [p for p in paths if re.fullmatch(r"\.argocd-source(-[^/]+)?\.ya?ml", Path(p).name)]


steps = WORKFLOW["jobs"]["validate"]["steps"]
runs = [s.get("run", "").strip() for s in steps]
install = runs.index('bash .github/scripts/install-k8s-tools.sh "$K8S_TOOLS"') if \
    'bash .github/scripts/install-k8s-tools.sh "$K8S_TOOLS"' in runs else len(runs)


def ci_runs(name, steps=steps):
    """Index of the plain step that runs infra/tests/<name>, or -1."""
    command = f"python infra/tests/{name}"
    return next((i for i, s in enumerate(steps) if s.get("run", "").strip() == command
                 and not {"if", "continue-on-error"} & set(s)), -1)


checks_scripts = sorted(p.name for p in (ROOT / "infra/tests").glob("check_*.py"))
test_scripts = sorted(p.name for p in (ROOT / "infra/tests").glob("test_*.py"))
k8s_tools = {"K8S_TOOLS": "${{ runner.temp }}/k8s-tools"}

found_projects, found_app = project_properties(PROJECTS), app_properties(APP)
checks = {
    "Terraform pins helm and the Argo CD chart exactly as the CI install script":
        (LOCALS.get("helm_version"), LOCALS.get("helm_sha256"), LOCALS.get("argocd_chart_version"), LOCALS.get("argocd_chart_sha256"))
        == (PINS.get("HELM_VERSION"), PINS.get("HELM_SHA256"), PINS.get("ARGOCD_CHART_VERSION"), PINS.get("ARGOCD_CHART_SHA256"))
        and all(HEX.fullmatch(LOCALS.get(k, "")) for k in ("helm_sha256", "argocd_chart_sha256")),
    "bootstrap fetches kubectl, helm and the chart by those pins, each checked against its sha256 before use":
        downloads_checked(BOOTSTRAP),
    **{f"negative control: {name} is caught": not downloads_checked(changed(old, new)) for name, (old, new) in DOWNLOAD_CONTROLS.items()},
    "Argo CD values: both images by digest": DIGEST.fullmatch(f'{VALUES["global"]["image"]["repository"]}:{VALUES["global"]["image"]["tag"]}')
        is not None and DIGEST.fullmatch(f'{VALUES["redis"]["image"]["repository"]}:{VALUES["redis"]["image"]["tag"]}') is not None,
    "Argo CD values: headless, no admin, applications only in the app namespace": VALUES["server"]["replicas"] == 0
        and VALUES["applicationSet"]["replicas"] == 0 and VALUES["dex"]["enabled"] is False
        and VALUES["notifications"]["enabled"] is False and VALUES["configs"]["cm"]["admin.enabled"] is False
        and VALUES["configs"]["params"]["application.namespaces"] == LOCALS.get("k8s_app_namespace")
        and VALUES["createAggregateRoles"] is False and VALUES["server"]["clusterRoleRules"] == {"enabled": True, "rules": []},
    **found_projects,
    **found_app,
    # The reviewed plan shows each file's sha256 in plain text, and the build refuses a file that differs.
    "bootstrap embeds the infra/k8s files and checks each against its own sha256 after unpacking":
        re.findall(r'^  k8s_bootstrap_files\s+= \[(.*)\]$', TF, re.M) == [", ".join(f'"{f}"' for f in EMBEDDED.values())]
        and re.search(r'^  k8s_manifests\s+= "\$\{path\.module\}/\.\./k8s"$', TF, re.M) is not None
        and 'k8s_bundle_b64         = base64gzip(join("", [for f in local.k8s_bootstrap_files : "#==> ${f}\\n${file("${local.k8s_manifests}/${f}")}"]))' in TF
        and all(re.search(rf'^\s+{n}_sha256\s+= filesha256\("\$\{{local\.k8s_manifests\}}/{re.escape(f)}"\)$', TF, re.M)
                and f"${{{n}_sha256}}  /tmp/finrisk/{f}\n" in BOOTSTRAP for n, f in EMBEDDED.items())
        and """awk '/^#==> /{f="/tmp/finrisk/"$2; next} {print > f}'""" in BOOTSTRAP
        and "sha256sum --check --strict <<EOF" in BOOTSTRAP,
    "bootstrap evidence: node, guard, argocd, monitoring, then bootstrap=complete":
        evidence(BOOTSTRAP) == ["node", "guard", "argocd", "monitoring", "bootstrap=complete"],
    "only the last bootstrap evidence line is terminal": terminal_last(BOOTSTRAP),
    "negative control: an earlier bootstrap= line is caught": not terminal_last(early),
    f"bootstrap waits and downloads at their bounds ({f'{BUDGET / 60:.1f} min' if BUDGET else 'one has no recognised bound'}) "
    f"plus {OVERHEAD // 60} min fit build_timeout ({BUILD_TIMEOUT} min)": BUDGET is not None and BUDGET + OVERHEAD <= BUILD_TIMEOUT * 60,
    **{f"negative control: {name} is caught": bool(changed(old, new)) and budget_fails(changed(old, new))
       for name, (old, new) in WAIT_CONTROLS.items()},
    "no .argocd-source*.yaml anywhere in the repository": bool(tracked) and not argocd_source_files(tracked),
    "negative control: .argocd-source files are found": argocd_source_files(
        ["charts/finrisk-inference/.argocd-source.yaml", "x/.argocd-source-finrisk-inference.yml", "docs/argocd-source.md"])
        == ["charts/finrisk-inference/.argocd-source.yaml", "x/.argocd-source-finrisk-inference.yml"],
    # Nothing that needs the tools is skipped, and nothing static is left out of CI.
    "CI runs every check_*.py after installing the pinned tools, with K8S_TOOLS": bool(checks_scripts) and all(
        install < ci_runs(n) and steps[ci_runs(n)].get("env") == k8s_tools for n in checks_scripts),
    "CI runs every test_*.py": all(ci_runs(n) >= 0 for n in test_scripts),
    "negative control: a check left out of CI is caught": ci_runs(checks_scripts[0], steps=[
        s for s in steps if s.get("run", "").strip() != f"python infra/tests/{checks_scripts[0]}"]) == -1,
}
for name, (change, prop) in PROJECT_CONTROLS.items():
    mutated = copy.deepcopy(PROJECTS)
    change(mutated)
    checks[f"negative control: {name} fails '{prop}'"] = found_projects[prop] and not project_properties(mutated)[prop]
for name, (change, prop) in APP_CONTROLS.items():
    checks[f"negative control: {name} fails '{prop}'"] = found_app[prop] and not app_properties(changed_app(change))[prop]

failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("Cluster add-ons acceptance failed: " + ", ".join(failed))
