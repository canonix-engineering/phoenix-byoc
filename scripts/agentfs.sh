#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
action=${1:?AgentFS action required}
values_file=${PHOENIX_BYOC_VALUES_FILE:?Values file required}
secrets_file=${PHOENIX_BYOC_SECRETS_FILE:?Secrets file required}
[[ "$values_file" == /* ]] || values_file="$repo_root/$values_file"
[[ "$secrets_file" == /* ]] || secrets_file="$repo_root/$secrets_file"
namespace=${PHOENIX_BYOC_NAMESPACE:?Namespace required}
merged_config() {
  # shellcheck disable=SC2016 # $item is a yq variable.
  yq eval-all -o=json '. as $item ireduce ({}; . * $item)' \
    "$repo_root/release.yaml" "$repo_root/defaults/values.yaml" \
    "$values_file" "$secrets_file"
}
case "$action" in
  enabled) merged_config | yq -r '.services.opensandbox.fuse.enabled' ;;
  managed) merged_config | yq -r '.fuseDevicePlugin.install' ;;
  namespace) merged_config | yq -r '.fuseDevicePlugin.namespace' ;;
  *)
    context_args=(--namespace "$namespace")
    if [[ -n "${PHOENIX_AGENTFS_CONTEXT:-}" ]]; then
      context_args+=(--context "$PHOENIX_AGENTFS_CONTEXT")
    fi
    merged_config | python3 "$repo_root/scripts/agentfs.py" "$action" \
      "${context_args[@]}"
    ;;
esac
