{{- define "ecr-pull-secret-refresh.name" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ecr-pull-secret-refresh.snapshotCredentialsSecretName" -}}
{{- if .Values.snapshotRegistry.credentials.existingSecret -}}
{{- .Values.snapshotRegistry.credentials.existingSecret -}}
{{- else -}}
{{- printf "%s-snapshot-registry-credentials" (include "ecr-pull-secret-refresh.name" .) -}}
{{- end -}}
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
{{- with .Values.nodeSelector }}
nodeSelector:
{{ toYaml . | indent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
{{ toYaml . | indent 2 }}
{{- end }}
{{- with .Values.affinity }}
affinity:
{{ toYaml . | indent 2 }}
{{- end }}
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
        if [ "$SNAPSHOT_REGISTRY_ENABLED" = "true" ]; then
          snapshot_auth="$(printf '%s:%s' "$SNAPSHOT_REGISTRY_USERNAME" "$SNAPSHOT_REGISTRY_PASSWORD" | base64 | tr -d '\n')"
          printf '%s\n' \
            '---' \
            'apiVersion: v1' \
            'kind: Secret' \
            'metadata:' \
            "  name: $SNAPSHOT_REGISTRY_SECRET_NAME" \
            "  namespace: $TARGET_NAMESPACE" \
            'type: kubernetes.io/dockerconfigjson' \
            'stringData:' \
            '  .dockerconfigjson: |' \
            "    {\"auths\":{\"$ECR_REGISTRY\":{\"auth\":\"$token\"},\"$SNAPSHOT_REGISTRY_HOST\":{\"auth\":\"$snapshot_auth\"}}}" \
            >> /work/secret.yaml
        fi
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
      - name: SNAPSHOT_REGISTRY_ENABLED
        value: {{ .Values.snapshotRegistry.enabled | quote }}
{{- if .Values.snapshotRegistry.enabled }}
      - name: SNAPSHOT_REGISTRY_HOST
        value: {{ required "snapshotRegistry.registryHost is required when snapshotRegistry.enabled=true" .Values.snapshotRegistry.registryHost | quote }}
      - name: SNAPSHOT_REGISTRY_SECRET_NAME
        value: {{ required "snapshotRegistry.secretName is required when snapshotRegistry.enabled=true" .Values.snapshotRegistry.secretName | quote }}
      - name: SNAPSHOT_REGISTRY_USERNAME
        valueFrom:
          secretKeyRef:
            name: {{ include "ecr-pull-secret-refresh.snapshotCredentialsSecretName" . }}
            key: username
      - name: SNAPSHOT_REGISTRY_PASSWORD
        valueFrom:
          secretKeyRef:
            name: {{ include "ecr-pull-secret-refresh.snapshotCredentialsSecretName" . }}
            key: password
{{- end }}
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
