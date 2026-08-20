#!/usr/bin/env bash
set -euo pipefail

requested_namespace=""
requested_values=""
requested_secrets=""
generate_secrets=false
while (($# > 0)); do
  case "$1" in
    --namespace)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "ERROR: --namespace requires a value." >&2
        exit 2
      fi
      requested_namespace=$2
      shift 2
      ;;
    --values)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "ERROR: --values requires a path." >&2
        exit 2
      fi
      requested_values=$2
      shift 2
      ;;
    --secrets)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "ERROR: --secrets requires a path." >&2
        exit 2
      fi
      requested_secrets=$2
      shift 2
      ;;
    --generate-secrets)
      generate_secrets=true
      shift
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$requested_namespace" || -z "$requested_values" || -z "$requested_secrets" ]]; then
  echo "Usage: ./scripts/install.sh --namespace <name> --values <path> --secrets <path> [--generate-secrets]" >&2
  exit 2
fi
if [[ ! "$requested_namespace" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
  echo "ERROR: namespace must be a valid lowercase Kubernetes DNS label." >&2
  exit 2
fi

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
values_file=$requested_values
if [[ "$values_file" != /* ]]; then
  values_file="$repo_root/$values_file"
fi
secrets_file=$requested_secrets
if [[ "$secrets_file" != /* ]]; then
  secrets_file="$repo_root/$secrets_file"
fi

generate_internal_secrets() (
  local namespace=$1
  local selected_values=$2
  local selected_secrets=$3
  local secrets_template="$repo_root/examples/values.secrets.yaml"
  local merged_config
  local generated_file
  local cluster_domain
  local postgres_port
  local cortex_user
  local cortex_database
  local clickhouse_user
  local clickhouse_database
  local generated_count=0
  local derived_count=0

  for command in openssl yq; do
    if ! command -v "$command" >/dev/null 2>&1; then
      echo "ERROR: --generate-secrets requires command: $command" >&2
      return 1
    fi
  done
  if [[ ! -f "$selected_values" ]]; then
    echo "ERROR: values file does not exist: $selected_values" >&2
    return 1
  fi
  if [[ ! -f "$secrets_template" ]]; then
    echo "ERROR: secret values template does not exist: $secrets_template" >&2
    return 1
  fi

  local relative_secrets=${selected_secrets#"$repo_root/"}
  if [[ "$relative_secrets" != "$selected_secrets" ]] && \
      [[ -n "$(git -C "$repo_root" ls-files -- "$relative_secrets" 2>/dev/null)" ]]; then
    echo "ERROR: refusing to generate secrets in a Git-tracked file: $relative_secrets" >&2
    return 1
  fi
  if ! yq -e 'type == "!!map" and length > 0' "$selected_values" >/dev/null 2>&1; then
    echo "ERROR: values file must be a non-empty YAML mapping: $selected_values" >&2
    return 1
  fi
  if ! yq -e 'type == "!!map" and length > 0' "$secrets_template" >/dev/null 2>&1; then
    echo "ERROR: secrets template must be a non-empty YAML mapping: $secrets_template" >&2
    return 1
  fi

  merged_config=$(mktemp)
  generated_file=""
  cleanup_generated_files() {
    [[ -z "$merged_config" ]] || rm -f -- "$merged_config"
    [[ -z "$generated_file" ]] || rm -f -- "$generated_file"
  }
  trap cleanup_generated_files EXIT
  chmod 600 "$merged_config"
  # shellcheck disable=SC2016 # $item is a yq variable, not a shell variable.
  yq eval-all '. as $item ireduce ({}; . * $item)' \
    "$repo_root/defaults/values.yaml" \
    "$selected_values" >"$merged_config"

  for bundled_path in \
    postgresql.bundled.enabled \
    redis.bundled.enabled \
    cortex.bundled.enabled \
    clickhouse.bundled.enabled; do
    if [[ "$(yq -r ".$bundled_path // false" "$merged_config")" != "true" ]]; then
      echo "ERROR: --generate-secrets currently requires all bundled dependencies." >&2
      echo "       Disabled dependency: ${bundled_path%.enabled}" >&2
      return 1
    fi
  done

  local secrets_directory
  secrets_directory=$(dirname "$selected_secrets")
  mkdir -p -- "$secrets_directory"
  if [[ ! -f "$selected_secrets" ]]; then
    cp "$secrets_template" "$selected_secrets"
    chmod 600 "$selected_secrets"
    echo "Created secret values file: $selected_secrets"
  fi
  if ! yq -e 'type == "!!map" and length > 0' "$selected_secrets" >/dev/null 2>&1; then
    echo "ERROR: secrets file must be a non-empty YAML mapping: $selected_secrets" >&2
    return 1
  fi

  generated_file=$(mktemp "${selected_secrets}.tmp.XXXXXX")
  chmod 600 "$generated_file"
  # The template supplies newly released fields; the selected file wins for
  # every value it already contains, including customer-specific extra keys.
  # shellcheck disable=SC2016 # $item is a yq variable, not a shell variable.
  yq eval-all '. as $item ireduce ({}; . * $item)' \
    "$secrets_template" \
    "$selected_secrets" >"$generated_file"

  # Convert empty or legacy CHANGE_ME values only at paths that the current
  # template classifies as generated. This preserves existing real values and
  # makes the marker contract backward compatible with older secrets files.
  while IFS=$'\t' read -r generated_path generated_marker; do
    [[ -z "$generated_path" ]] && continue
    local current
    current=$(yq -r ".$generated_path // \"\"" "$generated_file")
    if [[ -z "$current" || "$current" == CHANGE_ME_* ]]; then
      SECRET_VALUE="$generated_marker" \
        yq -i ".$generated_path = strenv(SECRET_VALUE)" "$generated_file"
    fi
  done < <(
    yq eval --no-doc -r '
      .. | select(tag == "!!str" and test("^GENERATE_HEX_(32|64)$")) |
      [(path | join(".")), .] | @tsv
    ' "$secrets_template"
  )

  local unknown_marker_paths
  unknown_marker_paths=$(yq eval --no-doc -r '
    .. | select(
      tag == "!!str" and
      (
        (
          test("^GENERATE_") and
          (test("^GENERATE_HEX_(32|64)$") | not)
        ) or
        (
          test("^DERIVE_") and
          (test("^DERIVE_(POSTGRES_ADMIN_URL|REDIS_URL|CORTEX_URL|CLICKHOUSE_URL|INTERNAL_SERVICE_TOKENS)$") | not)
        )
      )
    ) | path | join(".")
  ' "$generated_file")
  if [[ -n "$unknown_marker_paths" ]]; then
    echo "ERROR: unsupported secret markers:" >&2
    while IFS= read -r unknown_path; do
      [[ -z "$unknown_path" ]] || echo "  $unknown_path" >&2
    done <<<"$unknown_marker_paths"
    return 1
  fi

  while IFS=$'\t' read -r generated_path generated_marker; do
    [[ -z "$generated_path" ]] && continue
    local generated_bytes=${generated_marker#GENERATE_HEX_}
    local generated_value
    generated_value=$(openssl rand -hex "$generated_bytes")
    SECRET_VALUE="$generated_value" \
      yq -i ".$generated_path = strenv(SECRET_VALUE)" "$generated_file"
    generated_count=$((generated_count + 1))
  done < <(
    yq eval --no-doc -r '
      .. | select(tag == "!!str" and test("^GENERATE_HEX_(32|64)$")) |
      [(path | join(".")), .] | @tsv
    ' "$generated_file"
  )

  set_derived_value() {
    local path=$1
    local derived=$2
    SECRET_VALUE="$derived" yq -i ".$path = strenv(SECRET_VALUE)" "$generated_file"
    derived_count=$((derived_count + 1))
  }

  cluster_domain=$(yq -r '.clusterDomain' "$merged_config")
  postgres_port=$(yq -r '.postgresql.external.port' "$merged_config")
  cortex_user=$(yq -r '.cortex.bundled.username' "$merged_config")
  cortex_database=$(yq -r '.cortex.bundled.database' "$merged_config")
  clickhouse_user=$(yq -r '.clickhouse.bundled.username' "$merged_config")
  clickhouse_database=$(yq -r '.clickhouse.bundled.database' "$merged_config")

  local postgres_superuser_password
  local cortex_password
  local clickhouse_password
  local workflow_engine_token
  postgres_superuser_password=$(yq -r '.secrets.postgresql.superuserPassword' "$generated_file")
  cortex_password=$(yq -r '.secrets.cortex.password' "$generated_file")
  clickhouse_password=$(yq -r '.secrets.clickhouse.password' "$generated_file")
  workflow_engine_token=$(yq -r '.secrets.application.workflowEngineToken' "$generated_file")

  set_derived_value secrets.postgresql.adminUrl \
    "postgresql://postgres:${postgres_superuser_password}@postgresql-postgresql:${postgres_port}/postgres?sslmode=disable&connect_timeout=10"
  set_derived_value secrets.redis.url \
    "redis://redis-client.${namespace}.svc.${cluster_domain}:6379/1"
  set_derived_value secrets.cortex.url \
    "postgresql://${cortex_user}:${cortex_password}@cortex-postgresql.${namespace}.svc.${cluster_domain}:5432/${cortex_database}?sslmode=disable"
  set_derived_value secrets.clickhouse.url \
    "http://${clickhouse_user}:${clickhouse_password}@clickhouse:8123/${clickhouse_database}"

  local internal_service_tokens
  internal_service_tokens=$(yq -r '.secrets.application.internalServiceTokens // ""' "$generated_file")
  if [[ -z "$internal_service_tokens" || \
        "$internal_service_tokens" == CHANGE_ME_* || \
        "$internal_service_tokens" == DERIVE_INTERNAL_SERVICE_TOKENS ]]; then
    internal_service_tokens=$(printf \
      '[{"identity":"phoenix-gateway","token":"%s","scopes":["workflow:artifacts:read","workflow:context:read","workflow:events:write"],"tenant_ids":[],"app_slugs":[]}]' \
      "$workflow_engine_token")
    set_derived_value secrets.application.internalServiceTokens "$internal_service_tokens"
  fi

  chmod 600 "$generated_file"
  mv "$generated_file" "$selected_secrets"
  generated_file=""
  chmod 600 "$selected_secrets"
  rm -f "$merged_config"
  merged_config=""

  echo "Internal secret generation completed."
  echo "Generated values: $generated_count"
  echo "Derived values refreshed: $derived_count"
  echo "Secret values were not printed."
)

if [[ "$generate_secrets" == "true" ]]; then
  generate_internal_secrets "$requested_namespace" "$values_file" "$secrets_file"
fi

export PHOENIX_BYOC_NAMESPACE="$requested_namespace"
export PHOENIX_BYOC_VALUES_FILE="$values_file"
export PHOENIX_BYOC_SECRETS_FILE="$secrets_file"

context=$(kubectl config current-context)

"$repo_root/scripts/preflight.sh"
"$repo_root/scripts/render.sh"

namespace=$requested_namespace
release_version=$(awk '$1 == "version:" {gsub(/"/, "", $2); print $2; exit}' \
  "$repo_root/release.yaml")
pull_secrets=$(awk '
  /^imagePullSecrets:/ { in_secrets=1; next }
  in_secrets && /^[^ ]/ { exit }
  in_secrets && $1 == "-" && $2 == "name:" {
    gsub(/"/, "", $3)
    print $3
  }
' "$values_file")

echo
echo "Installing or upgrading Phoenix $release_version."
echo "Context:     $context"
echo "Namespace:   $namespace"
echo "Values:      $values_file"
echo "Secrets:     $secrets_file"
echo "Rendered:    $repo_root/.rendered/all.yaml"

cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"

(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" helmfile sync
)

# OpenSandbox creates runtime Pods after Helm installation. Linking the same
# pull secrets to the namespace default ServiceAccount lets those dynamic Pods
# pull from the configured registry. This runs after Helmfile so the optional
# ECR refresh release can create and populate its managed pull Secret first.
if [[ -n "$pull_secrets" ]]; then
  service_account_manifest=$(mktemp)
  trap 'rm -f "$service_account_manifest"' EXIT
  {
    echo "apiVersion: v1"
    echo "kind: ServiceAccount"
    echo "metadata:"
    echo "  name: default"
    echo "  namespace: $namespace"
    echo "imagePullSecrets:"
    while IFS= read -r secret_name; do
      echo "  - name: $secret_name"
    done <<<"$pull_secrets"
  } >"$service_account_manifest"
  kubectl apply -f "$service_account_manifest"
fi

"$repo_root/scripts/verify.sh" \
  --namespace "$namespace" \
  --values "$values_file" \
  --secrets "$secrets_file"
