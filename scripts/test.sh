#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
devops_charts="${PHOENIX_BYOC_LOCAL_CHARTS:-$repo_root/../phoenix-devops/charts}"
cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"

if [[ ! -d "$devops_charts/phoenix-web" ]]; then
  echo "ERROR: local charts not found; set PHOENIX_BYOC_LOCAL_CHARTS" >&2
  exit 1
fi

for environment in kind external; do
  render_dir="$repo_root/.rendered/test-$environment"
  values_file="tests/fixtures/values.yaml"
  secrets_file="tests/fixtures/values.secrets.yaml"
  if [[ "$environment" == "external" ]]; then
    values_file="tests/fixtures/values-external.yaml"
    secrets_file="tests/fixtures/values.secrets-external.yaml"
  fi

  mkdir -p "$cache_dir" "$render_dir"
  (
    cd "$repo_root"
    HELMFILE_CACHE_HOME="$cache_dir" \
      PHOENIX_BYOC_LOCAL_CHARTS="$devops_charts" \
      PHOENIX_BYOC_VALUES_FILE="$values_file" \
      PHOENIX_BYOC_SECRETS_FILE="$secrets_file" \
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
done

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "$repo_root"/scripts/*.sh
fi

if command -v yamllint >/dev/null 2>&1; then
  yamllint \
    --config-file "$repo_root/.yamllint.yaml" \
    "$repo_root/config" \
    "$repo_root/profiles" \
    "$repo_root/releases" \
    "$repo_root/tests" \
    "$repo_root/Taskfile.yaml"
fi

echo "Static BYOC tests passed."
