#!/usr/bin/env bash
# shellcheck disable=SC2329 # Exported mocks are invoked by child scripts.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
expected=$(yq -r '.images.valkey | .repository + ":" + .tag + "@" + .digest' "$repo_root/release.yaml")
export EXPECTED_CACHE_IMAGE="$expected"

for scenario in bundled private-registry direct-ecr external; do
  manifest="$repo_root/.rendered/test-$scenario/all.yaml"
  if grep -Eq 'image:.*(^|/)redis:8\.' "$manifest"; then
    echo "ERROR: Redis 8 image remains in $scenario manifest" >&2
    exit 1
  fi
  if [[ "$scenario" == external ]]; then
    [[ -z "$(yq eval --no-doc 'select(.kind == "StatefulSet" and .metadata.name == "valkey") | .metadata.name' "$manifest")" ]]
    continue
  fi
  if [[ "$scenario" == private-registry ]]; then
    EXPECTED_CACHE_IMAGE="registry.test.invalid/phoenix/valkey:$(yq -r '.images.valkey | .tag + "@" + .digest' "$repo_root/release.yaml")"
  else
    export EXPECTED_CACHE_IMAGE="$expected"
  fi
  yq eval --exit-status '
    select(.kind == "StatefulSet" and .metadata.name == "valkey") |
    .spec.template.spec.containers[0] |
    (.image == strenv(EXPECTED_CACHE_IMAGE) and
    (.command | join(" ")) == "redis-server" and
    (.args | join(" ")) == "/etc/redis/redis.conf" and
    (.readinessProbe.exec.command | join(" ")) == "sh -ec redis-cli ping" and
    (.livenessProbe.exec.command | join(" ")) == "sh -ec redis-cli ping" and
    (.startupProbe.exec.command | join(" ")) == "sh -ec redis-cli ping")
  ' "$manifest" >/dev/null
  yq eval --exit-status '
    select(.kind == "Service" and .metadata.name == "redis-client") |
    (.spec.selector."app.kubernetes.io/name" == "valkey" and
    .spec.ports[0].port == 6379 and .spec.ports[0].targetPort == "redis")
  ' "$manifest" >/dev/null
  for label in name instance component role; do
    export CACHE_LABEL="app.kubernetes.io/$label"
    service_label=$(yq eval --no-doc -r 'select(.kind == "Service" and .metadata.name == "redis-client") | .spec.selector[strenv(CACHE_LABEL)]' "$manifest")
    pod_label=$(yq eval --no-doc -r 'select(.kind == "StatefulSet" and .metadata.name == "valkey") | .spec.template.metadata.labels[strenv(CACHE_LABEL)]' "$manifest")
    [[ "$service_label" != null && "$service_label" == "$pod_label" ]]
  done
done

# No real cluster writes: verify that an upgrade cannot silently discard Redis.
kubectl() {
  case "$*" in
    *'get statefulset redis '*) [[ "$CACHE_TEST_STATE" != legacy ]] || echo statefulset.apps/redis ;;
    *'get pvc data-redis-0 '*) [[ "$CACHE_TEST_STATE" == fresh ]] || echo persistentvolumeclaim/data-redis-0 ;;
    *'get statefulset valkey '*) [[ "$CACHE_TEST_STATE" != migrated ]] || echo statefulset.apps/valkey ;;
    *) echo "Unexpected kubectl call: $*" >&2; return 1 ;;
  esac
  return 0
}
export -f kubectl
for state in legacy orphan fresh migrated; do
  export CACHE_TEST_STATE="$state"
  if "$repo_root/scripts/check-cache-upgrade.sh" test "$repo_root/.rendered/test-bundled/all.yaml" >/dev/null 2>&1; then
    [[ "$state" == fresh || "$state" == migrated ]]
  else
    [[ "$state" == legacy || "$state" == orphan ]]
  fi
done
unset -f kubectl

mirror_plan=$("$repo_root/scripts/images.sh" mirror --to registry.test.invalid/phoenix --dry-run)
grep -Fq "$expected registry.test.invalid/phoenix/valkey:$(yq -r '.images.valkey.tag' "$repo_root/release.yaml")" <<<"$mirror_plan"

# Resolving a mirror tag successfully is insufficient: its digest must match.
crane() { echo sha256:incorrect; }
export -f crane
if "$repo_root/scripts/images.sh" verify --registry registry.test.invalid/phoenix >/dev/null 2>&1; then
  echo "ERROR: image verification accepted a mismatched digest" >&2
  exit 1
fi
unset -f crane
printf '%s\n' '[]' | "$repo_root/scripts/check-cache-modules.sh"
printf '%s\n' '[{"name":"lua","ver":1,"path":"lua","args":[]}]' |
  "$repo_root/scripts/check-cache-modules.sh"
for modules in \
  '[{"name":"search","ver":1,"path":"/redisearch.so","args":[]}]' \
  '[{"name":"lua","ver":1,"path":"/custom/lua.so","args":[]}]'; do
  if printf '%s\n' "$modules" | "$repo_root/scripts/check-cache-modules.sh" >/dev/null 2>&1; then
    echo "ERROR: module allowlist accepted an external module" >&2
    exit 1
  fi
done
echo "Valkey render, upgrade guard and mirror tests passed."
