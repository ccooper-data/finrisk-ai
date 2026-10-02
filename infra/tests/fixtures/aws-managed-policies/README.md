# AWS managed policy fixtures

Policy documents for the four AWS managed policies attached to the EKS roles, copied from the
[AWS Managed Policy Reference](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/) on 2026-10-01.
`infra/tests/test_second_review_hardening.py` checks that `docs/aws-eks-boundary-policy.json` lets each role use every action here.

| Policy | Default version | Attached to |
|---|---|---|
| AmazonEKSClusterPolicy | v10 | `finrisk-ai-eks-cluster-*` |
| AmazonEKSWorkerNodePolicy | v3 | `finrisk-ai-eks-nodes-*` |
| AmazonEKS_CNI_Policy | v6 | `finrisk-ai-eks-nodes-*` |
| AmazonEC2ContainerRegistryPullOnly | v1 | `finrisk-ai-eks-nodes-*` |

When AWS publishes a new default version, refresh the file here; if the test then fails, widen the boundary in the same reviewed change.
