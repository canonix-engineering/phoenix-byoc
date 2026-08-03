#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
devops_charts="${PHOENIX_BYOC_LOCAL_CHARTS:-$repo_root/../phoenix-devops/charts}"
cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"

if [[ ! -d "$devops_charts/phoenix-web" ]]; then
  echo "ERROR: local charts not found; set PHOENIX_BYOC_LOCAL_CHARTS" >&2
  exit 1
fi

for scenario in bundled external private-registry direct-ecr; do
  render_dir="$repo_root/.rendered/test-$scenario"
  values_file="tests/fixtures/values.yaml"
  secrets_file="tests/fixtures/values.secrets.yaml"
  if [[ "$scenario" == "external" ]]; then
    values_file="tests/fixtures/values-external.yaml"
    secrets_file="tests/fixtures/values.secrets-external.yaml"
  elif [[ "$scenario" == "private-registry" ]]; then
    values_file="tests/fixtures/values-private-registry.yaml"
  elif [[ "$scenario" == "direct-ecr" ]]; then
    values_file="tests/fixtures/values-direct-ecr.yaml"
    secrets_file="tests/fixtures/values.secrets-direct-ecr.yaml"
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
  elif [[ "$scenario" == "direct-ecr" ]]; then
    grep -q 'kind: CronJob' "$render_dir/all.yaml" || {
      echo "ERROR: direct ECR render is missing the token refresh CronJob" >&2
      exit 1
    }
    grep -q 'name: ecr-pull-secret-refresh' "$render_dir/all.yaml" || {
      echo "ERROR: direct ECR render is missing the refresh release resources" >&2
      exit 1
    }
    grep -q 'name: phoenix-ecr-pull' "$render_dir/all.yaml" || {
      echo "ERROR: direct ECR render is missing the managed pull Secret" >&2
      exit 1
    }
    grep -q 'public.ecr.aws/aws-cli/aws-cli:2.36.14@sha256:' "$render_dir/all.yaml" || {
      echo "ERROR: direct ECR render is missing the pinned AWS CLI image" >&2
      exit 1
    }
    grep -q 'registry.k8s.io/kubectl:v1.32.13@sha256:' "$render_dir/all.yaml" || {
      echo "ERROR: direct ECR render is missing the pinned kubectl image" >&2
      exit 1
    }
  fi
done

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "$repo_root"/scripts/*.sh
fi

if command -v yamllint >/dev/null 2>&1; then
  yamllint \
    --config-file "$repo_root/.yamllint.yaml" \
    "$repo_root/defaults" \
    "$repo_root/examples" \
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
