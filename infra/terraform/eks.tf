data "aws_iam_policy_document" "eks_cluster_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eks_cluster" {
  count              = var.enable_eks ? 1 : 0
  name_prefix        = "${var.project_name}-eks-cluster-"
  assume_role_policy = data.aws_iam_policy_document.eks_cluster_assume.json
}

resource "aws_iam_role_policy_attachment" "eks_cluster" {
  count      = var.enable_eks ? 1 : 0
  role       = aws_iam_role.eks_cluster[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_eks_cluster" "platform" {
  count    = var.enable_eks ? 1 : 0
  name     = "${var.project_name}-${var.environment}"
  role_arn = aws_iam_role.eks_cluster[0].arn
  version  = var.eks_cluster_version

  vpc_config {
    subnet_ids              = aws_subnet.private[*].id
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = ["0.0.0.0/0"]
  }

  depends_on = [aws_iam_role_policy_attachment.eks_cluster]

  tags = {
    Name = "${var.project_name}-${var.environment}-eks"
  }
}

data "aws_iam_policy_document" "eks_nodes_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eks_nodes" {
  count              = var.enable_eks ? 1 : 0
  name_prefix        = "${var.project_name}-eks-nodes-"
  assume_role_policy = data.aws_iam_policy_document.eks_nodes_assume.json
}

locals {
  eks_node_policy_arns = var.enable_eks ? toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPullOnly",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
  ]) : toset([])
}

resource "aws_iam_role_policy_attachment" "eks_nodes" {
  for_each   = local.eks_node_policy_arns
  role       = aws_iam_role.eks_nodes[0].name
  policy_arn = each.value
}

resource "aws_eks_node_group" "platform" {
  count           = var.enable_eks ? 1 : 0
  cluster_name    = aws_eks_cluster.platform[0].name
  node_group_name = "portfolio-workers"
  node_role_arn   = aws_iam_role.eks_nodes[0].arn
  subnet_ids      = aws_subnet.private[*].id
  instance_types  = var.eks_node_instance_types
  capacity_type   = "ON_DEMAND"

  scaling_config {
    desired_size = var.eks_node_desired_size
    min_size     = 1
    max_size     = 2
  }

  update_config {
    max_unavailable = 1
  }

  depends_on = [aws_iam_role_policy_attachment.eks_nodes]

  tags = {
    Name = "${var.project_name}-${var.environment}-workers"
  }
}
