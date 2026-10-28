#!/usr/bin/env bash
# shellcheck disable=SC2329 # Exported kubectl guard is invoked by child scripts.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
devops_charts="${PHOENIX_BYOC_LOCAL_CHARTS:-$repo_root/../phoenix-devops/charts}"
cache_dir="${HELMFILE_CACHE_HOME:-$repo_root/.tmp/helmfile-cache}"
eval_tmp=$(mktemp -d)
trap 'rm -rf "$eval_tmp"' EXIT

python3 -m unittest discover -s "$repo_root/tests" -p test_evals.py -v
for scenario in bundled external private-registry direct-ecr; do
  python3 "$repo_root/tests/check_eval_render.py" "$repo_root/.rendered/test-$scenario/all.yaml"
done

# Exercise the actual Helmfile fallback, then an old customer's saved inputs.
# These are synthetic fixture credentials; no cluster access is made.
cp "$repo_root/tests/fixtures/values.yaml" "$eval_tmp/values.yaml"
cp "$repo_root/tests/fixtures/values.secrets.yaml" "$eval_tmp/secrets.yaml"
yq -i '.secrets.application.internalServiceTokens = ""' "$eval_tmp/secrets.yaml"
for scenario in fallback upgraded; do
  if [[ "$scenario" == upgraded ]]; then
    yq -i '
      .services.workflowEngine.operator.maxConcurrentSandboxTasksEval = 5 |
      .services.workflowEngine.operator.maxConcurrentInProcessTasksEval = 5
    ' "$eval_tmp/values.yaml"
    cp "$repo_root/tests/fixtures/values.secrets.yaml" "$eval_tmp/secrets.yaml"
    yq -i '.secrets.application.internalServiceTokens |=
      (from_json | map(.scopes |= map(select(. != "workflow:evals:read" and . != "workflow:evals:write"))) | to_json)
    ' "$eval_tmp/secrets.yaml"
    kubectl() { echo 'Unexpected cluster access in eval validation' >&2; return 97; }
    export -f kubectl
    for invalid in scopes partial-capacity; do
      expected='workflow:evals:read'
      if [[ "$invalid" == partial-capacity ]]; then
        yq -i '.services.workflowEngine.operator.maxConcurrentSandboxTasksEval = 0' "$eval_tmp/values.yaml"
        expected='enable both eval queues'
      fi
      if PHOENIX_BYOC_NAMESPACE=phoenix-eval-test \
         PHOENIX_BYOC_VALUES_FILE="$eval_tmp/values.yaml" \
         PHOENIX_BYOC_SECRETS_FILE="$eval_tmp/secrets.yaml" \
         "$repo_root/scripts/preflight.sh" >"$eval_tmp/preflight.log" 2>&1; then
        echo "ERROR: preflight accepted invalid eval $invalid" >&2
        exit 1
      fi
      grep -q "$expected" "$eval_tmp/preflight.log"
      if grep -q 'Unexpected cluster access' "$eval_tmp/preflight.log"; then
        echo "ERROR: eval validation did not run before cluster access" >&2
        exit 1
      fi
    done
    unset -f kubectl
    yq -i '.services.workflowEngine.operator.maxConcurrentInProcessTasksEval = 0' "$eval_tmp/values.yaml"
    python3 "$repo_root/scripts/eval-config.py" enable \
      --values "$eval_tmp/values.yaml" --secrets "$eval_tmp/secrets.yaml"
  fi
  (
    cd "$repo_root"
    HELMFILE_CACHE_HOME="$cache_dir" \
      PHOENIX_BYOC_LOCAL_CHARTS="$devops_charts" \
      PHOENIX_BYOC_VALUES_FILE="$eval_tmp/values.yaml" \
      PHOENIX_BYOC_SECRETS_FILE="$eval_tmp/secrets.yaml" \
      PHOENIX_BYOC_NAMESPACE=phoenix-eval-test \
      helmfile template --skip-deps --quiet >"$eval_tmp/rendered.yaml"
  )
  python3 "$repo_root/tests/check_eval_render.py" "$eval_tmp/rendered.yaml"
done
echo "Eval default, permission and upgrade render tests passed."
