#!/usr/bin/env python3
# In-VPC CodeBuild deploy path to the private EKS API: Terraform, buildspecs, IAM, workflows.
import base64
import gzip
import json
import re
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "infra/terraform"
eks = (TF / "eks.tf").read_text()
path_tf = (TF / "deploy_path.tf").read_text()
deploy_spec = (TF / "deploy/deploy-buildspec.yml.tftpl").read_text()
bootstrap_spec = (TF / "deploy/bootstrap-buildspec.yml.tftpl").read_text()
variables = (TF / "variables.tf").read_text()
inference_app = [d for d in yaml.safe_load_all((ROOT / "infra/k8s/inference-app.yaml").read_text()) if d]
release = json.loads((ROOT / "docs/aws-release-policy.json").read_text())
release_trust = json.loads((ROOT / "docs/aws-release-trust-policy.json").read_text())
deployer_path = json.loads((ROOT / "docs/aws-deployer-deploy-path-policy.json").read_text())
boundary = json.loads((ROOT / "docs/aws-eks-boundary-policy.json").read_text())
runtime_tpl = (TF / "policies/codebuild-runtime.json.tftpl").read_text()
deploy_wf = (ROOT / ".github/workflows/deploy-inference.yml").read_text()
build_wf = (ROOT / ".github/workflows/build-inference-image.yml").read_text()
provision_wf = (ROOT / ".github/workflows/provision-bounded-aws.yml").read_text()
runner = (ROOT / ".github/scripts/run-codebuild.sh").read_text()
install = (ROOT / ".github/scripts/install-k8s-tools.sh").read_text()
terraform = {p.name: p.read_text() for p in sorted(TF.glob("*.tf"))}
REF = {s: json.loads((ROOT / f"infra/tests/fixtures/aws-service-reference/{s}.json").read_text())["actions"]
       for s in ("codebuild", "eks", "iam", "sts")}

ACCOUNT, REGION, REPO = "780976819607", "us-east-1", "finrisk-ai-inference"
CODEBUILD_ROLE = f"arn:aws:iam::{ACCOUNT}:role/finrisk-ai-codebuild-deploy-example"
EDIT = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"
CLUSTER_ADMIN = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
GROUP = "finrisk-digest-writer"
# The one IAM change of V2 PR 2b: the runners' access entries may carry this group, and no other.
ACCESS_ENTRY_CONDITION = {
    "ArnLike": {"eks:principalArn": f"arn:aws:iam::{ACCOUNT}:role/finrisk-ai-codebuild-*"},
    "StringEquals": {"eks:accessEntryType": "STANDARD"},
    "ForAllValues:StringEquals": {"eks:kubernetesGroups": GROUP},
    "Null": {"eks:username": "true"}}


def as_list(v):
    return [v] if isinstance(v, str) else v


def block(text, header):
    start = text.index(header)
    depth = 0
    for i in range(text.index("{", start), len(text)):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return text[start:i + 1]
    raise ValueError(header)


def stmt(policy, sid):
    return next(s for s in policy["Statement"] if s["Sid"] == sid)


# IAM silently ignores unknown condition keys, so every service key must be one AWS lists for
# that action (action or resource keys) in the service reference fixtures.
def unknown_condition_keys(policy):
    bad = []
    for s in policy["Statement"]:
        keys = {k for op in s.get("Condition", {}).values() for k in op}
        for action in as_list(s["Action"]):
            svc, name = action.split(":")
            if svc not in REF:
                continue
            ref = REF[svc][name]
            allowed = set(ref["condition_keys"]) | set(ref["resource_condition_keys"])
            allowed |= {re.sub(r"\$\{[^}]+\}", "*", k) for k in allowed}
            for k in keys:
                if k.startswith("aws:"):
                    continue
                if not any(fnmatchcase(k, a) for a in allowed):
                    bad.append(f"{s['Sid']}:{action}:{k}")
    return bad


def template_variables(template, cfg):
    """The ${name} a buildspec template uses, and the names its templatefile call passes; templatefile
    fails at PLAN on a missing one."""
    used = set(re.findall(r"(?<!\$)\$\{(\w+)\}", template))
    call = cfg[cfg.index("buildspec = templatefile("):]
    passed = set(re.findall(r"^\s+(\w+)\s+=", call[:call.index("\n    })")], re.M))
    return used, passed


def kubectl_checked(deploy, bootstrap):
    """Both buildspecs install kubectl only after checking it against the pinned sha256: the deploy
    inline, the bootstrap through fetch (defined first, and checking every download)."""
    fetch = ('        fetch() {\n          curl -fsSL --retry 3 --retry-connrefused --retry-max-time 20 --max-time 40 -o "$1" "$2"\n'
             '          echo "$3  $1" | sha256sum --check --strict\n        }\n')
    fetched = ('        fetch /tmp/kubectl "https://dl.k8s.io/release/${kubectl_version}/bin/linux/amd64/kubectl" "${kubectl_sha256}"\n'
               '        install -m 0755 /tmp/kubectl ')
    return '        echo "${kubectl_sha256}  /tmp/kubectl" | sha256sum --check --strict\n        install -m 0755 /tmp/kubectl ' in deploy \
        and fetch in bootstrap and fetched in bootstrap and bootstrap.index(fetch) < bootstrap.index(fetched)


def render(tpl, **values):
    for k, v in values.items():
        tpl = tpl.replace("${" + k + "}", v)
    return tpl.replace("$${", "${")


# --- Buildspec inputs: known at PLAN, so the reviewed plan text shows each buildspec in full ---
# An allowlist. A value that reaches either CodeBuild templatefile, directly, through locals or through
# a nested templatefile, may use only variables, path, literals, the pure functions below, and the
# listed attributes (each checked below to be known at PLAN). Anything else (a managed resource's
# attribute in any form, a data source, a module, count or each, or an impure function such as
# timestamp) is refused: it could make the buildspec "(known after apply)" in the plan, and the
# cluster-admin buildspec would no longer be reviewed.
FUNCTIONS = {"templatefile", "file", "filesha256", "base64gzip", "base64encode", "jsonencode", "jsondecode",
             "join", "format", "lower", "upper", "replace", "coalesce"}
KNOWN_AT_PLAN = {"aws_ecr_repository.inference.name", "data.aws_caller_identity.current.account_id"}
REFERENCE = re.compile(r"(?<![\w.\]])([A-Za-z_][\w-]*)((?:\s*\.\s*(?:[A-Za-z_][\w-]*|\*)|\s*\[[^\]]*\])+)")


def scan(text, i=0, close=None):
    """An HCL expression from i to the bracket `close` that matches (or the end): its code, with string
    text blanked but ${...} interpolations kept and comments dropped, and the index after `close`.
    Heredocs and %{ } directives raise ValueError rather than being guessed at."""
    code, depth = [], 0
    while i < len(text):
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                if text[i] == "\\":
                    i += 2
                elif text.startswith(("$${", "%%{"), i):
                    i += 3
                elif text.startswith("%{", i):
                    raise ValueError("template directive")
                elif text.startswith("${", i):
                    inner, i = scan(text, i + 2, "}")
                    code.append(f" {inner} ")
                else:
                    i += 1
            code.append(' "" ')
            i += 1
            continue
        if c == "#" or text.startswith("//", i):
            i = text.find("\n", i) % (len(text) + 1)
            continue
        if text.startswith(("<<", "/*"), i):
            raise ValueError("heredoc or block comment")
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                if c != close:
                    raise ValueError("unbalanced " + c)
                return "".join(code), i + 1
            depth -= 1
        code.append(c)
        i += 1
    if close:
        raise ValueError("unterminated")
    return "".join(code), i


def local_definitions(sources):
    """Each local's full expression (multi-line ones included), from every locals block."""
    defs = {}
    for text in sources.values():
        for start in [m.start() for m in re.finditer(r"^locals \{", text, re.M)]:
            body = block(text[start:], "locals {")
            for m in re.finditer(r"^  (\w+)\s*=(.*?)(?=^  \w+\s*=|\Z)", body[body.index("{") + 1:-1], re.M | re.S):
                defs[m[1]] = m[2]
    return defs


def buildspec_inputs(cfg):
    """The code of everything passed to one CodeBuild project's buildspec templatefile."""
    start = cfg.index("buildspec = templatefile(") + len("buildspec = templatefile(")
    return scan(cfg, start, ")")[0]


def unknown_at_plan(code, defs, seen=()):
    """Everything in an expression's code that may be unknown until APPLY: what the allowlist lacks."""
    bad = [f"{f}()" for f in re.findall(r"(?<![\w.])([A-Za-z_]\w*)\s*\(", code) if f not in FUNCTIONS]
    loop_vars = {v for pair in re.findall(r"\bfor\s+(\w+)(?:\s*,\s*(\w+))?\s+in\b", code) for v in pair if v}
    for root, trailer in REFERENCE.findall(code):
        path = root + re.sub(r"\s+", "", trailer)
        if root in ("var", "path") or root in loop_vars:
            continue
        if root == "local":
            name = re.match(r"\s*\.\s*(\w+)", trailer)[1]
            if name not in defs:
                bad.append(path)
            elif name not in seen:
                bad += [f"{path}: {b}" for b in unknown_at_plan(scan(defs[name])[0], defs, (*seen, name))]
        elif re.sub(r"\[[^\]]*\]", "", path) not in KNOWN_AT_PLAN:
            bad.append(path)
    return bad


def known_attributes_are_known():
    """The allowlisted attributes: the repository's name is a configured argument made of known
    values, and the caller identity is a data source without arguments, read during PLAN."""
    name = re.search(r'^  name\s+= (.+)$', block(terraform["ecr.tf"], 'resource "aws_ecr_repository" "inference"'), re.M)
    return bool(name) and not unknown_at_plan(scan(name[1])[0], LOCALS) \
        and 'data "aws_caller_identity" "current" {}' in terraform["security.tf"] \
        and len(re.findall(r'data "aws_caller_identity"', "".join(terraform.values()))) == 1


def rendered_size(template, values, embedded):
    """The rendered length: every ${name} replaced by a value of its real length (values, else a 64-hex
    sha256), each embedded payload by base64 of its gzip. Python's level 6 came out 24 characters longer
    than Terraform's base64gzip for the bootstrap bundle (terraform 1.9.8), so this errs slightly high."""
    rendered = template.replace("$${", "\0")
    for name, data in embedded.items():
        rendered = rendered.replace("${" + name + "}", base64.b64encode(gzip.compress(data, 6)).decode())
    rendered = re.sub(r"\$\{(\w+)\}", lambda m: values.get(m[1], "0" * 64), rendered)
    return len(rendered.replace("\0", "${"))


def access_entry_allowed(condition, principal, entry_type, groups, username=None):
    """IAM's evaluation of this statement's condition for one CreateAccessEntry request."""
    keys = {"eks:principalArn": [principal], "eks:accessEntryType": [entry_type], "eks:kubernetesGroups": groups,
            "eks:username": [username] if username else []}
    for operator, tests in condition.items():
        for key, expected in tests.items():
            present, expected = keys[key], as_list(expected)
            if operator == "ArnLike":
                ok = bool(present) and all(matches(v, expected) for v in present)
            elif operator == "StringEquals":
                ok = bool(present) and all(v in expected for v in present)
            elif operator == "ForAllValues:StringEquals":
                ok = all(v in expected for v in present)
            elif operator == "ForAnyValue:StringEquals":
                ok = any(v in expected for v in present)
            elif operator == "Null":
                ok = (not present) == (expected == ["true"])
            else:
                raise ValueError(operator)
            if not ok:
                return False
    return True


RUNNER = f"arn:aws:iam::{ACCOUNT}:role/finrisk-ai-codebuild-deploy-abc"
ACCESS_ENTRY_REQUESTS = {  # (principal, type, groups, username) -> allowed
    "a runner entry without groups (V1, PR 2a, the bootstrap's)": ((RUNNER, "STANDARD", []), True),
    "the deploy runner with the digest-writer group": ((RUNNER, "STANDARD", [GROUP]), True),
    "system:masters": ((RUNNER, "STANDARD", ["system:masters"]), False),
    "the group plus system:masters": ((RUNNER, "STANDARD", [GROUP, "system:masters"]), False),
    "a custom username": ((RUNNER, "STANDARD", [GROUP], "admin"), False),
    "the group on a non-runner role": ((f"arn:aws:iam::{ACCOUNT}:role/finrisk-ai-eks-nodes-x", "STANDARD", [GROUP]), False),
    "the group on an EC2_LINUX entry": ((RUNNER, "EC2_LINUX", [GROUP]), False),
}


def access_entry_semantics(condition):
    return all(access_entry_allowed(condition, *request) == ok for request, ok in ACCESS_ENTRY_REQUESTS.values())


# --- IAM evaluation helpers for the boundary (allow + principal match, no deny) ------------
def matches(value, patterns):
    return any(fnmatchcase(value.lower(), p.lower()) for p in as_list(patterns))


def boundary_allows(action, principal):
    def applies(s):
        pattern = s.get("Condition", {}).get("ArnLike", {}).get("aws:PrincipalArn")
        return matches(action, s["Action"]) and (pattern is None or matches(principal, pattern))
    hits = [s for s in boundary["Statement"] if applies(s)]
    return any(s["Effect"] == "Allow" for s in hits) and not any(s["Effect"] == "Deny" for s in hits)


# --- The URI check, executed in bash exactly as rendered ------------------------------------
uri_block = re.search(r'(if \[\[ ! "\$FINRISK_IMAGE_URI" =~ .*?\n\s*fi\n)', deploy_spec, re.S).group(1)
uri_script = 'FINRISK_IMAGE_URI="$1"\n' + render(uri_block, account_id=ACCOUNT, region=REGION, repository=REPO) + "echo ACCEPTED\n"
GOOD = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{REPO}@sha256:" + "a" * 64
URI_CASES = {
    GOOD: True,
    f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{REPO}:sha-" + "a" * 40: False,
    GOOD.replace(ACCOUNT, "111122223333"): False,
    GOOD.replace(REGION, "us-west-2"): False,
    GOOD.replace(f"{REPO}@", f"{REPO}-evil@"): False,
    GOOD[:-64] + "A" * 64: False,
    GOOD[:-1]: False,
    GOOD + "a": False,
    GOOD + ";curl evil": False,
    GOOD[:-64] + "$(id)" + "a" * 59: False,
    GOOD + "\n": False,
    " " + GOOD: False,
    GOOD.replace(".dkr.", "Xdkr."): False,
    "": False,
    "unset": False,
}
uri_results = {v: "ACCEPTED" in subprocess.run(["bash", "-c", uri_script, "uri-check", v],
                                               capture_output=True, text=True).stdout
               for v in URI_CASES}
# Both builds refuse a gitops revision that is not a commit ("unset" when PLAN passed none), first thing.
REVISION_CHECKS = {
    "bootstrap": ('        FINRISK_GITOPS_REVISION=${gitops_revision}\n'
                  '        [[ "$FINRISK_GITOPS_REVISION" =~ ^[0-9a-f]{40}$ ]] || { echo "gitops revision refused: '
                  '$FINRISK_GITOPS_REVISION"; exit 1; }\n', bootstrap_spec, "mkdir -p"),
    "deploy": ('        TARGET_REVISION=${gitops_revision}\n', deploy_spec, "curl -fsSL"),
}
revision_refusals = {}
for name, (line, spec, first) in REVISION_CHECKS.items():
    check = re.search(r'^.*\[\[ "\$(?:FINRISK_GITOPS_REVISION|TARGET_REVISION)" =~ .*$', spec, re.M)
    probe = (re.search(r"^ *(\w+)=\$\{gitops_revision\}$", spec, re.M)[1] + '="$1"\n' + check[0] + "\necho ACCEPTED\n") if check else ""
    revision_refusals[name] = line in spec and spec.index(line) < spec.index(first) and check is not None \
        and spec.index(check[0]) < spec.index(first) and all(
            ("ACCEPTED" in subprocess.run(["bash", "-c", probe, "check", v], capture_output=True, text=True).stdout) == ok
            for v, ok in (("unset", False), ("", False), ("a" * 40, True), ("A" * 40, False), ("a" * 39, False), ("a" * 41, False)))

runtime = json.loads(render(runtime_tpl, region=REGION, account_id=ACCOUNT,
                            subnet_arns='["arn:aws:ec2:us-east-1:780976819607:subnet/subnet-a"]',
                            log_group_name="/finrisk/codebuild/finrisk-ai-portfolio",
                            cluster_arn=f"arn:aws:eks:{REGION}:{ACCOUNT}:cluster/finrisk-ai-portfolio"))
runtime_actions = {a for s in runtime["Statement"] for a in as_list(s["Action"])}

override_denies = [s for s in release["Statement"] if s["Sid"].startswith("DenyOverride")]
denied_keys = {k for s in override_denies for k in s["Condition"]["Null"]}
# The deploy build legitimately sets one environment variable, so the environment section and
# the env-var keys are governed by the dedicated statements instead of a blanket Null deny.
ENV_GOVERNED = {"codebuild:environment"}
uncovered_startbuild_keys = [
    k for k in REF["codebuild"]["StartBuild"]["condition_keys"]
    if k not in ENV_GOVERNED and not k.startswith("codebuild:environment.environmentVariables")
    and not any(k == d or k.startswith(d + ".") or k.startswith(d + "/") for d in denied_keys)
]
release_allowed = {a for s in release["Statement"] if s["Effect"] == "Allow" for a in as_list(s["Action"])}
deploy_cfg = block(path_tf, 'resource "aws_codebuild_project" "k8s_deploy"')
deploy_entry = block(path_tf, 'resource "aws_eks_access_entry" "k8s_deploy"')
bootstrap_entry = block(path_tf, 'resource "aws_eks_access_entry" "k8s_bootstrap"')
gitops_variable = block(variables, 'variable "gitops_revision"')
access_statement = stmt(deployer_path, "CreateCodeBuildAccessEntries")
role = next((d for d in inference_app if d["kind"] == "Role"), {})
binding = next((d for d in inference_app if d["kind"] == "RoleBinding"), {})
bootstrap_cfg = block(path_tf, 'resource "aws_codebuild_project" "k8s_bootstrap"')
edit_assoc = block(path_tf, 'resource "aws_eks_access_policy_association" "k8s_deploy_edit"')
admin_assoc = block(path_tf, 'resource "aws_eks_access_policy_association" "k8s_bootstrap_cluster_admin"')
cluster = block(eks, 'resource "aws_eks_cluster" "platform"')
LOCALS = local_definitions(terraform)
bootstrap_inputs, deploy_inputs = buildspec_inputs(bootstrap_cfg), buildspec_inputs(deploy_cfg)
# Negative controls: a value unknown at PLAN, added to the bootstrap's templatefile map, is caught in
# every form; through a local too.
UNKNOWN_INPUTS = {
    "the cluster endpoint": "cluster_endpoint = aws_eks_cluster.platform[0].endpoint",
    "a nested attribute (the cluster CA)": "cluster_ca = aws_eks_cluster.platform[0].certificate_authority[0].data",
    "a splat (the subnet IDs)": "subnets = jsonencode(aws_subnet.private[*].id)",
    "an unlisted attribute of the allowlisted resource": "registry = aws_ecr_repository.inference.registry_id",
    "the OIDC issuer": "issuer = aws_eks_cluster.platform[0].identity[0].oidc[0].issuer",
    "the NAT gateway's public IP": "nat_ip = aws_nat_gateway.platform.public_ip",
    "a data source not on the list": "vpc = data.aws_vpc.default.id",
    "an impure function": "built_at = timestamp()",
    "a nested templatefile": 'inference_app_b64 = base64gzip(templatefile("${path.module}/../k8s/x.yaml.tftpl", {\n'
                             "        image_repository = aws_ecr_repository.inference.repository_url\n      }))",
}
unknown_controls = {name: unknown_at_plan(buildspec_inputs(bootstrap_cfg.replace(
    "      cluster_name ", f"      {line}\n      cluster_name ", 1)), LOCALS) for name, line in UNKNOWN_INPUTS.items()}
indirect = dict(LOCALS, k8s_cluster_name=" aws_iam_role.codebuild_bootstrap[0].arn\n")
# The image repository spelled out from known values; repository_url is unknown until the repository exists.
url_repository = dict(LOCALS, inference_repository=" aws_ecr_repository.inference.repository_url\n")
install_pins = dict(re.findall(r'^(\w+)="([^"]+)"$', install, re.M))
tf_pins = dict(re.findall(r'^  (\w+)\s+= "([^"]*)"$', path_tf, re.M))
deploy_jobs = yaml.safe_load(deploy_wf)["jobs"]["deploy"]
wait = {s["name"]: int(s.get("env", {}).get("CODEBUILD_WAIT_MINUTES", 0)) for s in deploy_jobs["steps"] if "name" in s}
timeouts = {name: (int(re.search(r"build_timeout\s+= (\d+)", cfg)[1]), int(re.search(r"queued_timeout\s+= (\d+)", cfg)[1]))
            for name, cfg in (("bootstrap", bootstrap_cfg), ("deploy", deploy_cfg))}
session = int(re.search(r"role-duration-seconds: (\d+)", deploy_wf)[1]) // 60
manifests = ROOT / "infra/k8s"
# The bootstrap's bundle as deploy_path.tf builds it: a "#==> <file>" line before each file.
bundle = "".join(f"#==> {f}\n" + (manifests / f).read_text()
                 for f in re.findall(r'"([^"]+)"', re.search(r"k8s_bootstrap_files\s+= \[(.*)\]", path_tf)[1])).encode()
REAL = {"cluster_name": "finrisk-ai-portfolio", "region": REGION, "account_id": ACCOUNT, "repository": REPO, "namespace": "finrisk",
        "argocd_namespace": "argocd", "monitoring_namespace": "monitoring", "app": "finrisk-inference", "node_instance_type": "m7i-flex.large",
        "kubectl_version": "v1.35.9", "helm_version": "v4.3.0", "argocd_chart_version": "10.9.6", "gitops_revision": "a" * 40,
        "image_repository": f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{REPO}", "repo_url": "https://github.com/ccooper-data/finrisk-ai.git",
        "chart_path": "charts/finrisk-inference", "prometheus_url": "http://monitoring-prometheus.monitoring.svc.cluster.local:9090"}
sizes = {
    "bootstrap": rendered_size(bootstrap_spec, REAL, {"k8s_bundle_b64": bundle}),
    "deploy": rendered_size(deploy_spec, REAL, {}),
}
evidence_lines = {name: re.findall(r'(?:echo "|print\(")FINRISK_EVIDENCE ([^"]*)"', spec) for name, spec in
                  (("bootstrap", bootstrap_spec), ("deploy", deploy_spec))}

checks = {
    # Cluster authorization and network
    "API-only auth, no implicit creator admin": 'authentication_mode                         = "API"' in cluster
        and "bootstrap_cluster_creator_admin_permissions = false" in cluster,
    "dedicated control-plane SG carries the runner rule": "security_group_ids = [aws_security_group.eks_api[0].id]" in cluster
        and "security_group_id            = aws_security_group.eks_api[0].id" in path_tf
        and "referenced_security_group_id = aws_security_group.codebuild[0].id" in path_tf,
    "no rule on the node-shared cluster SG": "cluster_security_group_id" not in path_tf,
    "runners in private subnets only": deploy_cfg.count("subnets            = aws_subnet.private[*].id") == 1
        and bootstrap_cfg.count("subnets            = aws_subnet.private[*].id") == 1,
    "fixed buildspecs, no source": deploy_cfg.count('type = "NO_SOURCE"') == 1 and bootstrap_cfg.count('type = "NO_SOURCE"') == 1,
    "unprivileged, serialized builds": all("privileged_mode             = false" in c and "concurrent_build_limit = 1" in c
                                            for c in (deploy_cfg, bootstrap_cfg)),
    "runner roles boundary-capped and project-bound": path_tf.count('permissions_boundary = "arn:aws:iam::${local.account_id}:policy/finrisk-ai-eks-boundary"') == 2
        and path_tf.count('variable = "aws:SourceArn"') == 2,
    "deploy runner: Edit scoped to finrisk only": f'policy_arn    = "${{local.eks_access_policy}}/AmazonEKSEditPolicy"' in edit_assoc
        and 'type       = "namespace"' in edit_assoc and "namespaces = [local.k8s_app_namespace]" in edit_assoc
        and re.search(r'^  k8s_app_namespace\s+= "finrisk"$', path_tf, re.M) is not None,
    "bootstrap runner: cluster admin at cluster scope": "AmazonEKSClusterAdminPolicy" in admin_assoc and 'type = "cluster"' in admin_assoc,
    "metrics-server add-on after nodes": 'addon_name   = "metrics-server"' in path_tf and "depends_on = [aws_eks_node_group.platform]" in path_tf,
    "kubectl pinned with fixed checksum, checked before it is installed": re.search(r'kubectl_version = "v1\.35\.\d+"', path_tf) is not None
        and re.search(r'kubectl_sha256  = "[0-9a-f]{64}"', path_tf) is not None
        and kubectl_checked(deploy_spec, bootstrap_spec),
    "negative control: the bootstrap's kubectl without its checksum is caught": not kubectl_checked(deploy_spec, bootstrap_spec.replace(
        'fetch /tmp/kubectl "https://dl.k8s.io/release/${kubectl_version}/bin/linux/amd64/kubectl" "${kubectl_sha256}"',
        'curl -fsSLo /tmp/kubectl "https://dl.k8s.io/release/${kubectl_version}/bin/linux/amd64/kubectl"')),
    "negative control: a bootstrap fetch that skips the checksum is caught": not kubectl_checked(
        deploy_spec, bootstrap_spec.replace('          echo "$3  $1" | sha256sum --check --strict\n', "")),
    "negative control: the deploy's kubectl without its checksum is caught": not kubectl_checked(
        deploy_spec.replace('        echo "${kubectl_sha256}  /tmp/kubectl" | sha256sum --check --strict\n', ""), bootstrap_spec),
    # Buildspecs and manifest
    "deploy validates FINRISK_IMAGE_URI before use": deploy_spec.index("FINRISK_IMAGE_URI rejected") < deploy_spec.index("curl -fsSL "),
    "URI check accepts only the digest-pinned repo URI": all(uri_results[v] == ok for v, ok in URI_CASES.items()),
    **{f"{name} refuses a gitops revision that is not a commit, before anything else": ok for name, ok in revision_refusals.items()},
    "bootstrap creates its three namespaces idempotently, labelled before helm runs":
        'for ns in "${namespace}" "$A" "$M"; do' in bootstrap_spec
        and 'create namespace "$ns" --dry-run=client -o yaml' in bootstrap_spec and "--create-namespace" not in bootstrap_spec
        and bootstrap_spec.index('label namespace "$ns"') < bootstrap_spec.index('"$H" upgrade --install')
        and 'A="${argocd_namespace}"' in bootstrap_spec and 'M="${monitoring_namespace}"' in bootstrap_spec
        and re.search(r'k8s_argocd_namespace\s+= "argocd"', path_tf) and re.search(r'k8s_monitoring_namespace\s+= "monitoring"', path_tf),
    "no impersonation": "--as" not in deploy_spec and "--as" not in bootstrap_spec,
    # The commit pin is a literal in the build command, never an environment variable a StartBuild could
    # override, and only the bootstrap names it FINRISK_GITOPS_REVISION (the PLAN step greps for it).
    "FINRISK_GITOPS_REVISION: a literal in the bootstrap's command only, no buildspec or project variables":
        bootstrap_spec.count("FINRISK_GITOPS_REVISION=") == 1 and "FINRISK_GITOPS_REVISION" not in deploy_spec
        and not re.search(r"^\s*(variables|parameter-store|secrets-manager|exported-variables):", bootstrap_spec + deploy_spec, re.M)
        and "environment_variable" not in bootstrap_cfg
        and re.findall(r'environment_variable \{\s*name\s+= "(\w+)"', deploy_cfg) == ["FINRISK_IMAGE_URI"],
    "gitops_revision: null by default (DESTROY, the reaper), else a full commit SHA": 'type        = string' in gitops_variable
        and "default     = null" in gitops_variable and "nullable    = true" in gitops_variable
        and 'var.gitops_revision == null || can(regex("^[0-9a-f]{40}$", var.gitops_revision))' in gitops_variable
        and re.search(r'^  gitops_revision\s+= coalesce\(var\.gitops_revision, "unset"\)$', path_tf, re.M) is not None,
    "both buildspecs get the commit, the bootstrap also the image repository; the deploy has no manifest":
        re.search(r"^\s+gitops_revision\s+= local\.gitops_revision$", bootstrap_cfg, re.M) is not None
        and re.search(r"^\s+image_repository\s+= local\.inference_repository$", bootstrap_cfg, re.M) is not None
        and all(re.search(rf"^\s+{k}\s+= local\.{v}$", deploy_cfg, re.M) for k, v in (
            ("gitops_revision", "gitops_revision"), ("repo_url", "gitops_repo_url"), ("chart_path", "gitops_chart_path"),
            ("prometheus_url", "prometheus_url")))
        and "manifest_b64" not in path_tf + deploy_spec and not (ROOT / "infra/k8s/inference.yaml").exists(),
    # Kubernetes group: the deploy runner's entry only, the same literal in Terraform, IAM and the RoleBinding.
    "the deploy runner's access entry carries exactly the digest-writer group; the bootstrap's none":
        "kubernetes_groups = [local.k8s_digest_writer_group]" in deploy_entry and "kubernetes_groups" not in bootstrap_entry
        and path_tf.count("kubernetes_groups") == 1
        and re.search(rf'^  k8s_digest_writer_group\s+= "{GROUP}"$', path_tf, re.M) is not None,
    "the RoleBinding binds that group to the Role, in finrisk": binding.get("subjects") == [
        {"apiGroup": "rbac.authorization.k8s.io", "kind": "Group", "name": GROUP}]
        and binding.get("roleRef") == {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": role.get("metadata", {}).get("name")}
        and binding["metadata"].get("namespace") == role["metadata"].get("namespace") == "finrisk",
    "the Edit association is unchanged (namespace finrisk)": edit_assoc.count("namespaces = [local.k8s_app_namespace]") == 1,
    "helm and the Argo CD chart pinned with fixed checksums, the same as CI's":
        re.fullmatch(r"v\d+\.\d+\.\d+", tf_pins.get("helm_version", "")) is not None
        and all(re.fullmatch(r"[0-9a-f]{64}", tf_pins.get(k, "")) for k in ("helm_sha256", "argocd_chart_sha256"))
        and (tf_pins.get("helm_version"), tf_pins.get("helm_sha256"), tf_pins.get("argocd_chart_version"), tf_pins.get("argocd_chart_sha256"))
        == (install_pins.get("HELM_VERSION"), install_pins.get("HELM_SHA256"), install_pins.get("ARGOCD_CHART_VERSION"),
            install_pins.get("ARGOCD_CHART_SHA256")),
    # PLAN-time knowledge: the plan text must show both buildspecs, not "(known after apply)".
    "each buildspec template uses exactly the variables Terraform passes it": all(
        used == passed and used for used, passed in (template_variables(bootstrap_spec, bootstrap_cfg),
                                                     template_variables(deploy_spec, deploy_cfg))),
    "negative control: a template variable Terraform does not pass is caught": (lambda u, p: u != p)(
        *template_variables(deploy_spec + "${digest_writer_group}", deploy_cfg)),
    "both buildspecs take only values known at PLAN (an allowlist)": "local.k8s_cluster_name" in bootstrap_inputs
        and "local.account_id" in deploy_inputs and not unknown_at_plan(bootstrap_inputs, LOCALS)
        and not unknown_at_plan(deploy_inputs, LOCALS),
    "the allowlisted attributes are known at PLAN": known_attributes_are_known(),
    **{f"negative control: {name} in the bootstrap buildspec is caught": bool(found) for name, found in unknown_controls.items()},
    "negative control: an attribute reached through a local is caught": unknown_at_plan(bootstrap_inputs, indirect)
        == ["local.k8s_cluster_name: aws_iam_role.codebuild_bootstrap[0].arn"],
    "the image repository and the commit reach the buildspecs through the allowlist (never repository_url)":
        "local.inference_repository" in bootstrap_inputs and "local.gitops_revision" in bootstrap_inputs
        and "local.gitops_revision" in deploy_inputs and "inference.repository_url" not in path_tf
        and re.search(r'^  inference_repository\s+= "\$\{local\.account_id\}\.dkr\.ecr\.\$\{var\.aws_region\}\.amazonaws\.com/'
                      r'\$\{aws_ecr_repository\.inference\.name\}"$', path_tf, re.M) is not None,
    "negative control: the image repository as repository_url is caught": unknown_at_plan(bootstrap_inputs, url_repository)
        == ["local.inference_repository: aws_ecr_repository.inference.repository_url"],
    # run-codebuild.sh stops reading logs at the first terminal match; the bootstrap's is checked in
    # test_cluster_addons.py, and in the deploy only the result lines may match.
    "deploy evidence: only the result lines match the terminal regex": bool(evidence_lines["deploy"]) and all(
        bool(re.search(r"result=|bootstrap=", line)) == line.startswith("result=") for line in evidence_lines["deploy"]),
    # The inline buildspec limit is not on the CodeBuild quotas page; a secondary source says 25,600.
    **{f"{name} buildspec renders to at most 20,000 characters (about {size:,})": size <= 20000 for name, size in sizes.items()},
    "build timeouts: bootstrap 25, deploy 30, each queued at most 10": timeouts == {"bootstrap": (25, 10), "deploy": (30, 10)},
    "workflow waits cover queue plus build: bootstrap 35, deploy 45":
        wait.get("Bootstrap cluster add-ons") == 35 >= sum(timeouts["bootstrap"])
        and wait.get("Deploy digest-pinned image") == 45 >= sum(timeouts["deploy"]),
    "job timeout covers both waits and cleanup, inside the role session":
        deploy_jobs["timeout-minutes"] == 90 >= wait.get("Bootstrap cluster add-ons", 99) + wait.get("Deploy digest-pinned image", 99) + 5
        and deploy_jobs["timeout-minutes"] <= session == 120,
    # Release role IAM
    "release role can only push images and run the two builds": release_allowed == {
        "ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:CompleteLayerUpload",
        "ecr:DescribeImages", "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart",
        "codebuild:StartBuild", "codebuild:BatchGetBuilds", "codebuild:StopBuild", "logs:GetLogEvents"},
    "release policy uses only real StartBuild condition keys": not unknown_condition_keys(release),
    "one Null deny per override key (keys are ANDed within a statement)": len(override_denies) >= 15
        and all(list(s["Condition"]) == ["Null"] and len(s["Condition"]["Null"]) == 1
                and list(s["Condition"]["Null"].values()) == ["false"] for s in override_denies),
    "every StartBuild override key is denied (itself or its section)": not uncovered_startbuild_keys,
    "bootstrap denies the whole environment section": stmt(release, "BootstrapAcceptsNoEnvironmentOverride")["Condition"]
        == {"Null": {"codebuild:environment": "false"}},
    "buildspec, image, role and privileged overrides denied": {"codebuild:source.buildspec", "codebuild:environment.image",
        "codebuild:serviceRole", "codebuild:environment.privilegedMode", "codebuild:source.location"}
        <= {k for s in override_denies for k in s["Condition"]["Null"]},
    "deploy accepts only FINRISK_IMAGE_URI": stmt(release, "DeployAcceptsOnlyFinriskImageUri")["Condition"]
        == {"ForAnyValue:StringNotEquals": {"codebuild:environment.environmentVariables.name": "FINRISK_IMAGE_URI"}},
    "deploy requires a digest-pinned image in this repo": stmt(release, "DeployRequiresDigestPinnedImage")["Condition"]
        == {"StringNotLike": {"codebuild:environment.environmentVariables/FINRISK_IMAGE_URI.value":
                              f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{REPO}@sha256:*"}},
    "bootstrap accepts no environment variables": stmt(release, "BootstrapAcceptsNoEnvironmentVariables")["Condition"]
        == {"Null": {"codebuild:environment.environmentVariables.name": "false"}},
    "release inline policy fits": len(json.dumps(release, separators=(",", ":"))) <= 10240,
    "release trust bound to portfolio-release": release_trust["Statement"][0]["Condition"]["StringEquals"] == {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:ccooper-data@314428882/finrisk-ai@1384434300:environment:portfolio-release"},
    # Terraform role additions
    "deployer additions use only real condition keys": not unknown_condition_keys(deployer_path),
    "runner roles must carry the boundary": stmt(deployer_path, "CreateBoundedCodeBuildRunnerRoles")["Condition"]
        == {"StringEquals": {"iam:PermissionsBoundary": f"arn:aws:iam::{ACCOUNT}:policy/finrisk-ai-eks-boundary"}},
    "only Edit (deploy) or ClusterAdmin (bootstrap) can be associated": stmt(deployer_path, "DenyAnyOtherAccessPolicy")["Condition"]
        == {"ArnNotEquals": {"eks:policyArn": [EDIT, CLUSTER_ADMIN]}}
        and stmt(deployer_path, "AssociateNamespacedEditToDeployRunner")["Condition"]["ArnEquals"] == {"eks:policyArn": EDIT}
        and stmt(deployer_path, "AssociateNamespacedEditToDeployRunner")["Condition"]["ForAllValues:StringEquals"] == {"eks:namespaces": "finrisk"}
        and all("codebuild-bootstrap-" in r for r in stmt(deployer_path, "AssociateClusterAdminToBootstrapRunner")["Resource"]),
    "projects must be created in a VPC": stmt(deployer_path, "K8sCodeBuildProjectsMustRunInVpc")["Action"] == "codebuild:CreateProject"
        and stmt(deployer_path, "K8sCodeBuildProjectsMustRunInVpc")["Condition"] == {"Null": {"codebuild:vpcConfig.vpcId": "true"}},
    "in-place project updates allowed unless they drop the VPC": stmt(deployer_path, "K8sCodeBuildUpdatesCannotDropVpc")["Condition"]
        == {"Null": {"codebuild:vpcConfig": "false", "codebuild:vpcConfig.vpcId": "true"}},
    "Terraform role cannot assume runner or EKS roles": stmt(deployer_path, "DenyAssumingFinriskRoles")["Resource"]
        == f"arn:aws:iam::{ACCOUNT}:role/finrisk-ai-*" and "sts:AssumeRole" in stmt(deployer_path, "DenyAssumingFinriskRoles")["Action"],
    "no cluster may grant its creator admin": stmt(deployer_path, "DenyClusterCreatorAdmin")["Condition"]
        == {"BoolIfExists": {"eks:bootstrapClusterCreatorAdminPermissions": "true"}}
        and stmt(deployer_path, "DenyNonApiClusterAuth")["Condition"] == {"StringNotEquals": {"eks:authenticationMode": "API"}},
    "runner SG is destroyed while runner roles can still clean up ENIs": "depends_on = [aws_iam_role_policy.codebuild_bootstrap, aws_iam_role_policy.codebuild_deploy]"
        in block(path_tf, 'resource "aws_security_group" "codebuild"') and "create_before_destroy" not in block(path_tf, 'resource "aws_security_group" "codebuild"'),
    "boundary cannot be removed or edited": {"iam:DeleteRolePermissionsBoundary", "iam:PutRolePermissionsBoundary"}
        <= set(stmt(deployer_path, "DenyBoundaryRemoval")["Action"])
        and "iam:CreatePolicyVersion" in stmt(deployer_path, "DenyBoundaryPolicyEdits")["Action"],
    f"deployer managed policy fits ({len(json.dumps(deployer_path, separators=(',', ':'))):,} of 6,144 characters minified)":
        len(json.dumps(deployer_path, separators=(",", ":"))) <= 6144,
    "runner access entries: the digest-writer group or none, no username, STANDARD, runner roles only (exact condition)":
        access_statement["Condition"] == ACCESS_ENTRY_CONDITION and access_statement["Action"] == "eks:CreateAccessEntry",
    "IAM evaluation of that condition: no groups or the one group allowed; any other group, a username or another role denied":
        access_entry_semantics(access_statement["Condition"]),
    "negative control: ForAnyValue (any one matching group) is caught": not access_entry_semantics(
        {**ACCESS_ENTRY_CONDITION, "ForAnyValue:StringEquals": {"eks:kubernetesGroups": GROUP}} | {"ForAllValues:StringEquals": {}}),
    "negative control: dropping the group condition is caught": not access_entry_semantics(
        {k: v for k, v in ACCESS_ENTRY_CONDITION.items() if k != "ForAllValues:StringEquals"}),
    "negative control: the V1 condition (no groups at all) is caught": not access_entry_semantics(
        {**ACCESS_ENTRY_CONDITION, "Null": {"eks:kubernetesGroups": "true", "eks:username": "true"}}),
    # Boundary covers the runners, and only the runners
    "boundary allows every runner action": all(boundary_allows(a, CODEBUILD_ROLE) for a in runtime_actions),
    "runners get no node or cluster workload permissions": not any(boundary_allows(a, CODEBUILD_ROLE) for a in (
        "ec2:AssignPrivateIpAddresses", "ecr:BatchGetImage", "elasticloadbalancing:CreateLoadBalancer",
        "ec2:AuthorizeSecurityGroupIngress", "ssmmessages:CreateControlChannel", "secretsmanager:GetSecretValue")),
    # Workflows: release path separated from the Terraform role
    "deploy and image build use the release environment and role": all(
        "environment: portfolio-release" in w and "vars.AWS_RELEASE_ROLE_ARN" in w and "AWS_DEPLOY_ROLE_ARN" not in w
        for w in (deploy_wf, build_wf)),
    "infrastructure stays on the Terraform role": "environment: portfolio-validation" in provision_wf
        and "vars.AWS_DEPLOY_ROLE_ARN" in provision_wf,
    "runner sends at most one PLAINTEXT override": runner.count("--environment-variables-override") == 1
        and 'type: "PLAINTEXT"' in runner,
}

failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    bad = unknown_condition_keys(release) + unknown_condition_keys(deployer_path)
    if bad:
        print("unknown condition keys:", bad)
    raise SystemExit("EKS deploy path acceptance failed: " + ", ".join(failed))
