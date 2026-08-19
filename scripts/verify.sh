#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: ./scripts/verify.sh --namespace <name> --values <path> --secrets <path>" >&2
}

namespace=""
values_path=""
secrets_path=""
while (($# > 0)); do
  case "$1" in
    --namespace)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "ERROR: --namespace requires a value." >&2
        exit 2
      fi
      namespace=$2
      shift 2
      ;;
    --values)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "ERROR: --values requires a path." >&2
        exit 2
      fi
      values_path=$2
      shift 2
      ;;
    --secrets)
      if (($# < 2)) || [[ -z "$2" ]]; then
        echo "ERROR: --secrets requires a path." >&2
        exit 2
      fi
      secrets_path=$2
      shift 2
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$namespace" || -z "$values_path" || -z "$secrets_path" ]]; then
  usage
  exit 2
fi

export PHOENIX_BYOC_NAMESPACE="$namespace"
export PHOENIX_BYOC_VALUES_FILE="$values_path"
export PHOENIX_BYOC_SECRETS_FILE="$secrets_path"

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"
values_file=$values_path
secrets_file=$secrets_path
if [[ "$values_file" != /* ]]; then
  values_file="$repo_root/$values_file"
fi
if [[ "$secrets_file" != /* ]]; then
  secrets_file="$repo_root/$secrets_file"
fi

for file in "$values_file" "$secrets_file"; do
  if [[ ! -f "$file" ]]; then
    echo "ERROR: configuration file does not exist: $file" >&2
    exit 1
  fi
done

merged_file=$(mktemp)
trap 'rm -f "$merged_file"' EXIT
chmod 600 "$merged_file"
# shellcheck disable=SC2016 # $item is a yq variable, not a shell variable.
yq eval-all '. as $item ireduce ({}; . * $item)' \
  "$repo_root/release.yaml" \
  "$repo_root/defaults/values.yaml" \
  "$values_file" \
  "$secrets_file" >"$merged_file"

ecr_refresh_enabled=$(yq -r '.registry.ecrRefresh.enabled' "$merged_file")
ecr_pull_secret=$(yq -r '.registry.ecrRefresh.pullSecretName' "$merged_file")
bundled_clickhouse=$(yq -r '.clickhouse.bundled.enabled' "$merged_file")
bundled_postgresql=$(yq -r '.postgresql.bundled.enabled' "$merged_file")
bundled_redis=$(yq -r '.redis.bundled.enabled' "$merged_file")
bundled_cortex=$(yq -r '.cortex.bundled.enabled' "$merged_file")
bundled_ingress=$(yq -r '.ingressNginx.enabled' "$merged_file")
ingress_namespace=$(yq -r '.ingressNginx.namespace // .namespace' "$merged_file")
opensandbox_controller=$(yq -r '.opensandboxController.enabled' "$merged_file")
postgresql_bootstrap=$(yq -r '.postgresql.hooks.phoenixWeb' "$merged_file")
rendered_file="$repo_root/.rendered/all.yaml"

"$repo_root/scripts/render.sh"

local_chart_version() {
  awk '$1 == "version:" {gsub(/"/, "", $2); print $2; exit}' \
    "$repo_root/charts/$1/Chart.yaml"
}

check_helm_release() {
  local release_name=$1
  local release_namespace=$2
  local expected_chart=$3
  local expected_version=$4
  local enabled=$5
  local metadata
  local actual_status
  local actual_chart
  local actual_version

  if [[ "$enabled" != "true" ]]; then
    return
  fi

  if ! metadata=$(helm get metadata "$release_name" \
      --namespace "$release_namespace" --output json 2>/dev/null); then
    echo "ERROR: enabled Helm release is missing: $release_namespace/$release_name" >&2
    exit 1
  fi

  actual_status=$(yq -r '.status // ""' <<<"$metadata")
  actual_chart=$(yq -r '.chart // ""' <<<"$metadata")
  actual_version=$(yq -r '.version // ""' <<<"$metadata")

  if [[ "$actual_status" != "deployed" ]]; then
    echo "ERROR: Helm release $release_namespace/$release_name has status '$actual_status', expected 'deployed'." >&2
    exit 1
  fi
  if [[ "$actual_chart" != "$expected_chart" || "$actual_version" != "$expected_version" ]]; then
    echo "ERROR: Helm release $release_namespace/$release_name uses $actual_chart@$actual_version;" >&2
    echo "       expected $expected_chart@$expected_version from release.yaml." >&2
    exit 1
  fi
}

check_helm_release ecr-pull-secret-refresh "$namespace" ecr-pull-secret-refresh \
  "$(local_chart_version ecr-pull-secret-refresh)" "$ecr_refresh_enabled"
check_helm_release ingress-nginx "$ingress_namespace" ingress-nginx \
  "$(yq -r '.versions.ingressNginx' "$merged_file")" "$bundled_ingress"
check_helm_release postgresql "$namespace" postgresql \
  "$(yq -r '.versions.postgresql' "$merged_file")" "$bundled_postgresql"
check_helm_release redis "$namespace" redis \
  "$(yq -r '.versions.redis' "$merged_file")" "$bundled_redis"
check_helm_release postgresql-bootstrap "$namespace" postgresql-bootstrap \
  "$(yq -r '.versions.postgresqlBootstrap' "$merged_file")" "$postgresql_bootstrap"
check_helm_release cortex-postgresql "$namespace" cortex-postgresql \
  "$(yq -r '.versions.cortexPostgresql' "$merged_file")" "$bundled_cortex"
check_helm_release clickhouse "$namespace" clickhouse \
  "$(yq -r '.versions.clickhouseChart' "$merged_file")" true
check_helm_release opensandbox-controller "$namespace" opensandbox-controller \
  "$(yq -r '.versions.opensandboxController' "$merged_file")" "$opensandbox_controller"
check_helm_release phoenix-web "$namespace" phoenix-web \
  "$(yq -r '.versions.phoenixWeb' "$merged_file")" true
check_helm_release phoenix-web-frontend "$namespace" phoenix-web-frontend \
  "$(yq -r '.versions.phoenixWebFrontend' "$merged_file")" true
check_helm_release phoenix-gateway "$namespace" phoenix-gateway \
  "$(yq -r '.versions.phoenixGateway' "$merged_file")" true
check_helm_release phoenix-workflow-engine "$namespace" phoenix-workflow-engine \
  "$(yq -r '.versions.phoenixWorkflowEngine' "$merged_file")" true

(
  cd "$repo_root"
  HELMFILE_CACHE_HOME="$cache_dir" helmfile status
)

kubectl -n "$namespace" wait \
  --for=condition=Available deployment --all --timeout=600s

while IFS= read -r statefulset; do
  [[ -z "$statefulset" ]] && continue
  kubectl -n "$namespace" rollout status "$statefulset" --timeout=600s
done < <(kubectl -n "$namespace" get statefulsets -o name)

kubectl -n "$namespace" get pods,services,persistentvolumeclaims

verify_dir=$(mktemp -d)
trap 'rm -f "$merged_file"; rm -rf "$verify_dir"' EXIT

while IFS=$'\t' read -r workload_kind workload_namespace workload_name; do
  [[ -z "$workload_kind" ]] && continue
  if [[ -z "$workload_namespace" || "$workload_namespace" == "null" ]]; then
    workload_namespace=$namespace
  fi

  live_file="$verify_dir/${workload_kind}-${workload_namespace}-${workload_name}.json"
  if ! kubectl -n "$workload_namespace" get "$workload_kind/$workload_name" \
      --output json >"$live_file"; then
    echo "ERROR: rendered workload is missing: $workload_namespace/$workload_kind/$workload_name" >&2
    exit 1
  fi

  for container_path in containers initContainers; do
    while IFS=$'\t' read -r container_name expected_image; do
      [[ -z "$container_name" ]] && continue
      export CONTAINER_NAME="$container_name"
      actual_image=$(yq -r \
        ".spec.template.spec.${container_path}[]? | select(.name == strenv(CONTAINER_NAME)) | .image" \
        "$live_file")
      if [[ "$actual_image" != "$expected_image" ]]; then
        echo "ERROR: image mismatch for $workload_namespace/$workload_kind/$workload_name" >&2
        echo "       $container_path/$container_name uses '$actual_image'; expected '$expected_image'." >&2
        exit 1
      fi
    done < <(
      export WORKLOAD_KIND="$workload_kind"
      export WORKLOAD_NAMESPACE="$workload_namespace"
      export WORKLOAD_NAME="$workload_name"
      export CONTAINER_PATH="$container_path"
      yq eval --no-doc -r '
        select(
          .kind == strenv(WORKLOAD_KIND) and
          (.metadata.namespace // strenv(PHOENIX_BYOC_NAMESPACE)) == strenv(WORKLOAD_NAMESPACE) and
          .metadata.name == strenv(WORKLOAD_NAME)
        ) |
        .spec.template.spec[strenv(CONTAINER_PATH)][]? |
        [.name, .image] | @tsv
      ' "$rendered_file"
    )
  done
done < <(
  yq eval --no-doc -r '
    select(.kind == "Deployment" or .kind == "StatefulSet") |
    [.kind, (.metadata.namespace // strenv(PHOENIX_BYOC_NAMESPACE)), .metadata.name] |
    @tsv
  ' "$rendered_file"
)

if [[ "$bundled_clickhouse" == "true" ]]; then
  kubectl -n "$namespace" get service/clickhouse statefulset/clickhouse
fi

if [[ "$ecr_refresh_enabled" == "true" ]]; then
  kubectl -n "$namespace" get cronjob/ecr-pull-secret-refresh
  pull_secret_type=$(kubectl -n "$namespace" get secret "$ecr_pull_secret" \
    -o jsonpath='{.type}')
  if [[ "$pull_secret_type" != "kubernetes.io/dockerconfigjson" ]]; then
    echo "ERROR: managed ECR pull Secret has unexpected type: $pull_secret_type" >&2
    exit 1
  fi
  echo "ECR pull Secret refresh is enabled for '$ecr_pull_secret'."
fi

echo "Phoenix verification passed in namespace $namespace."
