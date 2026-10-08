#!/usr/bin/env bash
set -euo pipefail

# Called after rendering, before any cluster mutation by install.sh.
namespace=${1:?namespace is required}
rendered_file=${2:?rendered manifest is required}
if [[ "$(yq eval --no-doc 'select(.kind == "StatefulSet" and .metadata.name == "valkey") | .metadata.name' "$rendered_file")" != "valkey" ]]; then
  exit 0
fi

legacy_cache=$(kubectl -n "$namespace" get statefulset redis --ignore-not-found -o name)
if [[ -n "$legacy_cache" ]]; then
  echo "ERROR: existing Redis requires a coordinated data migration before this upgrade." >&2
  echo "       Follow docs/redis.md; preserve the old PVC and validate data on Valkey." >&2
  exit 1
fi

# A retained Redis PVC with no running server is not evidence of an empty cache.
legacy_pvc=$(kubectl -n "$namespace" get pvc data-redis-0 --ignore-not-found -o name)
if [[ -n "$legacy_pvc" ]]; then
  valkey_cache=$(kubectl -n "$namespace" get statefulset valkey --ignore-not-found -o name)
  if [[ -z "$valkey_cache" ]]; then
    echo "ERROR: retained Redis data exists without a migrated Valkey deployment." >&2
    echo "       Follow docs/redis.md before installing; do not delete the old PVC." >&2
    exit 1
  fi
fi
