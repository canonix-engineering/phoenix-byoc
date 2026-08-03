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

(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" helmfile status
)

kubectl -n "$namespace" wait \
  --for=condition=Available deployment --all --timeout=600s
kubectl -n "$namespace" get pods,services,persistentvolumeclaims

echo "Phoenix verification passed in namespace $namespace."
