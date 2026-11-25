#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
context=$1 namespace=$2 pull_secrets=$3
(
  cd "$repo_root"
  helmfile --kube-context "$context" sync
)

# OpenSandbox creates runtime Pods after Helm installation. Linking the same
# pull secrets to the namespace default ServiceAccount lets those dynamic Pods
# pull from the configured registry. This runs after Helmfile so the optional
# ECR refresh release can create and populate its managed pull Secret first.
if [[ -n "$pull_secrets" ]]; then
  service_account_manifest=$(mktemp)
  trap 'rm -f "$service_account_manifest"' EXIT
  {
    echo "apiVersion: v1"
    echo "kind: ServiceAccount"
    echo "metadata:"
    echo "  name: default"
    echo "  namespace: $namespace"
    echo "imagePullSecrets:"
    while IFS= read -r secret_name; do
      echo "  - name: $secret_name"
    done <<<"$pull_secrets"
  } >"$service_account_manifest"
  kubectl --context "$context" apply -f "$service_account_manifest"
fi
