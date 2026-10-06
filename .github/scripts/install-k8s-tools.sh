#!/usr/bin/env bash
# Pinned helm and kubeconform (linux-amd64) and the ServiceMonitor JSON schema for
# infra/tests/check_inference_chart.py, each download verified against a sha256 fixed in this file
# rather than one fetched from the same origin.
#
# Usage: install-k8s-tools.sh <dir>
#   <dir>/bin/helm, <dir>/bin/kubeconform, <dir>/schemas/servicemonitor-monitoring-v1.json
set -euo pipefail

# https://get.helm.sh/helm-v4.3.0-linux-amd64.tar.gz.sha256sum (and the release notes)
HELM_VERSION="v4.3.0"
HELM_SHA256="86584a54def73570558f66f5111cc53dfed56689637ae32c1201205d494f54fb"
# CHECKSUMS from the kubeconform release
KUBECONFORM_VERSION="v0.8.0"
KUBECONFORM_SHA256="9bc2bffbf71f261128533edaf912153948b7ff238f9a531ae6d34466ec287883"
# The ServiceMonitor CRD of this prometheus-operator release, converted to JSON schema by
# kubeconform's own converter at the kubeconform version above.
PROMETHEUS_OPERATOR_VERSION="v0.94.1"
SERVICEMONITOR_CRD_SHA256="31bdff398b54ac2bc993a33f5dcb0472792a77104a6a609d264c8f1f17829769"
OPENAPI2JSONSCHEMA_SHA256="d145babfbb765004030764e1b4e518bfb7a4bd7f111691a08fa57983b81881f3"

mkdir -p "$1"
dir="$(cd "$1" && pwd)"
mkdir -p "$dir/bin" "$dir/schemas" "$dir/download"
cd "$dir/download"

fetch() {
  curl -fsSLo "$1" "$2"
  echo "$3  $1" | sha256sum --check --strict
}

fetch helm.tar.gz "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" "$HELM_SHA256"
tar -xzf helm.tar.gz linux-amd64/helm
install -m 0755 linux-amd64/helm "$dir/bin/helm"

fetch kubeconform.tar.gz "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-linux-amd64.tar.gz" "$KUBECONFORM_SHA256"
tar -xzf kubeconform.tar.gz kubeconform
install -m 0755 kubeconform "$dir/bin/kubeconform"

fetch servicemonitors.yaml "https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/${PROMETHEUS_OPERATOR_VERSION}/example/prometheus-operator-crd/monitoring.coreos.com_servicemonitors.yaml" "$SERVICEMONITOR_CRD_SHA256"
fetch openapi2jsonschema.py "https://raw.githubusercontent.com/yannh/kubeconform/${KUBECONFORM_VERSION}/scripts/openapi2jsonschema.py" "$OPENAPI2JSONSCHEMA_SHA256"
# Strict like kubeconform -strict: no property the CRD does not define, at any level.
(cd "$dir/schemas" && FILENAME_FORMAT='{kind}-{group}-{version}' DENY_ROOT_ADDITIONAL_PROPERTIES=1 \
  python3 "$dir/download/openapi2jsonschema.py" "$dir/download/servicemonitors.yaml")
test -s "$dir/schemas/servicemonitor-monitoring-v1.json"
