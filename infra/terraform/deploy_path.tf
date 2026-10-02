# In-VPC deploy path for the private-only EKS API.
#
# GitHub-hosted runners cannot reach the private endpoint, so two CodeBuild projects run inside
# the private subnets with fixed, reviewed buildspecs:
#   - k8s-bootstrap: AmazonEKSClusterAdminPolicy (cluster scope); only creates the namespace.
#   - k8s-deploy:    AmazonEKSEditPolicy scoped to the app namespace; applies, verifies, rolls back.
# The GitHub release role may only start these builds; it cannot edit them (see
# docs/aws-release-policy.json).

locals {
  k8s_cluster_name      = "${var.project_name}-${var.environment}"
  k8s_app_namespace     = "finrisk"
  k8s_app_name          = "finrisk-inference"
  k8s_bootstrap_project = "${var.project_name}-${var.environment}-k8s-bootstrap"
  k8s_deploy_project    = "${var.project_name}-${var.environment}-k8s-deploy"
  codebuild_log_group   = "/finrisk/codebuild/${var.project_name}-${var.environment}"
  codebuild_image       = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
  account_id            = data.aws_caller_identity.current.account_id

  # Latest 1.35 patch; checksum from https://dl.k8s.io/release/v1.35.9/bin/linux/amd64/kubectl.sha256
  kubectl_version = "v1.35.9"
  kubectl_sha256  = "3cfeaf80be482b435b0aa214aff6e0b2c312ee23c0ff20810c75517b6004c6eb"

  served_model = jsondecode(file("${path.module}/../../model/served-model.json"))

  eks_access_policy = "arn:aws:eks::aws:cluster-access-policy"
}

# --- Network: runners reach the API through a dedicated control-plane security group ---------

resource "aws_security_group" "codebuild" {
  count = var.enable_eks ? 1 : 0

  name_prefix = "${var.project_name}-${var.environment}-codebuild-"
  description = "CodeBuild deploy runners: no inbound; HTTPS out to the EKS API and through NAT"
  vpc_id      = aws_vpc.platform.id

  egress {
    description = "HTTPS to the EKS API, AWS APIs and dl.k8s.io"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-codebuild-sg"
  }

  # Destroy order: this group goes before the runner role policies, so CodeBuild can still
  # delete a running build's network interface (with the role's ec2:DeleteNetworkInterface)
  # while Terraform waits to delete the group.
  depends_on = [aws_iam_role_policy.codebuild_bootstrap, aws_iam_role_policy.codebuild_deploy]
}

# Attached only to the control-plane ENIs (vpc_config.security_group_ids). A rule on the
# EKS-managed cluster security group would also open every node and pod to the runners.
resource "aws_security_group" "eks_api" {
  count = var.enable_eks ? 1 : 0

  name_prefix = "${var.project_name}-${var.environment}-eks-api-"
  description = "Private EKS API access for the in-VPC CodeBuild runners only"
  vpc_id      = aws_vpc.platform.id

  tags = {
    Name = "${var.project_name}-${var.environment}-eks-api-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "eks_api_from_codebuild" {
  count = var.enable_eks ? 1 : 0

  security_group_id            = aws_security_group.eks_api[0].id
  referenced_security_group_id = aws_security_group.codebuild[0].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "kubectl from the in-VPC CodeBuild runners"
}

resource "aws_cloudwatch_log_group" "codebuild" {
  count = var.enable_eks ? 1 : 0

  name              = local.codebuild_log_group
  retention_in_days = 7
}

# --- Runner roles: boundary-capped, assumable only by their own CodeBuild project -------------

data "aws_iam_policy_document" "codebuild_bootstrap_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:codebuild:${var.aws_region}:${local.account_id}:project/${local.k8s_bootstrap_project}"]
    }
  }
}

data "aws_iam_policy_document" "codebuild_deploy_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:codebuild:${var.aws_region}:${local.account_id}:project/${local.k8s_deploy_project}"]
    }
  }
}

resource "aws_iam_role" "codebuild_bootstrap" {
  count                = var.enable_eks ? 1 : 0
  name_prefix          = "${var.project_name}-codebuild-bootstrap-"
  assume_role_policy   = data.aws_iam_policy_document.codebuild_bootstrap_assume.json
  permissions_boundary = "arn:aws:iam::${local.account_id}:policy/finrisk-ai-eks-boundary"
}

resource "aws_iam_role" "codebuild_deploy" {
  count                = var.enable_eks ? 1 : 0
  name_prefix          = "${var.project_name}-codebuild-deploy-"
  assume_role_policy   = data.aws_iam_policy_document.codebuild_deploy_assume.json
  permissions_boundary = "arn:aws:iam::${local.account_id}:policy/finrisk-ai-eks-boundary"
}

locals {
  codebuild_runtime_policy = var.enable_eks ? templatefile("${path.module}/policies/codebuild-runtime.json.tftpl", {
    region         = var.aws_region
    account_id     = local.account_id
    subnet_arns    = jsonencode(aws_subnet.private[*].arn)
    log_group_name = local.codebuild_log_group
    cluster_arn    = aws_eks_cluster.platform[0].arn
  }) : null
}

resource "aws_iam_role_policy" "codebuild_bootstrap" {
  count  = var.enable_eks ? 1 : 0
  name   = "codebuild-runtime"
  role   = aws_iam_role.codebuild_bootstrap[0].id
  policy = local.codebuild_runtime_policy
}

resource "aws_iam_role_policy" "codebuild_deploy" {
  count  = var.enable_eks ? 1 : 0
  name   = "codebuild-runtime"
  role   = aws_iam_role.codebuild_deploy[0].id
  policy = local.codebuild_runtime_policy
}

# --- CodeBuild projects: NO_SOURCE with buildspecs fixed in this plan ------------------------

resource "aws_codebuild_project" "k8s_bootstrap" {
  count = var.enable_eks ? 1 : 0

  name                   = local.k8s_bootstrap_project
  description            = "Creates the ${local.k8s_app_namespace} namespace on the private EKS cluster"
  service_role           = aws_iam_role.codebuild_bootstrap[0].arn
  build_timeout          = 15
  queued_timeout         = 10
  concurrent_build_limit = 1

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = local.codebuild_image
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = false
  }

  source {
    type = "NO_SOURCE"
    buildspec = templatefile("${path.module}/deploy/bootstrap-buildspec.yml.tftpl", {
      cluster_name    = local.k8s_cluster_name
      region          = var.aws_region
      namespace       = local.k8s_app_namespace
      kubectl_version = local.kubectl_version
      kubectl_sha256  = local.kubectl_sha256
    })
  }

  vpc_config {
    vpc_id             = aws_vpc.platform.id
    subnets            = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.codebuild[0].id]
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.codebuild[0].name
      stream_name = "k8s-bootstrap"
    }
  }

  # CodeBuild validates the VPC configuration with the service role at create time.
  depends_on = [aws_iam_role_policy.codebuild_bootstrap]
}

resource "aws_codebuild_project" "k8s_deploy" {
  count = var.enable_eks ? 1 : 0

  name                   = local.k8s_deploy_project
  description            = "Deploys the digest-pinned inference image to the ${local.k8s_app_namespace} namespace"
  service_role           = aws_iam_role.codebuild_deploy[0].arn
  build_timeout          = 30
  queued_timeout         = 10
  concurrent_build_limit = 1

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = local.codebuild_image
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = false

    # Placeholder the buildspec rejects; every real build overrides it (IAM requires that).
    environment_variable {
      name  = "FINRISK_IMAGE_URI"
      value = "unset"
    }
  }

  source {
    type = "NO_SOURCE"
    buildspec = templatefile("${path.module}/deploy/deploy-buildspec.yml.tftpl", {
      cluster_name    = local.k8s_cluster_name
      region          = var.aws_region
      account_id      = local.account_id
      repository      = aws_ecr_repository.inference.name
      namespace       = local.k8s_app_namespace
      app             = local.k8s_app_name
      kubectl_version = local.kubectl_version
      kubectl_sha256  = local.kubectl_sha256
      model_sha256    = local.served_model.sha256
      manifest_b64    = base64encode(file("${path.module}/../k8s/inference.yaml"))
    })
  }

  vpc_config {
    vpc_id             = aws_vpc.platform.id
    subnets            = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.codebuild[0].id]
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.codebuild[0].name
      stream_name = "k8s-deploy"
    }
  }

  depends_on = [aws_iam_role_policy.codebuild_deploy]
}

# --- Kubernetes authorization (EKS API mode, no implicit creator admin) ----------------------

resource "aws_eks_access_entry" "k8s_bootstrap" {
  count = var.enable_eks ? 1 : 0

  cluster_name  = aws_eks_cluster.platform[0].name
  principal_arn = aws_iam_role.codebuild_bootstrap[0].arn
  type          = "STANDARD"

  # An access entry silently stops matching if its role is recreated with a new unique ID.
  lifecycle {
    replace_triggered_by = [aws_iam_role.codebuild_bootstrap[0].unique_id]
  }
}

resource "aws_eks_access_policy_association" "k8s_bootstrap_cluster_admin" {
  count = var.enable_eks ? 1 : 0

  cluster_name  = aws_eks_cluster.platform[0].name
  principal_arn = aws_eks_access_entry.k8s_bootstrap[0].principal_arn
  policy_arn    = "${local.eks_access_policy}/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }
}

resource "aws_eks_access_entry" "k8s_deploy" {
  count = var.enable_eks ? 1 : 0

  cluster_name  = aws_eks_cluster.platform[0].name
  principal_arn = aws_iam_role.codebuild_deploy[0].arn
  type          = "STANDARD"

  lifecycle {
    replace_triggered_by = [aws_iam_role.codebuild_deploy[0].unique_id]
  }
}

resource "aws_eks_access_policy_association" "k8s_deploy_edit" {
  count = var.enable_eks ? 1 : 0

  cluster_name  = aws_eks_cluster.platform[0].name
  principal_arn = aws_eks_access_entry.k8s_deploy[0].principal_arn
  policy_arn    = "${local.eks_access_policy}/AmazonEKSEditPolicy"

  access_scope {
    type       = "namespace"
    namespaces = [local.k8s_app_namespace]
  }
}

# --- metrics-server for the HPA (EKS community add-on; needs schedulable nodes) --------------

resource "aws_eks_addon" "metrics_server" {
  count = var.enable_eks ? 1 : 0

  cluster_name = aws_eks_cluster.platform[0].name
  addon_name   = "metrics-server"

  depends_on = [aws_eks_node_group.platform]
}
