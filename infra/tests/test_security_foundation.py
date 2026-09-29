#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "terraform"
security = (ROOT / "security.tf").read_text()
audit = (ROOT / "audit.tf").read_text()
variables = (ROOT / "variables.tf").read_text()

checks = {
    "GitHub uses OIDC": 'aws_iam_openid_connect_provider' in security,
    "OIDC audience is STS": 'values   = ["sts.amazonaws.com"]' in security,
    "OIDC subject bound to repo/ref": 'token.actions.githubusercontent.com:sub' in security
        and 'repo:${var.github_repository}:ref:${var.github_deploy_ref}' in security,
    "deploy role uses web identity": "sts:AssumeRoleWithWebIdentity" in security,
    "ECR image permissions scoped": "resources = [aws_ecr_repository.inference.arn]" in security,
    "KMS rotation enabled": "enable_key_rotation     = true" in security,
    "artifact bucket public access blocked": "block_public_policy     = true" in security
        and "restrict_public_buckets = true" in security,
    "artifact bucket uses KMS": 'sse_algorithm     = "aws:kms"' in security,
    "artifact bucket versioned": 'status = "Enabled"' in security,
    "insecure S3 transport denied": "DenyInsecureTransport" in security,
    "CloudTrail defaults off": 'variable "enable_audit_trail"' in variables
        and "default     = false" in variables,
    "CloudTrail validates log files": "enable_log_file_validation    = true" in audit,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Security acceptance failed: " + ", ".join(failed))
