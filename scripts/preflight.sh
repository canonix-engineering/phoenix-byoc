#!/usr/bin/env bash
set -euo pipefail

environment=default
while (($# > 0)); do
  case "$1" in
    --environment)
      environment=${2:-}
      shift 2
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

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

context=$(kubectl config current-context 2>/dev/null || true)
if [[ -z "$context" ]]; then
  echo "ERROR: kubectl has no current context" >&2
  exit 1
fi

echo "Kubernetes context: $context"
echo "Helmfile environment: $environment"

kubectl version --output=json >/dev/null

if [[ -n "$(git -C "$repo_root" ls-files -- values.secrets.yaml 2>/dev/null)" ]]; then
  echo "ERROR: values.secrets.yaml is tracked by Git" >&2
  exit 1
fi

echo "Preflight passed."
