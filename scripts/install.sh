#!/usr/bin/env bash
set -euo pipefail

environment=default
confirmed=false
while (($# > 0)); do
  case "$1" in
    --environment)
      environment=${2:-}
      shift 2
      ;;
    --yes)
      confirmed=true
      shift
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
context=$(kubectl config current-context)

"$repo_root/scripts/preflight.sh" --environment "$environment"
"$repo_root/scripts/render.sh" --environment "$environment"

if [[ "$confirmed" != true ]]; then
  echo "Ready to install or upgrade Phoenix."
  echo "Context:     $context"
  echo "Environment: $environment"
  echo "Rendered:    $repo_root/.rendered/$environment/all.yaml"
  read -r -p "Apply these releases? [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || exit 1
fi

cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"
(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" helmfile --environment "$environment" apply --suppress-diff
)

"$repo_root/scripts/verify.sh" --environment "$environment"
