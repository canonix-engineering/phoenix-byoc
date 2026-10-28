"""Assert the rendered operator and Web agree on eval enablement; never print secrets."""
import base64
import json
from pathlib import Path
import subprocess
import sys


def check(path):
    result = subprocess.run(["yq", "-o=json", "-I=0", ".", str(path)],
                            capture_output=True, text=True, check=True)
    resources = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    objects = {(item["kind"], item["metadata"]["name"]): item
               for item in resources if isinstance(item, dict)}
    operator = objects[("ConfigMap", "phoenix-workflow-engine")]["data"]
    for key in ("OPERATOR_MAX_CONCURRENT_SANDBOX_WORKFLOW_STEP_RUNS_EVAL",
                "OPERATOR_MAX_CONCURRENT_INPROCESS_WORKFLOW_STEP_RUNS_EVAL"):
        assert int(operator[key]) > 0, f"{key} disables eval execution"
    web = objects[("Secret", "phoenix-web")]["data"]
    gateway = objects[("Secret", "phoenix-gateway")]["data"]
    token = base64.b64decode(gateway["PHOENIX_WORKFLOW_ENGINE_TOKEN"]).decode()
    identities = json.loads(base64.b64decode(web["PHOENIX_INTERNAL_SERVICE_TOKENS"]))
    matches = [entry for entry in identities if entry["token"] == token]
    assert len(matches) == 1, "Rendered Gateway credential must match exactly one Web identity"
    assert {"workflow:evals:read", "workflow:evals:write"} <= set(matches[0]["scopes"]), \
        "Rendered Gateway credential lacks eval API permissions"


if __name__ == "__main__":
    for manifest in sys.argv[1:]:
        check(Path(manifest))
    print("Rendered eval capacities and Gateway permissions passed.")
