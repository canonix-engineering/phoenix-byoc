#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"
values_file=${PHOENIX_BYOC_VALUES_FILE:-"$repo_root/values.yaml"}
if [[ "$values_file" != /* ]]; then
  values_file="$repo_root/$values_file"
fi
namespace=${PHOENIX_BYOC_NAMESPACE:-}
if [[ -z "$namespace" ]]; then
  namespace=$(awk '$1 == "namespace:" {print $2; exit}' "$values_file")
fi
if [[ -z "$namespace" ]]; then
  echo "ERROR: namespace is required." >&2
  exit 1
fi
ecr_refresh_enabled=$(awk '
  /^registry:/ { in_registry=1; next }
  in_registry && /^[^ ]/ { exit }
  in_registry && /^  ecrRefresh:/ { in_refresh=1; next }
  in_refresh && /^    enabled:/ { print $2; exit }
' "$values_file")
ecr_pull_secret=$(awk '
  /^registry:/ { in_registry=1; next }
  in_registry && /^[^ ]/ { exit }
  in_registry && /^  ecrRefresh:/ { in_refresh=1; next }
  in_refresh && /^    pullSecretName:/ {
    gsub(/"/, "", $2)
    print $2
    exit
  }
' "$values_file")

(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" helmfile status
)

kubectl -n "$namespace" wait \
  --for=condition=Available deployment --all --timeout=600s
kubectl -n "$namespace" get pods,services,persistentvolumeclaims

if [[ "$ecr_refresh_enabled" == "true" ]]; then
  kubectl -n "$namespace" get cronjob/ecr-pull-secret-refresh
  pull_secret_type=$(kubectl -n "$namespace" get secret "$ecr_pull_secret" \
    -o jsonpath='{.type}')
  if [[ "$pull_secret_type" != "kubernetes.io/dockerconfigjson" ]]; then
    echo "ERROR: managed ECR pull Secret has unexpected type: $pull_secret_type" >&2
    exit 1
  fi
  echo "ECR pull Secret refresh is enabled for '$ecr_pull_secret'."
fi

echo "Phoenix verification passed in namespace $namespace."
