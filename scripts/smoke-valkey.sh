#!/usr/bin/env bash
set -euo pipefail

# Run test.sh first. This uses its real chart render, not a hand-written config.
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
manifest="$repo_root/.rendered/test-bundled/all.yaml"
scratch=$(mktemp -d)
name="phoenix-byoc-valkey-smoke-$$"
subscriber=""
cleanup() {
  [[ -z "$subscriber" ]] || kill "$subscriber" 2>/dev/null || true
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker volume rm "$name" >/dev/null 2>&1 || true
  rm -rf "$scratch"
}
trap cleanup EXIT
"$repo_root/scripts/test-cache.sh"
image=$(yq eval --no-doc -r 'select(.kind == "StatefulSet" and .metadata.name == "valkey") | .spec.template.spec.containers[0].image' "$manifest")
cache_uid=$(yq eval --no-doc -r 'select(.kind == "StatefulSet" and .metadata.name == "valkey") | .spec.template.spec.containers[0].securityContext.runAsUser' "$manifest")
cache_gid=$(yq eval --no-doc -r 'select(.kind == "StatefulSet" and .metadata.name == "valkey") | .spec.template.spec.securityContext.fsGroup' "$manifest")
yq eval --no-doc -r 'select(.kind == "ConfigMap" and .metadata.name == "valkey-config") | .data."redis-standalone.conf"' "$manifest" >"$scratch/redis.conf"
[[ -s "$scratch/redis.conf" && "$cache_uid" != null && "$cache_gid" != null ]]
docker pull "$image" >/dev/null
docker volume create "$name" >/dev/null
docker run --rm --user 0 -v "$name:/data" --entrypoint sh "$image" \
  -ec "chown $cache_uid:$cache_gid /data"
docker run -d --name "$name" --user "$cache_uid:$cache_gid" \
  -v "$name:/data" -v "$scratch/redis.conf:/etc/redis/redis.conf:ro" \
  --entrypoint redis-server "$image" /etc/redis/redis.conf >/dev/null

cli() { docker exec "$name" redis-cli --raw "$@" | tr -d '\r'; }
ready() {
  for _ in {1..30}; do
    if [[ "$(cli PING 2>/dev/null)" == PONG ]]; then return; fi
    sleep 1
  done
  docker logs "$name" >&2
  echo "ERROR: Valkey did not become ready" >&2
  return 1
}
ready
expected_version=$(yq -r '.images.valkey.tag' "$repo_root/release.yaml")
cli INFO server | grep -Fx "valkey_version:$expected_version"
docker exec "$name" redis-cli --json MODULE LIST | "$repo_root/scripts/check-cache-modules.sh"
[[ "$(cli EVAL "return redis.call('PING')" 0)" == PONG ]]

# Execute all three chart probes verbatim, using the same shell and binaries.
for probe in startupProbe readinessProbe livenessProbe; do
  export CACHE_PROBE="$probe"
  probe_command=$(yq eval --no-doc -r 'select(.kind == "StatefulSet" and .metadata.name == "valkey") | .spec.template.spec.containers[0][strenv(CACHE_PROBE)].exec.command[2]' "$manifest")
  [[ "$(docker exec "$name" sh -ec "$probe_command" | tr -d '\r')" == PONG ]]
done

# Redis protocol operations used by Web/realtime and packaged lab workflows.
[[ "$(cli -n 1 SET byoc-smoke:expiry value EX 2)" == OK ]]
[[ "$(cli -n 14 HSET byoc-smoke:hash field value)" == 1 ]]
[[ "$(cli -n 14 EXPIRE byoc-smoke:hash 300)" == 1 ]]
docker exec "$name" redis-cli -n 1 --raw SUBSCRIBE byoc-smoke:channel >"$scratch/subscriber.log" &
subscriber=$!
for _ in {1..30}; do
  if grep -q byoc-smoke:channel "$scratch/subscriber.log"; then break; fi
  sleep 1
done
[[ "$(cli -n 1 PUBLISH byoc-smoke:channel byoc-smoke-message)" == 1 ]]
for _ in {1..30}; do
  if grep -q byoc-smoke-message "$scratch/subscriber.log"; then break; fi
  sleep 1
done
grep -q byoc-smoke-message "$scratch/subscriber.log"
kill "$subscriber" 2>/dev/null || true
wait "$subscriber" 2>/dev/null || true
subscriber=""
sleep 3
[[ "$(cli -n 1 EXISTS byoc-smoke:expiry)" == 0 ]]
docker restart "$name" >/dev/null
ready
[[ "$(cli -n 14 HGET byoc-smoke:hash field)" == value ]]
[[ "$(cli -n 14 TTL byoc-smoke:hash)" -gt 0 ]]
cli INFO persistence | grep -Fx aof_enabled:1
cli INFO persistence | grep -Fx aof_last_write_status:ok
echo "Valkey chart smoke passed: probes, Pub/Sub, expiry, DB 14 hashes and persisted restart."
