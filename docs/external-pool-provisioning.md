# Set up external pool provisioning

Use this guide after installing a BYOC release that supports external pool
provisioning. The release currently pinned in [release.yaml](../release.yaml),
`0.2.0-development.14`, uses the older embedded GCP integration and does not
include the `pool-provisioning` CLI. Follow [Upgrades](upgrades.md) when a
compatible BYOC release is supplied; changing only the Engine image is not a
supported migration. Existing embedded pools also require the
[migration procedure](#migration-and-rollback) below.

The setup steps and required reference material are included here so operators
do not need access to the Engine source repository.

This guide uses the CLI already installed in the **Engine operator container**
at `/usr/local/bin/pool-provisioning`. You need `kubectl` on your computer,
but no local Go installation or CLI build. Run all commands below in the same Bash
terminal on your computer; `kubectl exec` runs the indicated command inside the
container. No interactive container shell is required.

Supply provider-specific scripts as a customization directory containing
`pools.json` and two scripts. The CLI publishes it to Artifact Storage, and
Engine discovers it automatically.

## Before starting

Ask the platform installer for:

- A running deployment with the current Engine migration and operator version,
  including `pool-provisioning check`, plus compatible Artifact API and Gateway.
  All operator replicas must support checks and their cleanup recovery.
- The Kubernetes context, namespace, operator pod/container names and your
  organization UUID. The organization UUID is not the Kubernetes namespace.
- Permission to copy files into and execute commands in the operator pod.
- Provision/deprovision scripts for your provider, implementing the
  [script protocol](#runtime-and-script-protocol).

The operator must have the tools, network access and cloud identity those scripts
need. Its deployment must configure `ARTIFACT_API_BASE_URL`,
`PHOENIX_WORKFLOW_ENGINE_TOKEN`, `PHOENIX_GATEWAY_URL` and `INTERNAL_DATABASE_URL`.
The CLI reads these inside the container; no credential copying to your computer
is required. Scripts inherit only `PATH`, `HOME` and `TMPDIR`, so other operator
environment variables are not automatically available to them.

For a deployment still using the embedded integration, first follow the
[migration instructions](#migration-and-rollback).

## 1. Create the files on your computer

Open your terminal where you maintain deployment customizations, for example the
root of your own customization repository. Create a new directory:

```bash
mkdir -p ./my-pools/scripts
POOL_LOCAL_DIR="$PWD/my-pools"
```

Create `my-pools/pools.json` with this starting configuration:

```bash
cat > "$POOL_LOCAL_DIR/pools.json" <<'JSON'
{
  "pools": [{
    "name": "Application Dev",
    "workspace_root": "/home/phoenix/workspace",
    "ssh_user": "phoenix",
    "max_machines": 4,
    "command_timeout_seconds": 1200,
    "provision": {"path": "scripts/provision.sh", "args": ["dev"]},
    "deprovision": {"path": "scripts/deprovision.sh", "args": ["dev"]}
  }]
}
JSON
```

Edit this file for your environment:

- `name`: the pool name users will see in the UI.
- `workspace_root`: the workspace directory on the provisioned VM, for example
  `C:/phoenix/workspace` for Windows. This is not a path on your computer.
- `ssh_user`: the account that your provisioning script prepares on the VM.
- `max_machines` and `command_timeout_seconds`: capacity and operation timeout.
- Both `args` arrays: arguments understood by your scripts. `dev` is an example,
  not a built-in Engine parameter; remove or replace it if your scripts differ.

Copy your actual scripts, replacing the source paths below:

```bash
cp /absolute/path/to/your-provision.sh "$POOL_LOCAL_DIR/scripts/provision.sh"
cp /absolute/path/to/your-deprovision.sh "$POOL_LOCAL_DIR/scripts/deprovision.sh"
```

The completed directory must contain:

```text
my-pools/
  pools.json
  scripts/
    provision.sh
    deprovision.sh
```

`provision.sh` reads JSON from stdin, creates or finds the VM using
`allocation_id`, installs the supplied public key for `ssh_user`, and returns the
address and provider state as JSON. `deprovision.sh` removes the owned resources
and returns `deleted: true`; it must also work when provisioning output was lost.
Both scripts run under Bash on the operator, including when they create Windows
VMs. Follow the linked protocol for the exact input/output fields.

For two pools, add another object to `pools` with a different name and the
arguments your staging script expects. Both pools can share the same scripts
with distinct arguments, such as `dev` and `staging`. Keep your completed
directory in your own repository.

Only scripts referenced by `pools.json` are uploaded, not the entire directory.
Scripts cannot depend on sibling files being installed with them. Package any
provider tools and other runtime dependencies in the operator deployment.

## 2. Select the operator pod

Replace the example values with those supplied by the installer:

```bash
POOL_CONTEXT='your-kubernetes-context'
POOL_NAMESPACE='your-namespace'
POOL_ORGANIZATION_ID='11111111-1111-4111-8111-111111111111'
kubectl --context "$POOL_CONTEXT" -n "$POOL_NAMESPACE" get pods
```

Choose a **Running operator pod**, not the Engine API or Artifact API pod, and
set its name and container name:

```bash
POOL_OPERATOR_POD='your-operator-pod-name'
POOL_OPERATOR_CONTAINER='operator'
kubectl --context "$POOL_CONTEXT" -n "$POOL_NAMESPACE" \
  exec "$POOL_OPERATOR_POD" -c "$POOL_OPERATOR_CONTAINER" -- \
  /usr/local/bin/pool-provisioning --help
```

Expected: help listing `validate`, `apply`, `show`, `delete` and `check`. If the
binary or `check` command is missing, ask the installer for a compatible BYOC
release before continuing.

## 3. Copy and validate the files

From the same terminal, create a temporary directory in the operator and copy
your local directory into it:

```bash
POOL_REMOTE_DIR=$(kubectl --context "$POOL_CONTEXT" -n "$POOL_NAMESPACE" \
  exec "$POOL_OPERATOR_POD" -c "$POOL_OPERATOR_CONTAINER" -- \
  mktemp -d /tmp/pool-customization.XXXXXX)
kubectl --context "$POOL_CONTEXT" -n "$POOL_NAMESPACE" \
  cp "$POOL_LOCAL_DIR" "$POOL_OPERATOR_POD:$POOL_REMOTE_DIR/my-pools" \
  -c "$POOL_OPERATOR_CONTAINER"

kubectl --context "$POOL_CONTEXT" -n "$POOL_NAMESPACE" \
  exec "$POOL_OPERATOR_POD" -c "$POOL_OPERATOR_CONTAINER" -- \
  /usr/local/bin/pool-provisioning validate \
  --organization "$POOL_ORGANIZATION_ID" --config "$POOL_REMOTE_DIR/my-pools"
```

Here `--config` is a path **inside the container**. The `scripts/...` paths in
`pools.json` resolve relative to that file, regardless of the working directory.
[kubectl cp](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_cp/)
requires `tar` in the container; the standard Engine image includes it.

Expected: exit zero and a JSON manifest with resolved pool UUIDs and script
digests. Invalid fields or missing files produce an error. Validation does not
execute scripts or test provider access.

## 4. Publish and wait for discovery

Run from your computer, using the same pod and copied files:

```bash
kubectl --context "$POOL_CONTEXT" -n "$POOL_NAMESPACE" \
  exec "$POOL_OPERATOR_POD" -c "$POOL_OPERATOR_CONTAINER" -- \
  /usr/local/bin/pool-provisioning apply \
  --organization "$POOL_ORGANIZATION_ID" --config "$POOL_REMOTE_DIR/my-pools"

kubectl --context "$POOL_CONTEXT" -n "$POOL_NAMESPACE" \
  exec "$POOL_OPERATOR_POD" -c "$POOL_OPERATOR_CONTAINER" -- \
  /usr/local/bin/pool-provisioning show --organization "$POOL_ORGANIZATION_ID"
```

Expected: a publication revision and `manifest.pools`, including each pool's
`id`. The CLI uploads scripts first and then the manifest. `apply` replaces the
organization's entire pool list, so include every pool you want to retain.

Engine polls roughly every five seconds. Wait for your pool names to appear in
the organization's pool UI; `show` reports publication, not Engine readiness.
Registration does not create VMs. Once published, Engine loads scripts from
Artifact Storage and no longer depends on the temporary copy in the pod.

## 5. Check each pool, then assign it to an application

Copy one pool UUID from `manifest.pools[].id` in `show` and run:

```bash
POOL_ID='replace-with-the-pool-uuid-from-show'
kubectl --context "$POOL_CONTEXT" -n "$POOL_NAMESPACE" \
  exec "$POOL_OPERATOR_POD" -c "$POOL_OPERATOR_CONTAINER" -- \
  /usr/local/bin/pool-provisioning check \
  --organization "$POOL_ORGANIZATION_ID" --pool "$POOL_ID"
```

Expected: `Pool check passed ...; VM and connection removed.` This command
provisions a real VM, tests SSH through Gateway and deprovisions it. No workflow
is created. Repeat for each pool; `apply` does not run this check automatically.
An error exits nonzero, and the operator retries unfinished cleanup. See
[smoke-check recovery](#installation-smoke-check).

After the checks succeed, assign the pools to your application in the existing
UI. Ordinary execution provisions a VM per agent attempt and disposes it after
the attempt finishes; suspension retains the VM.

## Updates and removal

For updates, edit the files on your computer, then repeat copying, validation
and publication. If the operator pod was replaced, select its new name first.
Preserve explicit pool IDs from `show` when renaming a pool. Removing a pool from
`pools.json` disables new allocations; existing VMs retain their cleanup scripts.

To disable all manifest-owned pools for this organization:

```bash
kubectl --context "$POOL_CONTEXT" -n "$POOL_NAMESPACE" \
  exec "$POOL_OPERATOR_POD" -c "$POOL_OPERATOR_CONTAINER" -- \
  /usr/local/bin/pool-provisioning delete --organization "$POOL_ORGANIZATION_ID"
```

Full [pools.json field reference](#poolsjson-reference).

## pools.json reference

Use `/usr/local/bin/pool-provisioning apply --help` inside the operator container
for an offline field summary and minimal example. The local input is one JSON
object:

```json
{
  "pools": [{
    "name": "Build",
    "workspace_root": "/work",
    "provision": {"path": "scripts/provision.sh", "args": ["dev"]},
    "deprovision": {"path": "scripts/deprovision.sh", "args": ["dev"]}
  }]
}
```

| Field | Required / default | Meaning and constraints |
| --- | --- | --- |
| `pools` | Required | Array of pool definitions. `[]` explicitly removes all pools; absent/null is invalid. |
| `pools[].name` | Required | Unique, nonempty name without surrounding whitespace, newline or NUL. |
| `pools[].workspace_root` | Required | Absolute canonical directory, e.g. `/work` or `C:/work`. Backslashes normalize to slashes; `/`, trailing slashes and `.`/`..` segments are rejected. |
| `pools[].provision.path` | Required | Path to the provisioning script; relative to this JSON file or absolute. |
| `pools[].deprovision.path` | Required | Path to the cleanup script, resolved the same way. |
| `pools[].provision.args` | Optional, empty | Array of literal string arguments; no shell expansion. NUL is rejected. |
| `pools[].deprovision.args` | Optional, empty | Cleanup arguments with the same rules. |
| `pools[].id` | Optional | Unique UUID. Omitted/zero derives from organization and name. Preserve the explicit ID from `show` when renaming. |
| `pools[].ssh_user` | Optional, `phoenix` | SSH login name; empty also selects the default. No whitespace or NUL. |
| `pools[].max_machines` | Optional, `4` | Positive integer limit across active, provisioning, deleting and smoke-test VMs. Zero selects the default. |
| `pools[].command_timeout_seconds` | Optional, `1200` | Operation timeout in seconds, integer `1..86400`. Zero selects the default. Cleanup has its own timeout. |

Unknown fields and duplicate pool IDs/names are rejected. JSON and each script
must be nonempty regular files of at most 1 MiB. Scripts need not be executable;
Engine invokes Bash. Paths identify files to upload, not paths inside Engine.
The published manifest uses script digests instead of local paths.

## Installation smoke check

Run the command in [step 5](#5-check-each-pool-then-assign-it-to-an-application)
inside the deployed operator container.

The operator environment supplies `INTERNAL_DATABASE_URL`, `PHOENIX_GATEWAY_URL`,
`ARTIFACT_API_BASE_URL` and `PHOENIX_WORKFLOW_ENGINE_TOKEN`. This administrative
command creates a real VM and uses Gateway-managed SSH credentials. It reads the
pool configuration currently installed in Engine; it does not publish, refresh
or change assignments. A missing/disabled pool or exhausted capacity fails the check.

The check reserves one disabled machine, snapshots scripts/arguments, invokes the
same provisioning and Gateway SSH test used for a workflow allocation, then
deprovisions and removes the connection and machine. Gateway's SSH test confirms
first-contact host identity using the same trust policy as ordinary provisioning.
No ticket, workflow, attempt or lease is created; no test VM becomes available to
workloads. Scripts receive zero UUIDs for `run_id` and `attempt_id` during a check;
resource identity must use the nonzero `allocation_id`.

Exit zero means provisioning, SSH and confirmed cleanup all succeeded. Errors
include the allocation ID; script stderr streams to command stdout. Cleanup is
attempted even after provisioning/SSH failure, timeout, SIGINT or SIGTERM, using
an independent timeout. If cleanup fails or the process dies, the operator retries
using the persisted snapshot and result, including after manifest removal. It
never replays provisioning for an abandoned check. Missing provisioning output
requires idempotent deletion by allocation ID, as for normal allocations. Inspect
operator logs for pending cleanup; capacity remains reserved until it succeeds.

`apply` and `validate` do not run this check automatically. Run it for each pool
to exercise its arguments, then use a real workflow to test scheduling, agent
execution and application-specific behavior. The smoke check does not validate
installed product versions, builds or a complete workflow.

Before first use, deploy the registry migration and update **all operators**.
Existing allocations and `pools.json`/Artifact/Gateway contracts are preserved;
the registry now also accepts allocations without a workflow for checks. Older
CLI commands still work, but older operators do not support recovering checks.
Complete all checks and pending cleanup before rolling back to an older operator.

## Runtime and script protocol

The operator polls on startup and every five seconds using its existing
`ARTIFACT_API_BASE_URL` and service credential. There is no manifest-reference
environment variable or feature flag. A failed refresh reports an error and
preserves the last successfully applied configuration. Persisted revisions stop
older responses from replacing newer state across operator replicas. Cleanup
continues independently of manifest refresh.

Scripts run under Bash in the operator deployment with manifest arguments passed
as separate argv entries. The base Engine image includes Bash. Provider SDKs,
network access and workload identity are supplied by the deployment; provider
scripts are distributed separately. The script environment contains only
`PATH`, `HOME` and `TMPDIR`; Engine database and service tokens are not forwarded.
Cancellation or timeout kills the script's process group. The timeout belongs
to the allocation snapshot, and provisioning also respects its attempt deadline.

Engine sends one JSON object on stdin:

```json
{
  "schema_version": 1,
  "allocation_id": "22222222-2222-4222-8222-222222222222",
  "organization_id": "11111111-1111-4111-8111-111111111111",
  "pool_id": "33333333-3333-4333-8333-333333333333",
  "run_id": "44444444-4444-4444-8444-444444444444",
  "attempt_id": "55555555-5555-4555-8555-555555555555",
  "ssh_user": "phoenix",
  "ssh_public_key": "<Gateway public key>",
  "provider_state": null
}
```

The public key is supplied only to provisioning. Private keys remain in Gateway.
Scripts must emit exactly one JSON object on stdout, at most 1 MiB, and exit zero.
Nonzero exit status, malformed output, or mismatched schema/allocation identity
fails the operation. Script output is never evaluated as code. Protocol stdout
is not logged. Stderr streams to operator stdout while the script runs, including
on failure; scripts must keep credentials out of their diagnostics.

Provisioning returns:

```json
{
  "schema_version": 1,
  "allocation_id": "22222222-2222-4222-8222-222222222222",
  "address": "192.0.2.10:22",
  "provider_state": {"resource_id": "provider-resource-reference"}
}
```

`provider_state` is opaque JSON persisted and returned to the deprovision script;
it must contain no credentials. Engine stores the result before configuring
Gateway and probing SSH. After the result is stored, recovery uses the saved
address and state without provisioning another VM.

Provisioning must be idempotent by `allocation_id`: a retry after lost output
must find and verify the same resource. A new attempt gets a different allocation.
Cloud ownership validation belongs in the script. Engine validates protocol
identity and Gateway readiness, without interpreting provider state.

Deprovisioning receives the same allocation identity and persisted provider state,
which can be absent if provisioning output was lost. It must find resources by
allocation identity and complete cleanup even in that case. It returns:

```json
{
  "schema_version": 1,
  "allocation_id": "22222222-2222-4222-8222-222222222222",
  "deleted": true
}
```

`deleted: true` is the provider's confirmation that the VM and owned resources
are absent. Repeating deletion of an absent resource must succeed. Engine drains
Gateway access before invoking deletion, and only releases capacity after this
confirmation. Failures retain registration and retry. Suspension retains the VM.

## Migration and rollback

| Combination | Behavior |
| --- | --- |
| Existing workflow clients with the new Artifact API | Existing routes and scopes are preserved |
| New CLI/operator with an old Artifact API | Customization routes are unavailable; no publication or refresh is accepted |
| New operator with the new Artifact API and no manifests | No provisioned pools; manually registered pools keep their behavior |
| Old and new operators on the provisioning registry | Unsupported; stop old operators before migration |

For a deployment using the embedded integration:

1. Stop new allocations and let the old operator finish all VM cleanup,
   including suspended attempts and uncertain deletions.
2. Stop old operators and Engine API writers. Keep the previous release available
   if cleanup has not finished. The migration refuses active legacy allocations.
3. Deploy the new Artifact API, run the Engine migration, and replace Engine
   processes. The migration preserves pools, manually registered machines and
   app references; it removes the legacy provider-specific allocation schema.
4. Supply scripts implementing the protocol above and publish the configuration
   with existing pool IDs. Remove legacy integration settings from deployment.
5. Verify pools and manifest ownership before reopening allocation admission.

Rollback requires disabling new allocations and draining all new managed VMs
with the new operator first. Preserve artifact history and snapshots until that
cleanup is complete. Reverting binaries alone does not restore the removed
legacy schema; restore a compatible drained registry migration or backup before
starting old operators. Never discard provisioning records for existing VMs.

## Documentation source

Adapted from the [Engine setup guide](https://github.com/canonix-engineering/phoenix-workflow-engine/blob/b8f561d3e4ca26e17ff0bbaa303f93918e120bf8/integrations/README.md)
and [operations reference](https://github.com/canonix-engineering/phoenix-workflow-engine/blob/b8f561d3e4ca26e17ff0bbaa303f93918e120bf8/docs/operations/external-pool-provisioning.md)
at revision `b8f561d3`. These source links require access to the
private Engine repository and are provided for documentation maintenance.
