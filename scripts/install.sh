#!/usr/bin/env bash
set -euo pipefail

requested_namespace=""
requested_values=""
requested_secrets=""
while (($# > 0)); do
  case "$1" in
    --namespace)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "ERROR: --namespace requires a value." >&2
        exit 2
      fi
      requested_namespace=$2
      shift 2
      ;;
    --values)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "ERROR: --values requires a path." >&2
        exit 2
      fi
      requested_values=$2
      shift 2
      ;;
    --secrets)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "ERROR: --secrets requires a path." >&2
        exit 2
      fi
      requested_secrets=$2
      shift 2
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$requested_namespace" || -z "$requested_values" || -z "$requested_secrets" ]]; then
  echo "Usage: ./scripts/install.sh --namespace <name> --values <path> --secrets <path>" >&2
  exit 2
fi
if [[ ! "$requested_namespace" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
  echo "ERROR: namespace must be a valid lowercase Kubernetes DNS label." >&2
  exit 2
fi

export PHOENIX_BYOC_NAMESPACE="$requested_namespace"
export PHOENIX_BYOC_VALUES_FILE="$requested_values"
export PHOENIX_BYOC_SECRETS_FILE="$requested_secrets"

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
context=$(kubectl config current-context)

"$repo_root/scripts/preflight.sh"
"$repo_root/scripts/render.sh"

values_file=$requested_values
if [[ "$values_file" != /* ]]; then
  values_file="$repo_root/$values_file"
fi
secrets_file=$requested_secrets
if [[ "$secrets_file" != /* ]]; then
  secrets_file="$repo_root/$secrets_file"
fi
namespace=$requested_namespace
release_version=$(awk '$1 == "version:" {gsub(/"/, "", $2); print $2; exit}' \
  "$repo_root/release.yaml")
pull_secrets=$(awk '
  /^imagePullSecrets:/ { in_secrets=1; next }
  in_secrets && /^[^ ]/ { exit }
  in_secrets && $1 == "-" && $2 == "name:" {
    gsub(/"/, "", $3)
    print $3
  }
' "$values_file")

echo
echo "Installing or upgrading Phoenix $release_version."
echo "Context:     $context"
echo "Namespace:   $namespace"
echo "Values:      $values_file"
echo "Secrets:     $secrets_file"
echo "Rendered:    $repo_root/.rendered/all.yaml"

cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"

(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" helmfile sync
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
  kubectl apply -f "$service_account_manifest"
fi

"$repo_root/scripts/verify.sh" \
  --namespace "$namespace" \
  --values "$values_file" \
  --secrets "$secrets_file"
