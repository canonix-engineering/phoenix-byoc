#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: ./scripts/verify.sh --namespace <name> --values <path> --secrets <path>" >&2
}

namespace=""
values_path=""
secrets_path=""
while (($# > 0)); do
  case "$1" in
    --namespace)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "ERROR: --namespace requires a value." >&2
        exit 2
      fi
      namespace=$2
      shift 2
      ;;
    --values)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "ERROR: --values requires a path." >&2
        exit 2
      fi
      values_path=$2
      shift 2
      ;;
    --secrets)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "ERROR: --secrets requires a path." >&2
        exit 2
      fi
      secrets_path=$2
      shift 2
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$namespace" || -z "$values_path" || -z "$secrets_path" ]]; then
  usage
  exit 2
fi

export PHOENIX_BYOC_NAMESPACE="$namespace"
export PHOENIX_BYOC_VALUES_FILE="$values_path"
export PHOENIX_BYOC_SECRETS_FILE="$secrets_path"

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"
values_file=$values_path
secrets_file=$secrets_path
if [[ "$values_file" != /* ]]; then
  values_file="$repo_root/$values_file"
fi
if [[ "$secrets_file" != /* ]]; then
  secrets_file="$repo_root/$secrets_file"
fi

for file in "$values_file" "$secrets_file"; do
  if [[ ! -f "$file" ]]; then
    echo "ERROR: configuration file does not exist: $file" >&2
    exit 1
  fi
done

merged_file=$(mktemp)
trap 'rm -f "$merged_file"' EXIT
chmod 600 "$merged_file"
# shellcheck disable=SC2016 # $item is a yq variable, not a shell variable.
yq eval-all '. as $item ireduce ({}; . * $item)' \
  "$repo_root/release.yaml" \
  "$repo_root/defaults/values.yaml" \
  "$values_file" \
  "$secrets_file" >"$merged_file"

ecr_refresh_enabled=$(yq -r '.registry.ecrRefresh.enabled' "$merged_file")
ecr_pull_secret=$(yq -r '.registry.ecrRefresh.pullSecretName' "$merged_file")
bundled_clickhouse=$(yq -r '.clickhouse.bundled.enabled' "$merged_file")

(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" helmfile status
)

kubectl -n "$namespace" wait \
  --for=condition=Available deployment --all --timeout=600s

while IFS= read -r statefulset; do
  [[ -z "$statefulset" ]] && continue
  kubectl -n "$namespace" rollout status "$statefulset" --timeout=600s
done < <(kubectl -n "$namespace" get statefulsets -o name)

kubectl -n "$namespace" get pods,services,persistentvolumeclaims

if [[ "$bundled_clickhouse" == "true" ]]; then
  kubectl -n "$namespace" get service/clickhouse statefulset/clickhouse
fi

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
