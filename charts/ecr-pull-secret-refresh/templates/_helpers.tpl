{{- define "ecr-pull-secret-refresh.name" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ecr-pull-secret-refresh.credentialsSecretName" -}}
{{- if .Values.credentials.existingSecret -}}
{{- .Values.credentials.existingSecret -}}
{{- else -}}
{{- printf "%s-aws-credentials" (include "ecr-pull-secret-refresh.name" .) -}}
{{- end -}}
{{- end -}}

{{- define "ecr-pull-secret-refresh.labels" -}}
app.kubernetes.io/name: ecr-pull-secret-refresh
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "ecr-pull-secret-refresh.podSpec" -}}
serviceAccountName: {{ include "ecr-pull-secret-refresh.name" . }}
automountServiceAccountToken: true
restartPolicy: Never
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault
volumes:
  - name: work
    emptyDir:
      medium: Memory
  - name: tmp
    emptyDir:
      medium: Memory
initContainers:
  - name: generate-pull-secret
    image: {{ .Values.images.awsCli | quote }}
    imagePullPolicy: IfNotPresent
    command:
      - /bin/sh
      - -ec
    args:
      - |
        mkdir -p "$HOME"
        token="$(aws ecr get-authorization-token \
          --region "$AWS_REGION" \
          --query 'authorizationData[0].authorizationToken' \
          --output text)"
        test -n "$token"
        umask 077
        printf '%s\n' \
          'apiVersion: v1' \
          'kind: Secret' \
          'metadata:' \
          "  name: $PULL_SECRET_NAME" \
          "  namespace: $TARGET_NAMESPACE" \
          'type: kubernetes.io/dockerconfigjson' \
          'stringData:' \
          '  .dockerconfigjson: |' \
          "    {\"auths\":{\"$ECR_REGISTRY\":{\"auth\":\"$token\"}}}" \
          > /work/secret.yaml
    env:
      - name: HOME
        value: /work/home
      - name: AWS_REGION
        value: {{ required "region is required" .Values.region | quote }}
      - name: ECR_REGISTRY
        value: {{ required "registry is required" .Values.registry | quote }}
      - name: PULL_SECRET_NAME
        value: {{ required "pullSecretName is required" .Values.pullSecretName | quote }}
      - name: TARGET_NAMESPACE
        value: {{ .Release.Namespace | quote }}
    envFrom:
      - secretRef:
          name: {{ include "ecr-pull-secret-refresh.credentialsSecretName" . }}
    resources:
{{ toYaml .Values.resources.init | indent 6 }}
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop:
          - ALL
      readOnlyRootFilesystem: true
    volumeMounts:
      - name: work
        mountPath: /work
      - name: tmp
        mountPath: /tmp
containers:
  - name: apply-pull-secret
    image: {{ .Values.images.kubectl | quote }}
    imagePullPolicy: IfNotPresent
    env:
      - name: HOME
        value: /tmp
    args:
      - apply
      - --server-side=false
      - -f
      - /work/secret.yaml
    resources:
{{ toYaml .Values.resources.apply | indent 6 }}
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop:
          - ALL
      readOnlyRootFilesystem: true
    volumeMounts:
      - name: work
        mountPath: /work
        readOnly: true
      - name: tmp
        mountPath: /tmp
{{- end -}}
