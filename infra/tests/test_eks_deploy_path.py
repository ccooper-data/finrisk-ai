#!/usr/bin/env python3
# In-VPC CodeBuild deploy path to the private EKS API: Terraform, buildspecs, IAM, workflows.
import json
import re
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "infra/terraform"
eks = (TF / "eks.tf").read_text()
path_tf = (TF / "deploy_path.tf").read_text()
deploy_spec = (TF / "deploy/deploy-buildspec.yml.tftpl").read_text()
bootstrap_spec = (TF / "deploy/bootstrap-buildspec.yml.tftpl").read_text()
manifest = (ROOT / "infra/k8s/inference.yaml").read_text()
release = json.loads((ROOT / "docs/aws-release-policy.json").read_text())
release_trust = json.loads((ROOT / "docs/aws-release-trust-policy.json").read_text())
deployer_path = json.loads((ROOT / "docs/aws-deployer-deploy-path-policy.json").read_text())
boundary = json.loads((ROOT / "docs/aws-eks-boundary-policy.json").read_text())
runtime_tpl = (TF / "policies/codebuild-runtime.json.tftpl").read_text()
deploy_wf = (ROOT / ".github/workflows/deploy-inference.yml").read_text()
build_wf = (ROOT / ".github/workflows/build-inference-image.yml").read_text()
provision_wf = (ROOT / ".github/workflows/provision-bounded-aws.yml").read_text()
runner = (ROOT / ".github/scripts/run-codebuild.sh").read_text()
REF = {s: json.loads((ROOT / f"infra/tests/fixtures/aws-service-reference/{s}.json").read_text())["actions"]
       for s in ("codebuild", "eks", "iam", "sts")}

ACCOUNT, REGION, REPO = "780976819607", "us-east-1", "finrisk-ai-inference"
CODEBUILD_ROLE = f"arn:aws:iam::{ACCOUNT}:role/finrisk-ai-codebuild-deploy-example"
EDIT = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"
CLUSTER_ADMIN = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"


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


def render(tpl, **values):
    for k, v in values.items():
        tpl = tpl.replace("${" + k + "}", v)
    return tpl.replace("$${", "${")


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
bootstrap_cfg = block(path_tf, 'resource "aws_codebuild_project" "k8s_bootstrap"')
edit_assoc = block(path_tf, 'resource "aws_eks_access_policy_association" "k8s_deploy_edit"')
admin_assoc = block(path_tf, 'resource "aws_eks_access_policy_association" "k8s_bootstrap_cluster_admin"')
cluster = block(eks, 'resource "aws_eks_cluster" "platform"')

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
        and 'k8s_app_namespace     = "finrisk"' in path_tf,
    "bootstrap runner: cluster admin at cluster scope": "AmazonEKSClusterAdminPolicy" in admin_assoc and 'type = "cluster"' in admin_assoc,
    "metrics-server add-on after nodes": 'addon_name   = "metrics-server"' in path_tf and "depends_on = [aws_eks_node_group.platform]" in path_tf,
    "kubectl pinned with fixed checksum": re.search(r'kubectl_version = "v1\.35\.\d+"', path_tf) is not None
        and re.search(r'kubectl_sha256  = "[0-9a-f]{64}"', path_tf) is not None
        and "sha256sum --check --strict" in deploy_spec and "sha256sum --check --strict" in bootstrap_spec,
    # Buildspecs and manifest
    "deploy validates FINRISK_IMAGE_URI before use": deploy_spec.index("FINRISK_IMAGE_URI rejected") < deploy_spec.index("curl -fsSLo"),
    "URI check accepts only the digest-pinned repo URI": all(uri_results[v] == ok for v, ok in URI_CASES.items()),
    "deploy manifest has no Namespace (Edit cannot create it)": "kind: Namespace" not in manifest,
    "HPA owns replicas": re.search(r"^\s*replicas:", manifest, re.M) is None,
    "bootstrap creates namespace idempotently": "create namespace" in bootstrap_spec and "--dry-run=client -o yaml" in bootstrap_spec,
    "no impersonation": "--as" not in deploy_spec and "--as" not in bootstrap_spec,
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
    "deployer managed policy fits": len(json.dumps(deployer_path, separators=(",", ":"))) <= 6144,
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
