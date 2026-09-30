#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "terraform"
security = (ROOT / "security.tf").read_text()
audit = (ROOT / "audit.tf").read_text()
variables = (ROOT / "variables.tf").read_text()

checks = {
    "GitHub OIDC is external data source": 'data "aws_iam_openid_connect_provider" "github"' in security,
    "stack does not create OIDC provider": 'resource "aws_iam_openid_connect_provider"' not in security,
    "stack does not create GitHub deploy role": 'resource "aws_iam_role" "github_deploy"' not in security,
    "stack cannot attach GitHub deploy inline policy": 'aws_iam_role_policy" "github_deploy"' not in security,
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
