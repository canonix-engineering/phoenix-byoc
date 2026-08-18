#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
devops_charts="${PHOENIX_BYOC_LOCAL_CHARTS:-$repo_root/../phoenix-devops/charts}"
cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"
example_tmp=$(mktemp -d)
trap 'rm -rf "$example_tmp"' EXIT

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
      clickhouse \
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

if grep -q 'postgresql-postgresql.*sslmode=require' \
    "$repo_root/.rendered/test-bundled/all.yaml"; then
  echo "ERROR: bundled PostgreSQL render incorrectly requires TLS" >&2
  exit 1
fi
grep -q 'postgresql-postgresql.*sslmode=disable' \
  "$repo_root/.rendered/test-bundled/all.yaml" || {
    echo "ERROR: bundled PostgreSQL render is missing sslmode=disable" >&2
    exit 1
  }
grep -q 'postgresql.test.invalid.*sslmode=verify-full' \
  "$repo_root/.rendered/test-external/all.yaml" || {
    echo "ERROR: external PostgreSQL render does not preserve customer sslmode" >&2
    exit 1
  }

gateway_engine_token=$(yq -r \
  'select(.kind == "Secret" and .metadata.name == "phoenix-gateway") | .data.PHOENIX_WORKFLOW_ENGINE_TOKEN' \
  "$repo_root/.rendered/test-bundled/all.yaml")
workflow_engine_token=$(yq -r \
  'select(.kind == "Secret" and .metadata.name == "phoenix-workflow-engine") | .data.PHOENIX_WORKFLOW_ENGINE_TOKEN' \
  "$repo_root/.rendered/test-bundled/all.yaml")
if [[ -z "$gateway_engine_token" || "$gateway_engine_token" != "$workflow_engine_token" ]]; then
  echo "ERROR: Gateway and Workflow Engine bearer tokens do not match" >&2
  exit 1
fi

agent_harness_url=$(yq -r \
  'select(.kind == "ConfigMap" and .metadata.name == "phoenix-workflow-engine") | .data.PHOENIX_AGENT_HARNESS_URL' \
  "$repo_root/.rendered/test-bundled/all.yaml")
if [[ "$agent_harness_url" != "ws://phoenix-web.phoenix.svc.cluster.local:80/cable" ]]; then
  echo "ERROR: Workflow Engine agent harness URL is missing or incorrect" >&2
  exit 1
fi

yq -e \
  'select(.kind == "Job" and .metadata.name == "phoenix-workflow-engine-migrate")' \
  "$repo_root/.rendered/test-bundled/all.yaml" >/dev/null || {
    echo "ERROR: Workflow Engine migration Job is missing" >&2
    exit 1
  }

if grep -Eq 'WORKFLOW_EVENTS_STREAMING_ENABLED|REDIS_CHANNEL_PREFIX' \
    "$repo_root/.rendered/test-bundled/all.yaml"; then
  echo "ERROR: rendered release contains the removed Redis workflow-event transport" >&2
  exit 1
fi

if yq -r \
  'select(.kind == "Secret" and .metadata.name == "phoenix-workflow-engine") | .data | keys | .[]' \
  "$repo_root/.rendered/test-bundled/all.yaml" | grep -qx 'GITHUB_PAT'; then
  echo "ERROR: Workflow Engine Secret contains the removed global GitHub PAT" >&2
  exit 1
fi

# The exact customer-facing examples must render after their documented
# placeholders are replaced; fixtures alone are not sufficient coverage.
sed -E 's/CHANGE_ME_[A-Z0-9_]*/test-only/g' \
  "$repo_root/examples/values.yaml" >"$example_tmp/values.yaml"
sed -E 's/CHANGE_ME_[A-Z0-9_]*/test-only/g' \
  "$repo_root/examples/values.secrets.yaml" >"$example_tmp/secrets.yaml"
example_render_dir="$repo_root/.rendered/test-customer-example"
mkdir -p "$example_render_dir"
(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" \
    PHOENIX_BYOC_LOCAL_CHARTS="$devops_charts" \
    PHOENIX_BYOC_VALUES_FILE="$example_tmp/values.yaml" \
    PHOENIX_BYOC_SECRETS_FILE="$example_tmp/secrets.yaml" \
    PHOENIX_BYOC_NAMESPACE=phoenix-example \
    helmfile template --skip-deps --quiet \
    >"$example_render_dir/all.yaml"
)
chmod 600 "$example_render_dir/all.yaml"
grep -q 'name: clickhouse' "$example_render_dir/all.yaml" || {
  echo "ERROR: customer example render is missing ClickHouse" >&2
  exit 1
}
grep -q 'name: ecr-pull-secret-refresh' "$example_render_dir/all.yaml" || {
  echo "ERROR: customer example render is missing direct ECR refresh" >&2
  exit 1
}
if command -v kubeconform >/dev/null 2>&1; then
  kubeconform \
    -kubernetes-version 1.32.0 \
    -strict \
    -summary \
    -ignore-missing-schemas \
    "$example_render_dir/all.yaml"
fi

# A shared cluster may already have one compatible cluster-wide OpenSandbox
# controller. The BYOC release must be able to reuse it without rendering a
# second controller or attempting to adopt its CRDs.
yq -i '.opensandboxController.enabled = false | .opensandboxController.crds.install = false' \
  "$example_tmp/values.yaml"
shared_controller_render_dir="$repo_root/.rendered/test-shared-controller"
mkdir -p "$shared_controller_render_dir"
(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" \
    PHOENIX_BYOC_LOCAL_CHARTS="$devops_charts" \
    PHOENIX_BYOC_VALUES_FILE="$example_tmp/values.yaml" \
    PHOENIX_BYOC_SECRETS_FILE="$example_tmp/secrets.yaml" \
    PHOENIX_BYOC_NAMESPACE=phoenix-example \
    helmfile template --skip-deps --quiet \
    >"$shared_controller_render_dir/all.yaml"
)
chmod 600 "$shared_controller_render_dir/all.yaml"
if grep -q 'name: opensandbox-controller-manager' "$shared_controller_render_dir/all.yaml"; then
  echo "ERROR: shared-controller render contains a second OpenSandbox controller" >&2
  exit 1
fi
if grep -q 'kind: CustomResourceDefinition' "$shared_controller_render_dir/all.yaml"; then
  echo "ERROR: shared-controller render attempts to install OpenSandbox CRDs" >&2
  exit 1
fi

helm lint "$repo_root/charts/clickhouse" \
  --set credentials.password=test-only-clickhouse \
  --set connection.url=http://phoenix:test-only-clickhouse@clickhouse:8123/phoenix \
  >/dev/null

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
    "$repo_root/Taskfile.yaml"
fi

image_count=$("$repo_root/scripts/images.sh" list | wc -l | tr -d ' ')
if [[ "$image_count" != "10" ]]; then
  echo "ERROR: release.yaml must contain exactly 10 required runtime images" >&2
  exit 1
fi
while IFS= read -r image_ref; do
  grep -Fq "$image_ref" "$repo_root/.rendered/test-bundled/all.yaml" || {
    echo "ERROR: release image does not match the rendered deployment: $image_ref" >&2
    exit 1
  }
done < <("$repo_root/scripts/images.sh" list)

echo "Static BYOC tests passed."
