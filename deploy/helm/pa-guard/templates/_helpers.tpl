{{/*
Common template helpers for the pa-guard chart.
*/}}

{{- define "pa-guard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "pa-guard.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "pa-guard.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "pa-guard.labels" -}}
helm.sh/chart: {{ include "pa-guard.chart" . }}
{{ include "pa-guard.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "pa-guard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "pa-guard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
