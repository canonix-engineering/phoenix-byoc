#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
cp "$repo_root/tests/fixtures/values.yaml" "$test_dir/values.yaml"
cp "$repo_root/tests/fixtures/values.secrets.yaml" "$test_dir/secrets.yaml"
export PHOENIX_BYOC_VALUES_FILE="$test_dir/values.yaml"
export PHOENIX_BYOC_SECRETS_FILE="$test_dir/secrets.yaml"
export PHOENIX_BYOC_NAMESPACE=phoenix
export PHOENIX_BYOC_LOCAL_CHARTS="${PHOENIX_BYOC_LOCAL_CHARTS:-$repo_root/../phoenix-devops/charts}"
export HELMFILE_CACHE_HOME="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"
yq -i '.services.opensandbox.fuse.enabled = true' "$test_dir/values.yaml"
# An enabled FUSE setting must not silently disappear into the older pinned chart.
if (cd "$repo_root" && helmfile template --skip-deps --quiet >"$test_dir/old.yaml" 2>"$test_dir/old.log"); then
  echo "ERROR: AgentFS accepted the older Engine chart." >&2
  exit 1
fi
grep -q 'AgentFS requires phoenixWorkflowEngine chart' "$test_dir/old.log" || { cat "$test_dir/old.log" >&2; exit 1; }
yq -i '
  .versions.phoenixWorkflowEngine = "0.2.6" |
  .services.opensandbox.fuse.retainedImages = ["registry.example/agent:old-a"] |
  .fuseDevicePlugin.nodeSelector.pool = "customer-sandbox"
' "$test_dir/values.yaml"
export PHOENIX_AGENTFS_RETAINED_IMAGES_JSON='["registry.example/agent:old-b", "registry.example/agent:old-a"]'
(cd "$repo_root" && helmfile template --skip-deps --quiet >"$test_dir/managed.yaml")
yq -e 'select(.kind == "Deployment" and .metadata.name == "phoenix-workflow-engine-opensandbox") |
  .spec.template.spec.containers[] | select(.name == "opensandbox") | .env[] |
  select(.name == "PHOENIX_OPENSANDBOX_FUSE_IMAGES_JSON") | .value | from_json |
  ((length == 3) and contains(["registry.example/agent:old-a", "registry.example/agent:old-b"]))' "$test_dir/managed.yaml" >/dev/null
yq -e 'select(.kind == "DaemonSet" and .metadata.name == "fuse-device-plugin") |
  .spec.template.spec |
  (.nodeSelector.pool == "customer-sandbox" and
  .nodeSelector."kubernetes.io/os" == "linux" and
  .automountServiceAccountToken == false and
  .containers[0].securityContext.privileged == true and
  (.volumes | length == 2))' "$test_dir/managed.yaml" >/dev/null
# The exact infrastructure image is part of the mirror inventory.
plugin_image=$("$repo_root/scripts/images.sh" list | grep 'squat/generic-device-plugin:')
grep -Fq "$plugin_image" "$test_dir/managed.yaml"
# Reuse must omit the release entirely, not set installed:false (which uninstalls).
yq -i '.fuseDevicePlugin.install = false | .imageRegistry = "registry.customer.example/phoenix"' "$test_dir/values.yaml"
(cd "$repo_root" && helmfile template --skip-deps --quiet >"$test_dir/reuse.yaml")
if grep -q 'kind: DaemonSet' "$test_dir/reuse.yaml"; then
  echo "ERROR: reuse mode rendered a node plugin." >&2
  exit 1
fi
yq -e 'select(.kind == "Deployment" and .metadata.name == "phoenix-workflow-engine-opensandbox") |
  .spec.template.spec.containers[] | select(.name == "opensandbox") | .env[] |
  select(.name == "PHOENIX_OPENSANDBOX_FUSE_IMAGES_JSON") | .value | from_json |
  .[0] | test("^registry.customer.example/phoenix/phoenix-agent:.*@sha256:")' "$test_dir/reuse.yaml" >/dev/null
python3 -m unittest discover -s "$repo_root/tests" -p test_agentfs.py -v
echo "AgentFS render, mirror, reuse and upgrade-guard tests passed."
