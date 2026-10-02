#!/usr/bin/env bash
# Start a reviewed CodeBuild project, wait for it to finish, and copy its FINRISK_EVIDENCE lines
# into $EVIDENCE_FILE. Fails unless the build SUCCEEDED and logged its final evidence line.
#
# Usage: run-codebuild.sh <project> [NAME=VALUE]
#   CODEBUILD_WAIT_MINUTES  how long to wait (at least the project's queued + build timeouts)
#   EVIDENCE_TERMINAL       regex for the line that proves the build reached its end
# At most one environment-variable override, sent as PLAINTEXT. The release role's IAM decides
# which projects and which single variable are allowed (docs/aws-release-policy.json).
set -euo pipefail

project="$1"
override="${2:-}"
evidence_file="${EVIDENCE_FILE:-evidence/deployment.txt}"
wait_minutes="${CODEBUILD_WAIT_MINUTES:-45}"
terminal="${EVIDENCE_TERMINAL:-result=|bootstrap=}"
mkdir -p "$(dirname "$evidence_file")"

start_args=(--project-name "$project")
if [ -n "$override" ]; then
  name="${override%%=*}"
  value="${override#*=}"
  start_args+=(--environment-variables-override "$(jq -nc --arg n "$name" --arg v "$value" '[{name: $n, value: $v, type: "PLAINTEXT"}]')")
fi

build_id="$(aws codebuild start-build "${start_args[@]}" --query 'build.id' --output text)"
echo "Started $project build $build_id"
echo "${project}_build_id=$build_id" >> "$evidence_file"

# A timeout or a cancelled workflow must not leave the build applying or rolling back unattended.
# The workflow execs this script so the runner's SIGINT reaches it; sleeps run in the background
# so the trap fires at once instead of after the sleep (the runner kills the step 10 s later).
finished=false
stop_if_running() {
  if [ "$finished" != true ]; then
    echo "::warning::Stopping $build_id"
    aws codebuild stop-build --id "$build_id" >/dev/null || true
  fi
}
trap stop_if_running EXIT
trap 'exit 130' INT TERM
nap() { sleep "$1" >/dev/null 2>&1 & wait $!; }

# A failed status read is retried until the deadline rather than stopping the build: a stop
# mid-rollout would also stop the buildspec's own rollback.
deadline=$((SECONDS + wait_minutes * 60))
while :; do
  if build="$(aws codebuild batch-get-builds --ids "$build_id" --output text \
      --query 'builds[0].[buildStatus,logs.groupName,logs.streamName]')"; then
    IFS=$'\t' read -r status group stream <<<"$build"
    [ "$status" != "IN_PROGRESS" ] && break
  else
    echo "::warning::Could not read the status of $build_id; retrying"
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "::error::Timed out after $wait_minutes minutes waiting for $build_id"
    exit 1
  fi
  nap 15
done
finished=true
echo "${project}_status=$status" >> "$evidence_file"

# get-log-events is not auto-paginated and the last lines can lag the build status, so read every
# page and retry briefly until the build's final evidence line is present. A read error (or a
# stream that was never created) is retried too, and never skips the status check below.
evidence=""
for attempt in 1 2 3 4 5 6; do
  evidence=""
  if [ "${group:-None}" != "None" ] && [ "${stream:-None}" != "None" ]; then
    token=""
    while :; do
      page_args=(--log-group-name "$group" --log-stream-name "$stream" --start-from-head --output json)
      [ -n "$token" ] && page_args+=(--next-token "$token")
      page="$(aws logs get-log-events "${page_args[@]}")" || { echo "::warning::Could not read $group/$stream (attempt $attempt)"; break; }
      evidence+="$(jq -r '.events[].message' <<<"$page" | grep '^FINRISK_EVIDENCE ' || true)"$'\n'
      next="$(jq -r '.nextForwardToken' <<<"$page")"
      [ "$next" = "$token" ] && break
      token="$next"
    done
  fi
  grep -Eq "$terminal" <<<"$evidence" && break
  nap 10
done
grep '^FINRISK_EVIDENCE ' <<<"$evidence" | sed "s/^FINRISK_EVIDENCE /${project}: /" >> "$evidence_file" || true

if [ "$status" != "SUCCEEDED" ]; then
  echo "::error::$project build $build_id finished with status $status"
  exit 1
fi
if ! grep -Eq "$terminal" <<<"$evidence"; then
  echo "::error::$project build $build_id succeeded but its final evidence line was not found in the logs"
  exit 1
fi
