#!/usr/bin/env python3
"""Validate eval configuration, or explicitly enable it in saved BYOC inputs.

Uses the existing yq prerequisite; never contacts Kubernetes or prints secrets.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

CAPACITIES = ("maxConcurrentSandboxTasksEval", "maxConcurrentInProcessTasksEval")
SCOPES = ("workflow:evals:read", "workflow:evals:write")
OPERATOR = "services.workflowEngine.operator"


def capacities(operator):
    result = [operator.get(key, 5) for key in CAPACITIES]
    if any(type(value) is not int or value < 0 for value in result):
        raise ValueError(f"{OPERATOR}: eval capacities must be non-negative integers")
    return result


def gateway_entry(application):
    token = application.get("workflowEngineToken")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("secrets.application.workflowEngineToken must be non-empty")
    raw = application.get("internalServiceTokens", "")
    if not raw:
        return None, None  # Web's values template derives the service identity.
    try:
        entries = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("secrets.application.internalServiceTokens must be a JSON array") from None
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError("secrets.application.internalServiceTokens must be a JSON array of identities")
    matches = [entry for entry in entries if token and entry.get("token") == token]
    if (len(matches) != 1 or not isinstance(matches[0].get("identity"), str)
            or not matches[0]["identity"].strip()):
        raise ValueError("internalServiceTokens must contain exactly one identity matching workflowEngineToken")
    scopes = matches[0].get("scopes", [])
    if not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes):
        raise ValueError("Gateway service-token scopes must be an array of strings")
    return entries, matches[0]


def validate(config):
    operator = config.get("services", {}).get("workflowEngine", {}).get("operator", {})
    limits = capacities(operator)
    if limits == [0, 0]:
        return
    if 0 in limits:
        raise ValueError(f"{OPERATOR}: enable both eval queues, or set both capacities to 0 to disable evals")
    _, entry = gateway_entry(config.get("secrets", {}).get("application", {}))
    if entry is not None:
        missing = [scope for scope in SCOPES if scope not in entry.get("scopes", [])]
        if missing:
            raise ValueError("Gateway token is missing " + ", ".join(missing) +
                             "; run scripts/eval-config.py enable with your saved --values and --secrets files")


def read_yaml(path):
    result = subprocess.run(["yq", "-o=json", ".", str(path)], capture_output=True, text=True)
    if result.returncode:
        raise ValueError("Cannot read YAML input (parser details suppressed to protect secrets)")
    data = json.loads(result.stdout)
    if not isinstance(data, dict) or not data:
        raise ValueError("Inputs must be non-empty YAML mappings")
    return data


def stage_update(path, updates, mode):
    """Render only changed paths, retaining YAML comments and unrelated settings."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as patch:
        json.dump(updates, patch)
        patch.flush()
        expression = " | ".join(f'.{key} = load(strenv(PHOENIX_EVAL_PATCH))["{key}"]' for key in updates)
        env = dict(os.environ, PHOENIX_EVAL_PATCH=patch.name)
        result = subprocess.run(["yq", expression, str(path)], env=env, capture_output=True)
    if result.returncode:
        raise ValueError("Cannot update YAML input (parser details suppressed to protect secrets)")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(result.stdout)
        os.chmod(name, mode)
    except BaseException:
        os.unlink(name)
        raise
    return Path(name)


def enable(values_path, secrets_path):
    for path in (values_path, secrets_path):
        if path.is_symlink() or not path.is_file():
            raise ValueError("Input paths must be existing regular files, not symlinks")
    if os.path.samefile(values_path, secrets_path):
        raise ValueError("Values and secrets must be separate files")
    tracked = subprocess.run(["git", "-C", str(secrets_path.parent), "ls-files", "--error-unmatch",
                              "--", secrets_path.name], capture_output=True)
    if tracked.returncode == 0:
        raise ValueError("Refusing to update a Git-tracked secrets file")
    values, secrets = read_yaml(values_path), read_yaml(secrets_path)
    secret_operator = secrets.get("services", {}).get("workflowEngine", {}).get("operator", {})
    if any(key in secret_operator for key in CAPACITIES):
        raise ValueError("Move eval capacity overrides from the secrets file into the values file before enabling evals")
    operator = values.get("services", {}).get("workflowEngine", {}).get("operator", {})
    limits = capacities(operator)
    application = secrets.get("secrets", {}).get("application", {})
    token = application.get("workflowEngineToken")
    if not isinstance(token, str) or not token.strip() or token.startswith(("GENERATE_", "DERIVE_", "CHANGE_ME")):
        raise ValueError("Generate/populate workflowEngineToken before enabling evals")
    entries, entry = gateway_entry(application)
    value_updates = {f"{OPERATOR}.{key}": limit or 5 for key, limit in zip(CAPACITIES, limits)
                     if key not in operator or limit == 0}
    secret_updates = {}
    if entry is not None:
        missing = [scope for scope in SCOPES if scope not in entry.get("scopes", [])]
        if missing:
            entry.setdefault("scopes", []).extend(missing)
            secret_updates["secrets.application.internalServiceTokens"] = json.dumps(entries)
    staged = []
    try:
        # Prepare both files before replacing either. Credentials go first, so an
        # interrupted migration never enables workers with old permissions.
        if secret_updates:
            staged.append((stage_update(secrets_path, secret_updates, 0o600), secrets_path))
        if value_updates:
            staged.append((stage_update(values_path, value_updates, values_path.stat().st_mode & 0o777), values_path))
        os.chmod(secrets_path, 0o600)
        for temporary, destination in staged:
            os.replace(temporary, destination)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    print("Eval settings saved. Existing tokens, positive capacities and identity restrictions preserved.")
    print("No cluster changes made. Use these same files for the next BYOC install/upgrade.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="validate merged JSON configuration from stdin")
    migration = commands.add_parser("enable", help="enable evals in existing saved files; no deployment")
    migration.add_argument("--values", required=True, type=Path)
    migration.add_argument("--secrets", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "check":
            validate(json.load(sys.stdin))
        else:
            enable(args.values.absolute(), args.secrets.absolute())
    except (ValueError, OSError, AttributeError, TypeError) as error:
        # Validation errors above are deliberately value-free. Unexpected input
        # shape / IO errors must not echo customer data either.
        message = str(error) if type(error) is ValueError else "Invalid eval configuration or inaccessible input file"
        print(f"ERROR: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
