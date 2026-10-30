# Upgrade from Phoenix BYOC 0.2.4 to 0.2.5

This release updates Web, frontend, Workflow Engine, OpenSandbox, Gateway and
Agents from Preview. Workflow definitions move into Engine's database catalog.
The installer prepares the Web database first, upgrades Engine and imports the
catalog, then upgrades Web and Gateway. Existing databases and Valkey stay in place.

## Before updating

Finish active workflows and pause new submissions and any definition-seeding
jobs until the update completes.
Keep your existing `values.yaml` and `values.secrets.yaml`; do not replace them
with examples. Existing GCP VM pool, Workload Identity, domain, storage and
registry settings should remain in place.

Backups are optional for this procedure. For an extra recovery point, back up
your databases, volumes and configuration before updating. The installer does
not create backups automatically.

Use the existing installation tools plus Python 3.9 or newer. AgentFS needs
Linux sandbox nodes with `/dev/fuse` and permission to run the FUSE plugin and
sandbox capabilities described in [AgentFS prerequisites](docs/agentfs.md).
The installer installs the plugin and checks node capacity automatically.
Keep the existing `fuseDevicePlugin.install` setting. Set it to `false` only
when reusing a provider managed outside this BYOC installation.

Keep any existing agent bundle namespace and publisher allowlist. The normal
`--generate-secrets` option preserves populated passwords and tokens.
No new settings or secrets are required when upgrading from 0.2.4. Preserve the
pool-secret encryption key already stored in your secrets file.

During installation or standalone verification, keep a Ready FUSE-capable node
available for each configured Linux sandbox class. This is an existing 0.2.2
check, not a new requirement. Scale-up from an idle zero-node sandbox pool
still depends on the cluster autoscaler's FUSE resource configuration and was
not validated by this release.

## Update using your existing Git checkout

From the Phoenix BYOC directory, fetch and select the exact release:

```bash
git fetch origin --tags
git checkout v0.2.5
```

Keep your existing local configuration files. If Git reports tracked local
changes, preserve them and resolve the conflict before continuing; do not use
a forced checkout. Confirm your current Kubernetes context is the intended
customer cluster:

```bash
kubectl config current-context
```

Apply the update using your existing namespace and files (the example assumes
namespace `phoenix`):

```bash
./scripts/install.sh \
  --namespace phoenix \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml \
  --generate-secrets
```

Valkey is already included in 0.2.2. Do not add `--discard-redis-state` for this
upgrade. Older Redis-based installations need the separate
[legacy migration procedure](docs/redis.md#existing-redis-installations).

The installer performs database migrations and verifies application readiness.
Wait until it exits successfully with `Phoenix verification passed in namespace
phoenix` before starting new workflows. Use your namespace in place of `phoenix`
if different. Do not run two installers at once or create another administrator.

Afterward, sign in with your existing account and start a new workflow. Existing
workflow history and definition data are retained. New workflows use the database
catalog; running workflows keep their pinned content. Application-specific workflow
definitions are managed through the updated platform.

If migration reports an invalid legacy definition, stop and share the named
record and error with Phoenix support. Do not delete definitions or reset the
catalog import marker. The installer stops before upgrading Web when Engine's
migration fails. A completed import is not repeated on a retry.

Do not downgrade by simply rerunning the previous installer. See
[rollback requirements](docs/rollback.md#rolling-back-from-025) for the required
Web-before-Engine sequence and limits for newly published workflows.

## Alternative: release archive

Download `phoenix-byoc-0.2.5.tar.gz` and its `.sha256` file from the
[release page](https://github.com/canonix-engineering/phoenix-byoc/releases/tag/v0.2.5).
Verify and extract them into a new directory:

```bash
sha256sum -c phoenix-byoc-0.2.5.tar.gz.sha256
tar -xzf phoenix-byoc-0.2.5.tar.gz
cd phoenix-byoc-0.2.5
sha256sum -c SHA256SUMS
```

On macOS use `shasum -a 256 -c`. Run the same install command with paths to your
existing values and secrets. `DELIVERY.json` records the exact source commit;
`image-index.json` and `chart-index.json` list the pinned artifacts.

## If the update fails

Keep new workflows paused and share the error with Phoenix support. Retain
logs privately and redact credentials before sharing. Do not delete volumes,
regenerate secrets or force a rollback. Database migrations are not undone by
Helm rollback. See [upgrade recovery](docs/upgrades.md) and
[AgentFS rollback restrictions](docs/agentfs.md#existing-workflows-and-rollback).
