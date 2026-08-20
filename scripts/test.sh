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

"$repo_root/scripts/create-initial-admin.sh" --help >/dev/null 2>&1
if "$repo_root/scripts/create-initial-admin.sh" \
    --namespace phoenix-admin-test >"$example_tmp/admin-missing.log" 2>&1; then
  echo "ERROR: initial administrator script accepted missing arguments" >&2
  exit 1
fi
grep -q -- '--enterprise-name' "$example_tmp/admin-missing.log" || {
  echo "ERROR: initial administrator script did not report missing arguments" >&2
  exit 1
}

# Mock kubectl so the complete interactive path can be checked without reading
# or changing a real application database.
kubectl() {
  local argument
  for argument in "$@"; do
    if [[ "$argument" == "test-only-admin-password" ]]; then
      echo "ERROR: password was passed in a kubectl argument" >&2
      return 91
    fi
  done
  if [[ "$*" == "config current-context" ]]; then
    echo "test-context"
    return
  fi
  if [[ " $* " == *" exec -i "* ]]; then
    local provided_password
    provided_password=$(cat)
    if [[ "$provided_password" != "test-only-admin-password" ]]; then
      echo "ERROR: password was not streamed through stdin" >&2
      return 92
    fi
    echo "Initial administrator created"
  fi
}
export -f kubectl
if ! printf 'test-only-admin-password\ntest-only-admin-password\n' | \
    "$repo_root/scripts/create-initial-admin.sh" \
      --namespace phoenix-admin-test \
      --enterprise-name "Test Enterprise" \
      --enterprise-domain test.example \
      --email admin@test.example \
      --name "Test Administrator" \
      >"$example_tmp/admin-create.log" 2>&1; then
  echo "ERROR: initial administrator mock execution failed" >&2
  unset -f kubectl
  exit 1
fi
unset -f kubectl
grep -q 'Kubernetes context: test-context' "$example_tmp/admin-create.log" || {
  echo "ERROR: initial administrator script did not display the context" >&2
  exit 1
}
grep -q 'Initial administrator created' "$example_tmp/admin-create.log" || {
  echo "ERROR: initial administrator script did not complete the mock bootstrap" >&2
  exit 1
}
if grep -q 'test-only-admin-password' "$example_tmp/admin-create.log"; then
  echo "ERROR: initial administrator script printed the password" >&2
  exit 1
fi

# Secret generation is exercised before any cluster access. The deliberately
# unresolved external credentials make preflight stop after the generator has
# created and reconciled the temporary file.
generator_tmp="$example_tmp/generator"
mkdir -p "$generator_tmp"
sed -E 's/CHANGE_ME_[A-Z0-9_]*/test-only/g' \
  "$repo_root/examples/values.yaml" >"$generator_tmp/values.yaml"
if "$repo_root/scripts/install.sh" \
    --namespace phoenix-generator-test \
    --values "$generator_tmp/values.yaml" \
    --secrets "$generator_tmp/values.secrets.yaml" \
    --generate-secrets >"$generator_tmp/first.log" 2>&1; then
  echo "ERROR: generator check unexpectedly passed unresolved external credentials" >&2
  exit 1
fi
[[ -f "$generator_tmp/values.secrets.yaml" ]] || {
  echo "ERROR: generator did not create the missing secrets file" >&2
  exit 1
}
generator_mode=$(stat -c %a "$generator_tmp/values.secrets.yaml" 2>/dev/null || \
  stat -f %Lp "$generator_tmp/values.secrets.yaml")
if [[ "$generator_mode" != "600" ]]; then
  echo "ERROR: generated secrets file mode is $generator_mode, expected 600" >&2
  exit 1
fi
yq -e \
  '[.. | select(tag == "!!str" and test("^(GENERATE_|DERIVE_)"))] | length == 0' \
  "$generator_tmp/values.secrets.yaml" >/dev/null || {
    echo "ERROR: generated secrets file contains unresolved generation markers" >&2
    exit 1
  }
yq -e '.secrets.application.secretKeyBase | test("^[0-9a-f]{128}$")' \
  "$generator_tmp/values.secrets.yaml" >/dev/null || {
    echo "ERROR: secretKeyBase was not generated as 64-byte hex" >&2
    exit 1
  }
grep -q 'secrets.registry.ecr.accessKeyId' "$generator_tmp/first.log" || {
  echo "ERROR: preflight did not report the unresolved ECR credential path" >&2
  exit 1
}
grep -q 'secrets.application.mailgunApiKey' "$generator_tmp/first.log" || {
  echo "ERROR: preflight did not report the unresolved mail credential path" >&2
  exit 1
}

workflow_token=$(yq -r '.secrets.application.workflowEngineToken' \
  "$generator_tmp/values.secrets.yaml")
workflow_token_hash=$(printf '%s' "$workflow_token" | shasum -a 256 | cut -d ' ' -f 1)
if grep -Fq "$workflow_token" "$generator_tmp/first.log"; then
  echo "ERROR: generator printed a generated secret value" >&2
  exit 1
fi
for index in {1..10}; do
  yq -i ".secrets.future.token${index} = \"GENERATE_HEX_32\"" \
    "$generator_tmp/values.secrets.yaml"
done
yq -i '
  del(.secrets.application.secretKeyBase) |
  del(.secrets.application.mailgunApiKey) |
  .secrets.application.agentHarnessToken = "CHANGE_ME_LEGACY_INTERNAL_TOKEN"
' "$generator_tmp/values.secrets.yaml"
if "$repo_root/scripts/install.sh" \
    --namespace phoenix-generator-test \
    --values "$generator_tmp/values.yaml" \
    --secrets "$generator_tmp/values.secrets.yaml" \
    --generate-secrets >"$generator_tmp/second.log" 2>&1; then
  echo "ERROR: reconciliation check unexpectedly passed external credentials" >&2
  exit 1
fi
yq -e \
  '[.secrets.future[] | select(test("^[0-9a-f]{64}$"))] | length == 10' \
  "$generator_tmp/values.secrets.yaml" >/dev/null || {
    echo "ERROR: generator did not fill all ten newly added secret fields" >&2
    exit 1
  }
yq -e '.secrets.application.agentHarnessToken | test("^[0-9a-f]{64}$")' \
  "$generator_tmp/values.secrets.yaml" >/dev/null || {
    echo "ERROR: legacy internal placeholder was not migrated" >&2
    exit 1
  }
if [[ "$(yq -r '.secrets.application.mailgunApiKey' \
    "$generator_tmp/values.secrets.yaml")" != "CHANGE_ME_MAILGUN_API_KEY" ]]; then
  echo "ERROR: reconciliation did not restore a missing template field" >&2
  exit 1
fi
workflow_token_after=$(yq -r '.secrets.application.workflowEngineToken' \
  "$generator_tmp/values.secrets.yaml")
workflow_token_hash_after=$(printf '%s' "$workflow_token_after" | \
  shasum -a 256 | cut -d ' ' -f 1)
if [[ "$workflow_token_hash" != "$workflow_token_hash_after" ]]; then
  echo "ERROR: reconciliation rotated an existing generated value" >&2
  exit 1
fi
if grep -Fq "$workflow_token_after" "$generator_tmp/second.log"; then
  echo "ERROR: reconciliation printed an existing secret value" >&2
  exit 1
fi

if "$repo_root/scripts/install.sh" \
    --namespace phoenix-generator-next \
    --values "$generator_tmp/values.yaml" \
    --secrets "$generator_tmp/values.secrets.yaml" \
    --generate-secrets >"$generator_tmp/third.log" 2>&1; then
  echo "ERROR: namespace refresh check unexpectedly passed external credentials" >&2
  exit 1
fi
if [[ "$(yq -r '.secrets.application.workflowEngineToken' \
    "$generator_tmp/values.secrets.yaml")" != "$workflow_token_after" ]]; then
  echo "ERROR: namespace refresh rotated an existing generated value" >&2
  exit 1
fi
if [[ "$(yq -r '.secrets.redis.url' "$generator_tmp/values.secrets.yaml")" != \
    "redis://redis-client.phoenix-generator-next.svc.cluster.local:6379/1" ]]; then
  echo "ERROR: namespace refresh did not update the derived Redis URL" >&2
  exit 1
fi
yq -i '.secrets.future.unsupported = "GENERATE_UUID"' \
  "$generator_tmp/values.secrets.yaml"
if "$repo_root/scripts/install.sh" \
    --namespace phoenix-generator-next \
    --values "$generator_tmp/values.yaml" \
    --secrets "$generator_tmp/values.secrets.yaml" \
    --generate-secrets >"$generator_tmp/unsupported.log" 2>&1; then
  echo "ERROR: unsupported generation marker was accepted" >&2
  exit 1
fi
grep -q 'secrets.future.unsupported' "$generator_tmp/unsupported.log" || {
  echo "ERROR: unsupported generation marker path was not reported" >&2
  exit 1
}

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
sed -E 's/CHANGE_ME_[A-Z0-9_]*/test-only/g; s/GENERATE_HEX_(32|64)/test-only/g; s/DERIVE_[A-Z0-9_]*/test-only/g' \
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
