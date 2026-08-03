#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
values_file=${PHOENIX_BYOC_VALUES_FILE:-values.yaml}
secrets_file=${PHOENIX_BYOC_SECRETS_FILE:-values.secrets.yaml}
if [[ "$values_file" != /* ]]; then
  values_file="$repo_root/$values_file"
fi
if [[ "$secrets_file" != /* ]]; then
  secrets_file="$repo_root/$secrets_file"
fi

for command in helm helmfile kubectl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "ERROR: required command is not installed: $command" >&2
    exit 1
  fi
done

if [[ ! -f "$values_file" ]]; then
  echo "ERROR: values file does not exist: $values_file" >&2
  exit 1
fi
if [[ ! -f "$secrets_file" ]]; then
  echo "ERROR: secret values file does not exist: $secrets_file" >&2
  exit 1
fi
chmod 600 "$secrets_file"

if grep -q 'CHANGE_ME' "$values_file"; then
  echo "ERROR: values file still contains CHANGE_ME placeholders: $values_file" >&2
  exit 1
fi
if grep -q 'CHANGE_ME' "$secrets_file"; then
  echo "ERROR: secret values file still contains CHANGE_ME placeholders." >&2
  exit 1
fi

release_channel=$(awk '$1 == "channel:" {gsub(/"/, "", $2); print $2; exit}' \
  "$repo_root/release.yaml")
release_version=$(awk '$1 == "version:" {gsub(/"/, "", $2); print $2; exit}' \
  "$repo_root/release.yaml")
if [[ -z "$release_channel" || -z "$release_version" ]]; then
  echo "ERROR: release.yaml does not contain release.version and release.channel" >&2
  exit 1
fi

if grep -q 'CHANGE_ME' "$repo_root/release.yaml"; then
  echo "ERROR: release.yaml contains an unresolved version placeholder." >&2
  exit 1
fi
context=$(kubectl config current-context 2>/dev/null || true)
if [[ -z "$context" ]]; then
  echo "ERROR: kubectl has no current context" >&2
  exit 1
fi

kubectl version --output=json >/dev/null

if [[ -n "$(git -C "$repo_root" ls-files -- values.secrets.yaml 2>/dev/null)" ]]; then
  echo "ERROR: values.secrets.yaml is tracked by Git" >&2
  exit 1
fi

namespace=${PHOENIX_BYOC_NAMESPACE:-}
if [[ -z "$namespace" ]]; then
  namespace=$(awk '$1 == "namespace:" {print $2; exit}' "$values_file")
fi
if [[ -z "$namespace" ]]; then
  echo "ERROR: namespace is required; run install.sh --namespace <name>." >&2
  exit 1
fi
bundled_postgresql=$(awk '
  /^postgresql:/ { in_component=1; next }
  in_component && /^[^ ]/ { exit }
  in_component && /^  bundled:/ { in_bundled=1; next }
  in_bundled && /^    enabled:/ { print $2; exit }
' "$values_file")
bundled_redis=$(awk '
  /^redis:/ { in_component=1; next }
  in_component && /^[^ ]/ { exit }
  in_component && /^  bundled:/ { in_bundled=1; next }
  in_bundled && /^    enabled:/ { print $2; exit }
' "$values_file")
bundled_cortex=$(awk '
  /^cortex:/ { in_component=1; next }
  in_component && /^[^ ]/ { exit }
  in_component && /^  bundled:/ { in_bundled=1; next }
  in_bundled && /^    enabled:/ { print $2; exit }
' "$values_file")
bundled_ingress=$(awk '
  /^ingressNginx:/ { in_component=1; next }
  in_component && /^[^ ]/ { exit }
  in_component && /^  enabled:/ { print $2; exit }
' "$values_file")
pull_secrets=$(awk '
  /^imagePullSecrets:/ { in_secrets=1; next }
  in_secrets && /^[^ ]/ { exit }
  in_secrets && $1 == "-" && $2 == "name:" {
    gsub(/"/, "", $3)
    print $3
  }
' "$values_file")
image_registry=$(awk '$1 == "imageRegistry:" {gsub(/"/, "", $2); print $2; exit}' \
  "$values_file")
ecr_refresh_enabled=$(awk '
  /^registry:/ { in_registry=1; next }
  in_registry && /^[^ ]/ { exit }
  in_registry && /^  ecrRefresh:/ { in_refresh=1; next }
  in_refresh && /^    enabled:/ { print $2; exit }
' "$values_file")
ecr_refresh_pull_secret=$(awk '
  /^registry:/ { in_registry=1; next }
  in_registry && /^[^ ]/ { exit }
  in_registry && /^  ecrRefresh:/ { in_refresh=1; next }
  in_refresh && /^    pullSecretName:/ {
    gsub(/"/, "", $2)
    print $2
    exit
  }
' "$values_file")
ecr_credentials_secret=$(awk '
  /^registry:/ { in_registry=1; next }
  in_registry && /^[^ ]/ { exit }
  in_registry && /^  ecrRefresh:/ { in_refresh=1; next }
  in_refresh && /^    credentialsSecretName:/ {
    gsub(/"/, "", $2)
    print $2
    exit
  }
' "$values_file")

managed_pull_secret=""
if [[ "$ecr_refresh_enabled" == "true" ]]; then
  if [[ -n "$image_registry" ]]; then
    echo "ERROR: imageRegistry must be empty when registry.ecrRefresh.enabled=true." >&2
    exit 1
  fi
  if [[ -z "$ecr_refresh_pull_secret" ]]; then
    echo "ERROR: registry.ecrRefresh.pullSecretName is required." >&2
    exit 1
  fi
  if ! grep -Fxq "$ecr_refresh_pull_secret" <<<"$pull_secrets"; then
    echo "ERROR: imagePullSecrets must include '$ecr_refresh_pull_secret' when ECR refresh is enabled." >&2
    exit 1
  fi
  managed_pull_secret=$ecr_refresh_pull_secret

  if [[ -n "$ecr_credentials_secret" ]]; then
    if ! kubectl get namespace "$namespace" >/dev/null 2>&1; then
      echo "ERROR: namespace '$namespace' must exist when using an existing ECR credentials Secret." >&2
      exit 1
    fi
    kubectl -n "$namespace" get secret "$ecr_credentials_secret" >/dev/null || {
      echo "ERROR: ECR credentials Secret '$ecr_credentials_secret' does not exist in namespace '$namespace'." >&2
      exit 1
    }
    for credential_key in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
      credential_value=$(kubectl -n "$namespace" get secret "$ecr_credentials_secret" \
        -o "jsonpath={.data.$credential_key}")
      if [[ -z "$credential_value" ]]; then
        echo "ERROR: ECR credentials Secret '$ecr_credentials_secret' is missing key '$credential_key'." >&2
        exit 1
      fi
    done
  else
    ecr_access_key_id=$(awk '
      /^secrets:/ { in_secrets=1; next }
      in_secrets && /^  registry:/ { in_registry=1; next }
      in_registry && /^    ecr:/ { in_ecr=1; next }
      in_ecr && /^      accessKeyId:/ {
        sub(/^[^:]+:[[:space:]]*/, "")
        gsub(/"/, "")
        print
        exit
      }
    ' "$secrets_file")
    ecr_secret_access_key=$(awk '
      /^secrets:/ { in_secrets=1; next }
      in_secrets && /^  registry:/ { in_registry=1; next }
      in_registry && /^    ecr:/ { in_ecr=1; next }
      in_ecr && /^      secretAccessKey:/ {
        sub(/^[^:]+:[[:space:]]*/, "")
        gsub(/"/, "")
        print
        exit
      }
    ' "$secrets_file")
    if [[ -z "$ecr_access_key_id" || -z "$ecr_secret_access_key" ]]; then
      echo "ERROR: ECR refresh requires accessKeyId and secretAccessKey in values.secrets.yaml or credentialsSecretName." >&2
      exit 1
    fi
  fi
fi

if [[ -n "$pull_secrets" ]]; then
  unmanaged_pull_secrets=$(awk -v managed="$managed_pull_secret" \
    'NF && $0 != managed { print }' <<<"$pull_secrets")
  if [[ -n "$unmanaged_pull_secrets" ]] && \
      ! kubectl get namespace "$namespace" >/dev/null 2>&1; then
    echo "ERROR: namespace '$namespace' must exist before creating registry pull secrets." >&2
    exit 1
  fi
  while IFS= read -r secret_name; do
    if [[ "$secret_name" == "$managed_pull_secret" ]]; then
      continue
    fi
    kubectl -n "$namespace" get secret "$secret_name" >/dev/null || {
      echo "ERROR: image pull secret '$secret_name' does not exist in namespace '$namespace'." >&2
      exit 1
    }
  done <<<"$pull_secrets"
fi

echo "Release:            $release_version ($release_channel)"
echo "Kubernetes context: $context"
echo "Namespace:          $namespace"
echo "Bundled PostgreSQL: ${bundled_postgresql:-false}"
echo "Bundled Redis:      ${bundled_redis:-true}"
echo "Bundled Cortex:     ${bundled_cortex:-true}"
echo "Bundled ingress:    ${bundled_ingress:-false}"
echo "ECR token refresh:  ${ecr_refresh_enabled:-false}"
echo "Preflight passed."
