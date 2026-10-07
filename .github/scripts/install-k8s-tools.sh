#!/usr/bin/env bash
# Pinned helm and kubeconform (linux-amd64), the two platform charts, the OCI manifest Argo CD syncs
# kube-prometheus-stack from, and the CRD JSON schemas for the infra/tests/check_*.py scripts, each
# download verified against a sha256 fixed in this file rather than one fetched from the same origin.
#
# Usage: install-k8s-tools.sh <dir>
#   <dir>/bin/helm, <dir>/bin/kubeconform, <dir>/charts/{argo-cd,kube-prometheus-stack}.tgz,
#   <dir>/charts/kube-prometheus-stack.oci-manifest.json,
#   <dir>/schemas/{servicemonitor-monitoring,application-argoproj,appproject-argoproj}-*.json
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
# The charts the bootstrap build installs: argo-cd from its GitHub release (the bootstrap downloads
# the same file; infra/terraform/deploy_path.tf pins the same sha256), and kube-prometheus-stack,
# whose tgz is the chart layer of the OCI manifest digest Argo CD syncs (infra/k8s/monitoring-app.yaml).
ARGOCD_CHART_VERSION="10.9.6"
ARGOCD_CHART_SHA256="6eda90bdd18de538511c9b9aca1ca7ba7a1ca5b919f598714d0e91cd7155d119"
KUBE_PROMETHEUS_STACK_VERSION="91.9.0"
KUBE_PROMETHEUS_STACK_SHA256="75ee7cf15ee9492faf1babc0682237caf6ba706700370cd34b1ea261cee737fe"
# The OCI manifest digest Argo CD syncs (the Application's targetRevision); check_monitoring_stack.py
# checks that its chart layer is the tgz above. Fetched, not committed: its annotations carry the
# chart maintainers' contact details.
KUBE_PROMETHEUS_STACK_MANIFEST_SHA256="04047e500c803dc8d2bc284ecb43e9229bb32b5c36bd13fc89592c8a2f3cdc72"

mkdir -p "$1"
dir="$(cd "$1" && pwd)"
mkdir -p "$dir/bin" "$dir/schemas" "$dir/charts" "$dir/download"
cd "$dir/download"

fetch() {  # <file> <url> <sha256> [-H <header>...]
  curl -fsSL "${@:4}" -o "$1" "$2"
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
fetch argo-cd.tgz "https://github.com/argoproj/argo-helm/releases/download/argo-cd-${ARGOCD_CHART_VERSION}/argo-cd-${ARGOCD_CHART_VERSION}.tgz" "$ARGOCD_CHART_SHA256"
fetch kube-prometheus-stack.tgz "https://github.com/prometheus-community/helm-charts/releases/download/kube-prometheus-stack-${KUBE_PROMETHEUS_STACK_VERSION}/kube-prometheus-stack-${KUBE_PROMETHEUS_STACK_VERSION}.tgz" "$KUBE_PROMETHEUS_STACK_SHA256"
# GHCR serves even public manifests only with a token; an anonymous pull token is enough.
ghcr="prometheus-community/charts/kube-prometheus-stack"
token="$(curl -fsSL "https://ghcr.io/token?scope=repository:$ghcr:pull" | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])')"
fetch kube-prometheus-stack.oci-manifest.json "https://ghcr.io/v2/$ghcr/manifests/sha256:${KUBE_PROMETHEUS_STACK_MANIFEST_SHA256}" "$KUBE_PROMETHEUS_STACK_MANIFEST_SHA256" -H "Authorization: Bearer $token" -H "Accept: application/vnd.oci.image.manifest.v1+json"
install -m 0644 argo-cd.tgz kube-prometheus-stack.tgz kube-prometheus-stack.oci-manifest.json "$dir/charts/"

# The Argo CD CRDs are Helm templates in this chart, so render them before converting.
for crd in application appproject; do
  "$dir/bin/helm" template argocd "$dir/charts/argo-cd.tgz" --show-only "templates/crds/crd-$crd.yaml" > "crd-$crd.yaml"
done
# Strict like kubeconform -strict: no property the CRD does not define, at any level.
(cd "$dir/schemas" && FILENAME_FORMAT='{kind}-{group}-{version}' DENY_ROOT_ADDITIONAL_PROPERTIES=1 \
  python3 "$dir/download/openapi2jsonschema.py" "$dir/download/servicemonitors.yaml" \
  "$dir/download/crd-application.yaml" "$dir/download/crd-appproject.yaml")
for schema in servicemonitor-monitoring-v1 application-argoproj-v1alpha1 appproject-argoproj-v1alpha1; do
  test -s "$dir/schemas/$schema.json"
done
