#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
devops_charts="${PHOENIX_BYOC_LOCAL_CHARTS:-$repo_root/../phoenix-devops/charts}"
cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"

if [[ ! -d "$devops_charts/phoenix-web" ]]; then
  echo "ERROR: local charts not found; set PHOENIX_BYOC_LOCAL_CHARTS" >&2
  exit 1
fi

for scenario in bundled external private-registry; do
  render_dir="$repo_root/.rendered/test-$scenario"
  values_file="tests/fixtures/values.yaml"
  secrets_file="tests/fixtures/values.secrets.yaml"
  if [[ "$scenario" == "external" ]]; then
    values_file="tests/fixtures/values-external.yaml"
    secrets_file="tests/fixtures/values.secrets-external.yaml"
  elif [[ "$scenario" == "private-registry" ]]; then
    values_file="tests/fixtures/values-private-registry.yaml"
  fi

  mkdir -p "$cache_dir" "$render_dir"
  (
    cd "$repo_root"
    HELMFILE_CACHE_HOME="$cache_dir" \
      PHOENIX_BYOC_LOCAL_CHARTS="$devops_charts" \
      PHOENIX_BYOC_VALUES_FILE="$values_file" \
      PHOENIX_BYOC_SECRETS_FILE="$secrets_file" \
      helmfile template --skip-deps --quiet \
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

  if [[ "$scenario" == "private-registry" ]]; then
    if grep -q 'ghcr.io/canonix-engineering/phoenix-' "$render_dir/all.yaml"; then
      echo "ERROR: private registry render contains a default Phoenix image" >&2
      exit 1
    fi
    for image in \
      cortex-postgresql \
      phoenix-agent \
      phoenix-gateway \
      phoenix-lab \
      phoenix-opensandbox \
      phoenix-opensandbox-controller \
      phoenix-web \
      phoenix-web-frontend \
      phoenix-workflow-engine; do
      grep -q "registry.test.invalid/phoenix/$image:" "$render_dir/all.yaml" || {
        echo "ERROR: mirrored image is missing from render: $image" >&2
        exit 1
      }
    done
  fi
done

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "$repo_root"/scripts/*.sh
fi

if command -v yamllint >/dev/null 2>&1; then
  yamllint \
    --config-file "$repo_root/.yamllint.yaml" \
    "$repo_root/defaults" \
    "$repo_root/release.yaml" \
    "$repo_root/tests" \
    "$repo_root/Taskfile.yaml" \
    "$repo_root/values.yaml.example" \
    "$repo_root/values.secrets.yaml.example"
fi

image_count=$("$repo_root/scripts/images.sh" list | wc -l | tr -d ' ')
if [[ "$image_count" != "9" ]]; then
  echo "ERROR: release.yaml must contain exactly 9 Phoenix runtime images" >&2
  exit 1
fi
while IFS= read -r image_ref; do
  grep -Fq "$image_ref" "$repo_root/.rendered/test-bundled/all.yaml" || {
    echo "ERROR: release image does not match the rendered deployment: $image_ref" >&2
    exit 1
  }
done < <("$repo_root/scripts/images.sh" list)

echo "Static BYOC tests passed."
