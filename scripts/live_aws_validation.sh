#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:=us-east-1}"
: "${TF_DIR:=infra/terraform}"
: "${EVIDENCE_DIR:=evidence/live-aws}"

mkdir -p "$EVIDENCE_DIR"

timestamp() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
record() { printf '%s %s\n' "$(timestamp)" "$*" | tee -a "$EVIDENCE_DIR/run.log"; }

cleanup() {
  status=$?
  record "cleanup_started original_exit=$status"
  terraform -chdir="$TF_DIR" destroy -auto-approve \
    -var='enable_eks=true' \
    -var='enable_nat_gateway=true' \
    -var='enable_observability=true' \
    -var='enable_audit_trail=true' \
    > "$EVIDENCE_DIR/terraform-destroy.log" 2>&1 || {
      record "CRITICAL destroy_failed manual_recovery_required"
      exit 97
    }
  record "cleanup_completed"
  exit "$status"
}
trap cleanup EXIT INT TERM

record "validation_started git_sha=${GITHUB_SHA:-$(git rev-parse HEAD)}"

terraform -chdir="$TF_DIR" init
terraform -chdir="$TF_DIR" plan -out=tfplan \
  -var='enable_eks=true' \
  -var='enable_nat_gateway=true' \
  -var='enable_observability=true' \
  -var='enable_audit_trail=true' \
  | tee "$EVIDENCE_DIR/terraform-plan.log"

record "STOP: apply is intentionally not automated in this harness until budget preflight is connected."
record "Use the reviewed plan as the final human gate before any billable resources are created."
exit 3
