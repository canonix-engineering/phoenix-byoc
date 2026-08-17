#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
values_file=${PHOENIX_BYOC_VALUES_FILE:-}
secrets_file=${PHOENIX_BYOC_SECRETS_FILE:-}
if [[ -z "$values_file" || -z "$secrets_file" ]]; then
  echo "ERROR: PHOENIX_BYOC_VALUES_FILE and PHOENIX_BYOC_SECRETS_FILE are required." >&2
  echo "Run scripts/install.sh with --values and --secrets." >&2
  exit 1
fi
if [[ "$values_file" != /* ]]; then
  values_file="$repo_root/$values_file"
fi
if [[ "$secrets_file" != /* ]]; then
  secrets_file="$repo_root/$secrets_file"
fi

for command in helm helmfile kubectl yq; do
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

if ! yq -e 'type == "!!map" and length > 0' "$values_file" >/dev/null 2>&1; then
  echo "ERROR: values file must be a non-empty YAML mapping: $values_file" >&2
  exit 1
fi
if ! yq -e 'type == "!!map" and length > 0' "$secrets_file" >/dev/null 2>&1; then
  echo "ERROR: secrets file must be a non-empty YAML mapping: $secrets_file" >&2
  exit 1
fi
if yq -e '[.. | select(tag == "!!str" and test("CHANGE_ME"))] | length > 0' \
    "$values_file" >/dev/null 2>&1; then
  echo "ERROR: values file still contains CHANGE_ME placeholders: $values_file" >&2
  exit 1
fi
if yq -e '[.. | select(tag == "!!str" and test("CHANGE_ME"))] | length > 0' \
    "$secrets_file" >/dev/null 2>&1; then
  echo "ERROR: secret values file still contains CHANGE_ME placeholders." >&2
  exit 1
fi

release_channel=$(yq -r '.release.channel // ""' "$repo_root/release.yaml")
release_version=$(yq -r '.release.version // ""' "$repo_root/release.yaml")
if [[ -z "$release_channel" || -z "$release_version" ]]; then
  echo "ERROR: release.yaml does not contain release.version and release.channel" >&2
  exit 1
fi
if yq -e '[.. | select(tag == "!!str" and test("CHANGE_ME"))] | length > 0' \
    "$repo_root/release.yaml" >/dev/null 2>&1; then
  echo "ERROR: release.yaml contains an unresolved version placeholder." >&2
  exit 1
fi

relative_secrets=${secrets_file#"$repo_root/"}
if [[ "$relative_secrets" != "$secrets_file" ]] && \
    [[ -n "$(git -C "$repo_root" ls-files -- "$relative_secrets" 2>/dev/null)" ]]; then
  echo "ERROR: selected secrets file is tracked by Git: $relative_secrets" >&2
  exit 1
fi

namespace=${PHOENIX_BYOC_NAMESPACE:-}
if [[ -z "$namespace" ]]; then
  echo "ERROR: namespace is required; run install.sh --namespace <name>." >&2
  exit 1
fi
if [[ ! "$namespace" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
  echo "ERROR: namespace must be a valid lowercase Kubernetes DNS label." >&2
  exit 1
fi

merged_file=$(mktemp)
trap 'rm -f "$merged_file"' EXIT
chmod 600 "$merged_file"
# shellcheck disable=SC2016 # $item is a yq variable, not a shell variable.
yq eval-all '. as $item ireduce ({}; . * $item)' \
  "$repo_root/release.yaml" \
  "$repo_root/defaults/values.yaml" \
  "$values_file" \
  "$secrets_file" >"$merged_file"

value() {
  local result
  result=$(yq -r ".$1" "$merged_file")
  if [[ "$result" == "null" ]]; then
    result=""
  fi
  printf '%s\n' "$result"
}

missing=()
require_value() {
  local path=$1
  if [[ -z "$(value "$path")" ]]; then
    missing+=("$path")
  fi
}

for path in \
  application.tenantId \
  application.appHost \
  application.spaHost \
  application.allowedHosts \
  application.cortex.host \
  application.cortex.scheme \
  application.mailer.from \
  application.mailer.domain \
  secrets.postgresql.applicationPassword \
  secrets.postgresql.internalPassword \
  secrets.application.secretKeyBase \
  secrets.application.agentHarnessToken \
  secrets.application.workflowEngineArtifactApiToken \
  secrets.application.workflowEngineToken \
  secrets.application.mailgunApiKey \
  secrets.application.guardrailsTestToken \
  secrets.application.jsTransformTestToken \
  secrets.application.toolInvocationTestToken; do
  require_value "$path"
done

bundled_postgresql=$(value postgresql.bundled.enabled)
bundled_redis=$(value redis.bundled.enabled)
bundled_cortex=$(value cortex.bundled.enabled)
bundled_clickhouse=$(value clickhouse.bundled.enabled)
bundled_ingress=$(value ingressNginx.enabled)
opensandbox_controller_enabled=$(value opensandboxController.enabled)
opensandbox_crds_install=$(value opensandboxController.crds.install)

if [[ "$bundled_postgresql" == "true" ]]; then
  require_value secrets.postgresql.superuserPassword
else
  require_value postgresql.external.host
  if [[ "$(value postgresql.hooks.phoenixWeb)" == "true" || \
        "$(value postgresql.hooks.workflowEngine)" == "true" ]]; then
    require_value secrets.postgresql.adminUrl
  fi
fi

if [[ "$bundled_redis" != "true" ]]; then
  require_value secrets.redis.url
fi
if [[ "$bundled_cortex" == "true" ]]; then
  require_value secrets.cortex.password
else
  require_value secrets.cortex.url
fi
if [[ "$bundled_clickhouse" == "true" ]]; then
  require_value clickhouse.bundled.username
  require_value clickhouse.bundled.database
  require_value secrets.clickhouse.password
else
  require_value secrets.clickhouse.url
fi

if ((${#missing[@]} > 0)); then
  echo "ERROR: required configuration is missing:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  exit 1
fi

if [[ "$bundled_clickhouse" == "true" ]]; then
  clickhouse_password=$(value secrets.clickhouse.password)
  if [[ ! "$clickhouse_password" =~ ^[A-Za-z0-9._~-]+$ ]]; then
    echo "ERROR: secrets.clickhouse.password must use URL-safe characters: A-Z a-z 0-9 . _ ~ -" >&2
    exit 1
  fi
fi

context=$(kubectl config current-context 2>/dev/null || true)
if [[ -z "$context" ]]; then
  echo "ERROR: kubectl has no current context" >&2
  exit 1
fi
kubectl version --output=json >/dev/null

opensandbox_crds=(
  batchsandboxes.sandbox.opensandbox.io
  pools.sandbox.opensandbox.io
  sandboxsnapshots.sandbox.opensandbox.io
)
if [[ "$opensandbox_controller_enabled" == "true" && "$opensandbox_crds_install" == "true" ]]; then
  for crd_name in "${opensandbox_crds[@]}"; do
    if ! kubectl get customresourcedefinition "$crd_name" >/dev/null 2>&1; then
      continue
    fi
    owner_release=$(kubectl get customresourcedefinition "$crd_name" \
      -o 'jsonpath={.metadata.annotations.meta\.helm\.sh/release-name}')
    owner_namespace=$(kubectl get customresourcedefinition "$crd_name" \
      -o 'jsonpath={.metadata.annotations.meta\.helm\.sh/release-namespace}')
    if [[ "$owner_release" != "opensandbox-controller" || "$owner_namespace" != "$namespace" ]]; then
      echo "ERROR: OpenSandbox CRD '$crd_name' already exists and is not owned by" >&2
      echo "       release opensandbox-controller in namespace '$namespace'." >&2
      echo "       Set opensandboxController.enabled=false only when reusing an existing" >&2
      echo "       compatible cluster-wide OpenSandbox controller." >&2
      exit 1
    fi
  done
else
  for crd_name in "${opensandbox_crds[@]}"; do
    if ! kubectl get customresourcedefinition "$crd_name" >/dev/null 2>&1; then
      echo "ERROR: required OpenSandbox CRD does not exist: $crd_name" >&2
      exit 1
    fi
  done
fi

pull_secrets=$(yq -r '.imagePullSecrets[]?.name // ""' "$merged_file")
image_registry=$(value imageRegistry)
ecr_refresh_enabled=$(value registry.ecrRefresh.enabled)
ecr_refresh_pull_secret=$(value registry.ecrRefresh.pullSecretName)
ecr_credentials_secret=$(value registry.ecrRefresh.credentialsSecretName)

managed_pull_secret=""
if [[ "$ecr_refresh_enabled" == "true" ]]; then
  if [[ -n "$image_registry" ]]; then
    echo "ERROR: imageRegistry must be empty when registry.ecrRefresh.enabled=true." >&2
    exit 1
  fi
  if [[ -z "$ecr_refresh_pull_secret" ]]; then
    echo "ERROR: registry.ecrRefresh.pullSecretName is required." >&2
    exit 1
  fi
  if ! grep -Fxq "$ecr_refresh_pull_secret" <<<"$pull_secrets"; then
    echo "ERROR: imagePullSecrets must include '$ecr_refresh_pull_secret' when ECR refresh is enabled." >&2
    exit 1
  fi
  managed_pull_secret=$ecr_refresh_pull_secret

  if [[ -n "$ecr_credentials_secret" ]]; then
    if ! kubectl get namespace "$namespace" >/dev/null 2>&1; then
      echo "ERROR: namespace '$namespace' must exist when using an existing ECR credentials Secret." >&2
      exit 1
    fi
    kubectl -n "$namespace" get secret "$ecr_credentials_secret" >/dev/null || {
      echo "ERROR: ECR credentials Secret '$ecr_credentials_secret' does not exist in namespace '$namespace'." >&2
      exit 1
    }
    for credential_key in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
      credential_value=$(kubectl -n "$namespace" get secret "$ecr_credentials_secret" \
        -o "jsonpath={.data.$credential_key}")
      if [[ -z "$credential_value" ]]; then
        echo "ERROR: ECR credentials Secret '$ecr_credentials_secret' is missing key '$credential_key'." >&2
        exit 1
      fi
    done
  else
    require_value secrets.registry.ecr.accessKeyId
    require_value secrets.registry.ecr.secretAccessKey
    if ((${#missing[@]} > 0)); then
      echo "ERROR: required configuration is missing:" >&2
      printf '  %s\n' "${missing[@]}" >&2
      exit 1
    fi
  fi
fi

if [[ -n "$pull_secrets" ]]; then
  unmanaged_pull_secrets=$(awk -v managed="$managed_pull_secret" \
    'NF && $0 != managed { print }' <<<"$pull_secrets")
  if [[ -n "$unmanaged_pull_secrets" ]] && \
      ! kubectl get namespace "$namespace" >/dev/null 2>&1; then
    echo "ERROR: namespace '$namespace' must exist before using pre-created registry pull secrets." >&2
    exit 1
  fi
  while IFS= read -r secret_name; do
    [[ -z "$secret_name" || "$secret_name" == "$managed_pull_secret" ]] && continue
    kubectl -n "$namespace" get secret "$secret_name" >/dev/null || {
      echo "ERROR: image pull secret '$secret_name' does not exist in namespace '$namespace'." >&2
      exit 1
    }
  done <<<"$pull_secrets"
fi

if [[ -n "$image_registry" ]]; then
  image_source="mirrored registry: $image_registry"
elif [[ "$ecr_refresh_enabled" == "true" ]]; then
  image_source="Phoenix ECR with managed token refresh"
else
  image_source="release.yaml repositories with cluster-managed authentication"
fi

echo "Release:            $release_version ($release_channel)"
echo "Kubernetes context: $context"
echo "Namespace:          $namespace"
echo "Values file:        $values_file"
echo "Secrets file:       $secrets_file"
echo "Image source:       $image_source"
echo "Bundled PostgreSQL: $bundled_postgresql"
echo "Bundled Redis:      $bundled_redis"
echo "Bundled Cortex DB:  $bundled_cortex"
echo "Bundled ClickHouse: $bundled_clickhouse"
echo "Bundled ingress:    $bundled_ingress"
echo "OpenSandbox ctrl:   $opensandbox_controller_enabled"
echo "ECR token refresh:  $ecr_refresh_enabled"
echo "Preflight passed."
