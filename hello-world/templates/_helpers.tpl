{{- define "hello-world.fullname" -}}
{{ .Release.Name }}-hello
{{- end }}
