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
render_dir="$repo_root/.rendered/$environment"
cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"

mkdir -p "$render_dir" "$cache_dir"
chmod 700 "$repo_root/.rendered"

(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" \
    helmfile --environment "$environment" template --skip-deps --quiet \
    >"$render_dir/all.yaml"
)
chmod 600 "$render_dir/all.yaml"

if command -v kubeconform >/dev/null 2>&1; then
  kubeconform \
    -kubernetes-version 1.32.0 \
    -strict \
    -summary \
    -ignore-missing-schemas \
    "$render_dir/all.yaml"
fi

echo "Rendered manifests: $render_dir/all.yaml"
