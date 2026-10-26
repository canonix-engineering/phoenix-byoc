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
yq -i '
  .postgresql.hooks.phoenixWeb = true |
  .application.agentBundles.namespace = "agent-bundles" |
  .application.agentBundles.globalPublisherUserIds = ["test-publisher"] |
  .services.workflowEngine.operator.sandboxAdmissionLimit = 6 |
  .services.workflowEngine.operator.evalResultDetailEnabled = true |
  .services.workflowEngine.operator.serviceAccountAnnotations."iam.gke.io/gcp-service-account" = "operator@customer.iam.gserviceaccount.com" |
  .services.opensandbox.costLimitCheckIntervalSeconds = 45 |
  .services.opensandbox.scheduling.nodeSelector.pool = "customer-sandbox" |
  .ingress.gateway.enabled = true
' "$test_dir/values.yaml"
yq -i '.secrets.application.artifactPublisherToken = "test-only-publisher"' "$test_dir/secrets.yaml"
(
  cd "$repo_root"
  helmfile template --skip-deps --quiet >"$test_dir/rendered.yaml"
)

# Check the complete values -> templates -> Kubernetes wiring, including the
# existing Web chart's secretKeyRef support. Never print rendered credentials.
yq -e 'select(.kind == "Deployment" and .metadata.name == "phoenix-web") |
  .spec.template.spec.containers[0].env[] |
  select(.name == "PHOENIX_ARTIFACT_PUBLISHER_TOKEN") |
  .valueFrom.secretKeyRef.name == "phoenix-artifact-publisher"' "$test_dir/rendered.yaml" >/dev/null
yq -e 'select(.kind == "Deployment" and .metadata.name == "phoenix-web-worker") |
  .spec.template.spec.containers[0].env[] |
  select(.name == "PHOENIX_ARTIFACT_PUBLISHER_TOKEN") |
  .valueFrom.secretKeyRef.key == "token"' "$test_dir/rendered.yaml" >/dev/null
publisher=$(yq -r 'select(.kind == "Secret" and .metadata.name == "phoenix-artifact-publisher") | .data.token' "$test_dir/rendered.yaml")
engine=$(yq -r 'select(.kind == "Secret" and .metadata.name == "phoenix-workflow-engine") | .data.PHOENIX_ARTIFACT_PUBLISHER_TOKEN' "$test_dir/rendered.yaml")
[[ -n "$publisher" && "$publisher" == "$engine" ]]
unset publisher engine
yq -e 'select(.kind == "ConfigMap" and .metadata.name == "phoenix-workflow-engine") |
  (.data.PHOENIX_ARTIFACT_STANDALONE_ENABLED // "true") == "true" and
  .data.PHOENIX_ARTIFACT_KEY_DELEGATOR_NAMESPACES == "agent-bundles" and
  .data.OPERATOR_SANDBOX_ADMISSION_LIMIT == "6" and
  .data.OPERATOR_EVAL_RESULT_DETAIL_ENABLED == "true" and
  .data.PHOENIX_COST_LIMIT_CHECK_INTERVAL_SECONDS == "45"' "$test_dir/rendered.yaml" >/dev/null
yq -e 'select(.kind == "Ingress" and .metadata.name == "phoenix-gateway") |
  [.spec.rules[].http.paths[].path] | contains(["/mcp/v1/toolboxes/", "/v1/remote-ssh/connect"])' "$test_dir/rendered.yaml" >/dev/null
if yq -e 'select(.kind == "Ingress" and .metadata.name == "phoenix-gateway") |
  .spec.rules[].http.paths[] | select(.path == "/")' "$test_dir/rendered.yaml" >/dev/null 2>&1; then
  echo "ERROR: Gateway exposes unrestricted routes." >&2
  exit 1
fi
grep -q 'operator@customer.iam.gserviceaccount.com' "$test_dir/rendered.yaml"
grep -q 'customer-sandbox' "$test_dir/rendered.yaml"
yq -e 'select(.kind == "Job" and .metadata.name == "phoenix-web-db-init") |
  .spec.template.spec.containers[0].args | join(",") == "db:create,db:migrate,apps:rematerialize"' "$test_dir/rendered.yaml" >/dev/null

# The migration jobs must receive incoming publisher values directly, before
# Helm updates the previous release's Secret/ConfigMap. This is the 0.2.1 upgrade
# case where those old objects may not contain publisher credentials at all.
for job in phoenix-web-db-init phoenix-workflow-engine-migrate; do
  export JOB_NAME="$job"
  token=$(yq -r 'select(.kind == "Job" and .metadata.name == strenv(JOB_NAME)) |
    .spec.template.spec.containers[0].env[] |
    select(.name == "PHOENIX_ARTIFACT_PUBLISHER_TOKEN") | .value' "$test_dir/rendered.yaml")
  [[ "$token" == "test-only-publisher" ]]
  unset token
  yq -e 'select(.kind == "Job" and .metadata.name == strenv(JOB_NAME)) |
    .spec.template.spec.containers[0].env[] |
    select(.name == "PHOENIX_ARTIFACT_PUBLISHER_NAMESPACE") |
    .value == "agent-bundles"' "$test_dir/rendered.yaml" >/dev/null
done
yq -e 'select(.kind == "Job" and .metadata.name == "phoenix-workflow-engine-migrate") |
  .metadata.annotations."helm.sh/hook" == "post-install,pre-upgrade"' "$test_dir/rendered.yaml" >/dev/null
for key in PHOENIX_ARTIFACT_TENANT_ID PHOENIX_ARTIFACT_KEY_DELEGATOR_NAMESPACES; do
  export ENV_NAME="$key"
  yq -e 'select(.kind == "Job" and .metadata.name == "phoenix-workflow-engine-migrate") |
    .spec.template.spec.containers[0].env[] |
    select(.name == strenv(ENV_NAME)) | .value != ""' "$test_dir/rendered.yaml" >/dev/null
done

# A misconfigured token must fail before any cluster interaction.
yq -i '.secrets.application.artifactPublisherToken = .secrets.application.workflowEngineToken' "$test_dir/secrets.yaml"
if "$repo_root/scripts/preflight.sh" >"$test_dir/preflight.log" 2>&1; then
  echo "ERROR: preflight accepted a publisher token shared with the engine." >&2
  exit 1
fi
grep -q 'artifactPublisherToken must differ' "$test_dir/preflight.log"
# Missing publisher credentials must fail even without any customer enable switch.
yq -i '.secrets.application.artifactPublisherToken = ""' "$test_dir/secrets.yaml"
if "$repo_root/scripts/preflight.sh" >"$test_dir/preflight.log" 2>&1; then
  echo "ERROR: preflight accepted missing publisher credentials." >&2
  exit 1
fi
grep -q 'secrets.application.artifactPublisherToken' "$test_dir/preflight.log"
yq -i '.secrets.application.artifactPublisherToken = "test-only-publisher"' "$test_dir/secrets.yaml"
yq -i '.application.agentBundles.namespace = "unsupported-namespace"' "$test_dir/values.yaml"
if "$repo_root/scripts/preflight.sh" >"$test_dir/preflight.log" 2>&1; then
  echo "ERROR: preflight accepted a namespace unsupported by Web and Agent." >&2
  exit 1
fi
grep -q 'require application.agentBundles.namespace=agent-bundles' "$test_dir/preflight.log"
echo "Release preparation wiring and preflight tests passed."
