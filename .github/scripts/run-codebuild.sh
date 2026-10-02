#!/usr/bin/env bash
# Start a reviewed CodeBuild project, wait for it to finish, and copy its FINRISK_EVIDENCE lines
# into $EVIDENCE_FILE. Fails unless the build SUCCEEDED.
#
# Usage: run-codebuild.sh <project> [NAME=VALUE]
# At most one environment-variable override, sent as PLAINTEXT. The release role's IAM decides
# which projects and which single variable are allowed (docs/aws-release-policy.json).
set -euo pipefail

project="$1"
override="${2:-}"
evidence_file="${EVIDENCE_FILE:-evidence/deployment.txt}"
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

deadline=$((SECONDS + 45 * 60))
while :; do
  status="$(aws codebuild batch-get-builds --ids "$build_id" --query 'builds[0].buildStatus' --output text)"
  [ "$status" != "IN_PROGRESS" ] && break
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "::error::Timed out waiting for $build_id"
    exit 1
  fi
  sleep 15
done

group="$(aws codebuild batch-get-builds --ids "$build_id" --query 'builds[0].logs.groupName' --output text)"
stream="$(aws codebuild batch-get-builds --ids "$build_id" --query 'builds[0].logs.streamName' --output text)"
if [ "$group" != "None" ] && [ "$stream" != "None" ]; then
  aws logs get-log-events --log-group-name "$group" --log-stream-name "$stream" --start-from-head --output json \
    | jq -r '.events[].message' | grep '^FINRISK_EVIDENCE ' | sed "s/^FINRISK_EVIDENCE /${project}: /" >> "$evidence_file" || true
fi

echo "${project}_status=$status" >> "$evidence_file"
if [ "$status" != "SUCCEEDED" ]; then
  echo "::error::$project build $build_id finished with status $status"
  exit 1
fi
