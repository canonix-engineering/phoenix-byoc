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

# The supported no-delivery mode must pass preflight and render without
# Mailgun or SMTP credentials. Mock only the read-only Kubernetes calls made by
# preflight so this check never reaches a real cluster.
mail_test_tmp="$example_tmp/mail-test"
mkdir -p "$mail_test_tmp"
cp "$repo_root/tests/fixtures/values-private-registry.yaml" \
  "$mail_test_tmp/values.yaml"
cp "$repo_root/tests/fixtures/values.secrets.yaml" \
  "$mail_test_tmp/values.secrets.yaml"
yq -i '
  .application.mailer.deliveryMethod = "test" |
  .application.mailer.domain = ""
' "$mail_test_tmp/values.yaml"
yq -i '
  .secrets.application.mailgunApiKey = "" |
  .secrets.application.smtpPassword = ""
' "$mail_test_tmp/values.secrets.yaml"
kubectl() {
  case "$*" in
    "config current-context")
      echo "test-context"
      ;;
    "version --output=json")
      echo '{}'
      ;;
    "get customresourcedefinition "*)
      return 1
      ;;
    *)
      echo "ERROR: unexpected kubectl call in mail-mode test: $*" >&2
      return 93
      ;;
  esac
}
export -f kubectl
PHOENIX_BYOC_NAMESPACE=phoenix-mail-test \
PHOENIX_BYOC_VALUES_FILE="$mail_test_tmp/values.yaml" \
PHOENIX_BYOC_SECRETS_FILE="$mail_test_tmp/values.secrets.yaml" \
  "$repo_root/scripts/preflight.sh" >"$mail_test_tmp/preflight.log"
unset -f kubectl
grep -q 'Preflight passed.' "$mail_test_tmp/preflight.log" || {
  echo "ERROR: deliveryMethod test did not pass preflight" >&2
  exit 1
}

mail_test_render_dir="$repo_root/.rendered/test-mail-disabled"
mkdir -p "$cache_dir" "$mail_test_render_dir"
(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" \
    PHOENIX_BYOC_LOCAL_CHARTS="$devops_charts" \
    PHOENIX_BYOC_VALUES_FILE="$mail_test_tmp/values.yaml" \
    PHOENIX_BYOC_SECRETS_FILE="$mail_test_tmp/values.secrets.yaml" \
    PHOENIX_BYOC_NAMESPACE=phoenix-mail-test \
    helmfile template --skip-deps --quiet \
    >"$mail_test_render_dir/all.yaml"
)
chmod 600 "$mail_test_render_dir/all.yaml"
grep -Eq 'MAIL_DELIVERY_METHOD: "?test"?' "$mail_test_render_dir/all.yaml" || {
  echo "ERROR: deliveryMethod test was not rendered" >&2
  exit 1
}
if grep -Eq 'SMTP_USER_NAME|SMTP_PASSWORD' "$mail_test_render_dir/all.yaml"; then
  echo "ERROR: no-delivery render contains SMTP credentials" >&2
  exit 1
fi

# An unauthenticated SMTP relay must also pass preflight and render without
# credentials, while retaining the relay address and port.
yq -i '
  .application.mailer.deliveryMethod = "smtp" |
  .application.mailer.smtp.address = "smtp.internal.example" |
  .application.mailer.smtp.port = "25" |
  .application.mailer.smtp.userName = "" |
  .application.mailer.smtp.authentication = ""
' "$mail_test_tmp/values.yaml"
kubectl() {
  case "$*" in
    "config current-context")
      echo "test-context"
      ;;
    "version --output=json")
      echo '{}'
      ;;
    "get customresourcedefinition "*)
      return 1
      ;;
    *)
      echo "ERROR: unexpected kubectl call in SMTP test: $*" >&2
      return 94
      ;;
  esac
}
export -f kubectl
PHOENIX_BYOC_NAMESPACE=phoenix-mail-test \
PHOENIX_BYOC_VALUES_FILE="$mail_test_tmp/values.yaml" \
PHOENIX_BYOC_SECRETS_FILE="$mail_test_tmp/values.secrets.yaml" \
  "$repo_root/scripts/preflight.sh" >"$mail_test_tmp/smtp-preflight.log"
unset -f kubectl
grep -q 'Preflight passed.' "$mail_test_tmp/smtp-preflight.log" || {
  echo "ERROR: unauthenticated SMTP did not pass preflight" >&2
  exit 1
}

smtp_render_dir="$repo_root/.rendered/test-smtp-no-auth"
mkdir -p "$smtp_render_dir"
(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" \
    PHOENIX_BYOC_LOCAL_CHARTS="$devops_charts" \
    PHOENIX_BYOC_VALUES_FILE="$mail_test_tmp/values.yaml" \
    PHOENIX_BYOC_SECRETS_FILE="$mail_test_tmp/values.secrets.yaml" \
    PHOENIX_BYOC_NAMESPACE=phoenix-mail-test \
    helmfile template --skip-deps --quiet \
    >"$smtp_render_dir/all.yaml"
)
chmod 600 "$smtp_render_dir/all.yaml"
grep -Eq 'SMTP_ADDRESS: "?smtp.internal.example"?' \
  "$smtp_render_dir/all.yaml" || {
  echo "ERROR: unauthenticated SMTP address was not rendered" >&2
  exit 1
}
grep -Eq 'SMTP_PORT: "?25"?' "$smtp_render_dir/all.yaml" || {
  echo "ERROR: unauthenticated SMTP port was not rendered" >&2
  exit 1
}
if grep -Eq 'SMTP_USER_NAME|SMTP_PASSWORD' "$smtp_render_dir/all.yaml"; then
  echo "ERROR: unauthenticated SMTP render contains credentials" >&2
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
gateway_encryption_key=$(yq -r '.secrets.gateway.remoteSshEncryptionKey' \
  "$generator_tmp/values.secrets.yaml")
gateway_encryption_key_size=$(printf '%s' "$gateway_encryption_key" | \
  openssl base64 -d -A | wc -c | tr -d ' ')
if [[ "$gateway_encryption_key_size" != "32" ]]; then
  echo "ERROR: Gateway master key was not generated as 32-byte base64" >&2
  exit 1
fi
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
if [[ "$(yq -r '.secrets.gateway.remoteSshEncryptionKey' \
    "$generator_tmp/values.secrets.yaml")" != "$gateway_encryption_key" ]]; then
  echo "ERROR: reconciliation rotated the Gateway master key" >&2
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

# Snapshot pause/resume is opt-in. Its render must keep the existing ECR-only
# pull Secret and create a separate Docker config containing source ECR and
# target-registry credentials for the unmodified OpenSandbox image committer.
snapshot_tmp="$example_tmp/snapshot-registry"
mkdir -p "$snapshot_tmp"
cp "$repo_root/tests/fixtures/values-direct-ecr.yaml" "$snapshot_tmp/values.yaml"
cp "$repo_root/tests/fixtures/values.secrets-direct-ecr.yaml" "$snapshot_tmp/secrets.yaml"
yq -i '
  .opensandboxController.snapshot.enabled = true |
  .opensandboxController.snapshot.registry = "us-east4-docker.pkg.dev/customer-project/opensandbox-snapshots/images"
' "$snapshot_tmp/values.yaml"
yq -i '
  .secrets.registry.snapshot.username = "_json_key" |
  .secrets.registry.snapshot.password = "test-only-service-account-json"
' "$snapshot_tmp/secrets.yaml"
kubectl() {
  case "$*" in
    "config current-context")
      echo "test-context"
      ;;
    "version --output=json")
      echo '{}'
      ;;
    "get customresourcedefinition "*)
      return 1
      ;;
    *)
      echo "ERROR: unexpected kubectl call in snapshot test: $*" >&2
      return 95
      ;;
  esac
}
export -f kubectl
PHOENIX_BYOC_NAMESPACE=phoenix \
PHOENIX_BYOC_VALUES_FILE="$snapshot_tmp/values.yaml" \
PHOENIX_BYOC_SECRETS_FILE="$snapshot_tmp/secrets.yaml" \
  "$repo_root/scripts/preflight.sh" >"$snapshot_tmp/preflight.log"
unset -f kubectl
grep -q 'OpenSandbox snaps:  true' "$snapshot_tmp/preflight.log" || {
  echo "ERROR: enabled snapshot mode did not pass preflight" >&2
  exit 1
}
snapshot_render_dir="$repo_root/.rendered/test-snapshot-registry"
mkdir -p "$snapshot_render_dir"
(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" \
    PHOENIX_BYOC_LOCAL_CHARTS="$devops_charts" \
    PHOENIX_BYOC_VALUES_FILE="$snapshot_tmp/values.yaml" \
    PHOENIX_BYOC_SECRETS_FILE="$snapshot_tmp/secrets.yaml" \
    PHOENIX_BYOC_NAMESPACE=phoenix \
    helmfile template --skip-deps --quiet \
    >"$snapshot_render_dir/all.yaml"
)
chmod 600 "$snapshot_render_dir/all.yaml"

for secret_name in phoenix-ecr-pull opensandbox-registry-auth; do
  yq -e \
    "select(.kind == \"Secret\" and .metadata.name == \"$secret_name\")" \
    "$snapshot_render_dir/all.yaml" >/dev/null || {
      echo "ERROR: snapshot render is missing Secret $secret_name" >&2
      exit 1
    }
done

controller_args=$(yq -r '
  select(.kind == "Deployment" and .metadata.name == "opensandbox-controller-manager") |
  .spec.template.spec.containers[0].args[]
' "$snapshot_render_dir/all.yaml")
for expected_arg in \
  '--snapshot-registry=us-east4-docker.pkg.dev/customer-project/opensandbox-snapshots/images' \
  '--snapshot-push-secret=opensandbox-registry-auth' \
  '--resume-pull-secret=opensandbox-registry-auth' \
  '--image-committer-image=ghcr.io/canonix-engineering/phoenix-byoc/opensandbox-controller:image-committer-upstream-6c433a77@sha256:e71d430aa8647ec5437b1515f77748b06f4c3362756edac0dc75ca053fe21b92'; do
  grep -Fxq -- "$expected_arg" <<<"$controller_args" || {
    echo "ERROR: snapshot controller argument is missing: $expected_arg" >&2
    exit 1
  }
done

snapshot_refresh_script=$(yq -r '
  select(.kind == "CronJob" and .metadata.name == "ecr-pull-secret-refresh") |
  .spec.jobTemplate.spec.template.spec.initContainers[] |
  select(.name == "generate-pull-secret") | .args[0]
' "$snapshot_render_dir/all.yaml")
for expected_text in \
  'SNAPSHOT_REGISTRY_USERNAME' \
  'SNAPSHOT_REGISTRY_PASSWORD' \
  '$ECR_REGISTRY' \
  '$SNAPSHOT_REGISTRY_HOST'; do
  grep -Fq -- "$expected_text" <<<"$snapshot_refresh_script" || {
    echo "ERROR: snapshot refresh script is missing $expected_text" >&2
    exit 1
  }
done

snapshot_registry_host=$(yq -r '
  select(.kind == "CronJob" and .metadata.name == "ecr-pull-secret-refresh") |
  .spec.jobTemplate.spec.template.spec.initContainers[] |
  select(.name == "generate-pull-secret") | .env[] |
  select(.name == "SNAPSHOT_REGISTRY_HOST") | .value
' "$snapshot_render_dir/all.yaml")
if [[ "$snapshot_registry_host" != "us-east4-docker.pkg.dev" ]]; then
  echo "ERROR: snapshot Docker auth key must be the registry hostname" >&2
  exit 1
fi

# The ordinary direct-ECR render remains snapshot-free and must not contain
# either the combined Secret or snapshot controller flags.
if grep -Eq 'opensandbox-registry-auth|--snapshot-registry=' \
    "$repo_root/.rendered/test-direct-ecr/all.yaml"; then
  echo "ERROR: disabled snapshot mode changed the direct-ECR installation" >&2
  exit 1
fi

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

action_cable_allowed_origins=$(yq -r \
  'select(.kind == "ConfigMap" and .metadata.name == "phoenix-web") | .data.ACTION_CABLE_ALLOWED_ORIGINS' \
  "$repo_root/.rendered/test-bundled/all.yaml")
if [[ "$action_cable_allowed_origins" != *"http://phoenix-web.phoenix.svc.cluster.local"* ]]; then
  echo "ERROR: Phoenix Web does not allow the internal agent harness WebSocket origin" >&2
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

github_pr_creation_enabled=$(yq -r \
  'select(.kind == "ConfigMap" and .metadata.name == "phoenix-workflow-engine") | .data.GITHUB_PULL_REQUEST_CREATION_ENABLED' \
  "$repo_root/.rendered/test-bundled/all.yaml")
github_public_prs_enabled=$(yq -r \
  'select(.kind == "ConfigMap" and .metadata.name == "phoenix-workflow-engine") | .data.GITHUB_ALLOW_PUBLIC_PULL_REQUESTS' \
  "$repo_root/.rendered/test-bundled/all.yaml")
if [[ "$github_pr_creation_enabled" != "false" || "$github_public_prs_enabled" != "false" ]]; then
  echo "ERROR: Workflow Engine GitHub PR policy defaults must render false/false" >&2
  exit 1
fi

gateway_encryption_secret=$(yq -r '
  select(.kind == "Deployment" and .metadata.name == "phoenix-gateway") |
  .spec.template.spec.containers[0].env[] |
  select(.name == "PHOENIX_REMOTE_SSH_ENCRYPTION_KEY") |
  .valueFrom.secretKeyRef.name
' "$repo_root/.rendered/test-bundled/all.yaml")
if [[ "$gateway_encryption_secret" != "phoenix-remote-ssh-encryption" ]]; then
  echo "ERROR: Gateway does not reference the managed SSH encryption Secret" >&2
  exit 1
fi

# The exact customer-facing examples must render after their documented
# placeholders are replaced; fixtures alone are not sufficient coverage.
sed -E 's/CHANGE_ME_[A-Z0-9_]*/test-only/g' \
  "$repo_root/examples/values.yaml" >"$example_tmp/values.yaml"
sed -E 's/CHANGE_ME_[A-Z0-9_]*/test-only/g; s/GENERATE_(HEX_(32|64)|BASE64_32)/test-only/g; s/DERIVE_[A-Z0-9_]*/test-only/g' \
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

yq -i '
  .services.workflowEngine.githubPullRequests.creationEnabled = true |
  .services.workflowEngine.githubPullRequests.allowPublicRepositories = true
' "$example_tmp/values.yaml"
github_pr_render_dir="$repo_root/.rendered/test-github-public-prs"
mkdir -p "$github_pr_render_dir"
(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" \
    PHOENIX_BYOC_LOCAL_CHARTS="$devops_charts" \
    PHOENIX_BYOC_VALUES_FILE="$example_tmp/values.yaml" \
    PHOENIX_BYOC_SECRETS_FILE="$example_tmp/secrets.yaml" \
    PHOENIX_BYOC_NAMESPACE=phoenix-example \
    helmfile template --skip-deps --quiet \
    >"$github_pr_render_dir/all.yaml"
)
chmod 600 "$github_pr_render_dir/all.yaml"
for expected in \
  'GITHUB_PULL_REQUEST_CREATION_ENABLED=true' \
  'GITHUB_ALLOW_PUBLIC_PULL_REQUESTS=true'; do
  key=${expected%%=*}
  expected_value=${expected#*=}
  actual_value=$(yq -r \
    "select(.kind == \"ConfigMap\" and .metadata.name == \"phoenix-workflow-engine\") | .data.$key" \
    "$github_pr_render_dir/all.yaml")
  if [[ "$actual_value" != "$expected_value" ]]; then
    echo "ERROR: $key did not render as $expected_value" >&2
    exit 1
  fi
done

# CSG is opt-in, but the regular BYOC values must be sufficient to render its
# operator configuration and GKE Workload Identity annotation.
yq -i '
  .services.workflowEngine.csg.enabled = true |
  .services.workflowEngine.csg.project = "customer-project" |
  .services.workflowEngine.csg.scriptEnv.HOST_PROJECT = "customer-host-project" |
  .services.workflowEngine.operator.serviceAccountAnnotations."iam.gke.io/gcp-service-account" = "provisioner@customer-project.iam.gserviceaccount.com"
' "$example_tmp/values.yaml"
csg_render_dir="$repo_root/.rendered/test-csg"
mkdir -p "$csg_render_dir"
(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" \
    PHOENIX_BYOC_LOCAL_CHARTS="$devops_charts" \
    PHOENIX_BYOC_VALUES_FILE="$example_tmp/values.yaml" \
    PHOENIX_BYOC_SECRETS_FILE="$example_tmp/secrets.yaml" \
    PHOENIX_BYOC_NAMESPACE=phoenix-example \
    helmfile template --skip-deps --quiet \
    >"$csg_render_dir/all.yaml"
)
chmod 600 "$csg_render_dir/all.yaml"
for expected in \
  'CSG_INTEGRATION_ENABLED=true' \
  'CSG_GCP_PROJECT_ID=customer-project' \
  'HOST_PROJECT=customer-host-project'; do
  key=${expected%%=*}
  expected_value=${expected#*=}
  actual_value=$(yq -r \
    "select(.kind == \"Deployment\" and .metadata.name == \"phoenix-workflow-engine-operator\") | .spec.template.spec.containers[0].env[] | select(.name == \"$key\") | .value" \
    "$csg_render_dir/all.yaml")
  if [[ "$actual_value" != "$expected_value" ]]; then
    echo "ERROR: CSG value $key did not render as $expected_value" >&2
    exit 1
  fi
done
csg_service_account_annotation=$(yq -r '
  select(.kind == "ServiceAccount" and .metadata.name == "phoenix-workflow-engine-operator") |
  .metadata.annotations."iam.gke.io/gcp-service-account"
' "$csg_render_dir/all.yaml")
if [[ "$csg_service_account_annotation" != "provisioner@customer-project.iam.gserviceaccount.com" ]]; then
  echo "ERROR: CSG operator service account annotation did not render" >&2
  exit 1
fi

yq -i '.services.workflowEngine.githubPullRequests.creationEnabled = false' \
  "$example_tmp/values.yaml"
if PHOENIX_BYOC_NAMESPACE=phoenix-example \
   PHOENIX_BYOC_VALUES_FILE="$example_tmp/values.yaml" \
   PHOENIX_BYOC_SECRETS_FILE="$example_tmp/secrets.yaml" \
   "$repo_root/scripts/preflight.sh" >"$example_tmp/github-pr-invalid.log" 2>&1; then
  echo "ERROR: preflight accepted public PRs while PR creation was disabled" >&2
  exit 1
fi
grep -q 'requires services.workflowEngine.githubPullRequests.creationEnabled=true' \
  "$example_tmp/github-pr-invalid.log" || {
    echo "ERROR: preflight did not explain the invalid GitHub PR policy" >&2
    exit 1
  }

# Restore the documented default before using this example for the shared
# OpenSandbox-controller render below.
yq -i '.services.workflowEngine.githubPullRequests.allowPublicRepositories = false' \
  "$example_tmp/values.yaml"
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

helm lint "$repo_root/charts/ecr-pull-secret-refresh" \
  --set registry=526563839763.dkr.ecr.us-east-1.amazonaws.com \
  --set credentials.accessKeyId=test-only-access-key \
  --set credentials.secretAccessKey=test-only-secret-key \
  --set snapshotRegistry.enabled=true \
  --set snapshotRegistry.registryHost=us-east4-docker.pkg.dev \
  --set snapshotRegistry.secretName=opensandbox-registry-auth \
  --set snapshotRegistry.credentials.username=_json_key \
  --set snapshotRegistry.credentials.password=test-only-gar-key \
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
if [[ "$image_count" != "11" ]]; then
  echo "ERROR: release.yaml must contain 10 core images and the snapshot image committer" >&2
  exit 1
fi
while IFS= read -r image_ref; do
  image_render="$repo_root/.rendered/test-bundled/all.yaml"
  if [[ "$image_ref" == *"image-committer-upstream-6c433a77"* ]]; then
    image_render="$snapshot_render_dir/all.yaml"
  fi
  grep -Fq "$image_ref" "$image_render" || {
    echo "ERROR: release image does not match the rendered deployment: $image_ref" >&2
    exit 1
  }
done < <("$repo_root/scripts/images.sh" list)

echo "Static BYOC tests passed."
