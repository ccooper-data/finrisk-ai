data "aws_caller_identity" "current" {}

resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_deploy_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:${var.github_deploy_ref}"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name_prefix        = "${var.project_name}-github-deploy-"
  assume_role_policy = data.aws_iam_policy_document.github_deploy_assume.json

  tags = {
    Purpose = "Short-lived GitHub Actions deployment identity"
  }
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid = "EcrImageDelivery"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:GetAuthorizationToken",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = ["*"]
  }

  statement {
    sid = "ReadClusterMetadata"
    actions = [
      "eks:DescribeCluster",
    ]
    resources = var.enable_eks ? [aws_eks_cluster.platform[0].arn] : []
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name_prefix = "${var.project_name}-deploy-"
  role        = aws_iam_role.github_deploy.id
  policy      = data.aws_iam_policy_document.github_deploy.json
}

resource "aws_kms_key" "artifacts" {
  description             = "FinRisk-AI governed artifact encryption key"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = {
    Purpose = "FinRisk-AI governed artifacts"
  }
}

resource "aws_kms_alias" "artifacts" {
  name          = "alias/${var.project_name}-artifacts"
  target_key_id = aws_kms_key.artifacts.key_id
}
