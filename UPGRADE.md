# Upgrade from Phoenix BYOC 0.2.1 to 0.2.2

This release updates the applications and adds AgentFS support. The upgrade
was verified in the `phoenix-byoc` AWS EKS environment. The customer applies it
using their existing cluster, namespace, values and secrets.

## Before updating

Finish active workflows and pause new submissions until the update completes.
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
If your cluster already has a provider for `devic.es/fuse`, set
`fuseDevicePlugin.install: false` in your existing values to reuse it.

Keep any existing agent bundle namespace and publisher allowlist. The normal
`--generate-secrets` option adds a publisher token if missing and preserves
populated passwords and tokens. No manual token generation is needed.

## Update using your existing Git checkout

From the Phoenix BYOC directory, fetch and select the exact release:

```bash
git fetch origin --tags
git checkout v0.2.2
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

Valkey is already included in 0.2.1. Do not add `--discard-redis-state` for this
upgrade. Older Redis-based installations need the separate
[legacy migration procedure](docs/redis.md#existing-redis-installations).

The installer performs database migrations and verifies application readiness.
Wait until it exits successfully with `Phoenix verification passed in namespace
phoenix` before starting new workflows. Use your namespace in place of `phoenix`
if different. Do not run two installers at once or create another administrator.

Afterward, sign in with your existing account and use your normal workflows.

## Alternative: release archive

Download `phoenix-byoc-0.2.2.tar.gz` and its `.sha256` file from the
[release page](https://github.com/canonix-engineering/phoenix-byoc/releases/tag/v0.2.2).
Verify and extract them into a new directory:

```bash
sha256sum -c phoenix-byoc-0.2.2.tar.gz.sha256
tar -xzf phoenix-byoc-0.2.2.tar.gz
cd phoenix-byoc-0.2.2
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
