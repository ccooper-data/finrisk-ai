{{/*
Names and the selector are those of infra/k8s/inference.yaml, not derived from the release: the
deploy build and its smoke test address the Deployment and Service by name, and a Deployment's
selector cannot change on upgrade. check_inference_chart.py renders under other release names to
hold this.
*/}}
{{- define "finrisk-inference.name" -}}
{{ .Chart.Name }}
{{- end }}

{{- define "finrisk-inference.selectorLabels" -}}
app: {{ include "finrisk-inference.name" . }}
{{- end }}

{{/* Object metadata only; never a selector or the Pod template. */}}
{{- define "finrisk-inference.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
app.kubernetes.io/name: {{ include "finrisk-inference.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
