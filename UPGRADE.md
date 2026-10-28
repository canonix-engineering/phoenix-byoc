# Draft upgrade from Phoenix BYOC 0.2.3 to 0.2.4

**Not ready for customer use.** The final Agents CI, Preview rollout and qualification
are pending. The instructions below will be finalized before tag `v0.2.4`
is published. Do not apply this preparation branch to a customer installation.

This candidate updates Web, Engine and Agents, plus the Engine/frontend charts. Engine adds pool configuration schema; existing
databases and Valkey remain in place.

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
Keep the existing `fuseDevicePlugin.install` setting. Set it to `false` only
when reusing a provider managed outside this BYOC installation.

Keep any existing agent bundle namespace and publisher allowlist. The normal
`--generate-secrets` option preserves populated passwords and tokens.
The installer generates the new pool-secret encryption key once and keeps it
in your existing secrets file. Preserve that file for future upgrades and recovery.
No manual token generation is needed. The eval settings command below updates
permissions while preserving existing tokens.

During installation or standalone verification, keep a Ready FUSE-capable node
available for each configured Linux sandbox class. This is an existing 0.2.2
check, not a new requirement. Scale-up from an idle zero-node sandbox pool
still depends on the cluster autoscaler's FUSE resource configuration and was
not validated by this release.

## Update using your existing Git checkout

From the Phoenix BYOC directory, fetch and select the exact release:

```bash
git fetch origin --tags
git checkout v0.2.4
```

Keep your existing local configuration files. If Git reports tracked local
changes, preserve them and resolve the conflict before continuing; do not use
a forced checkout. Confirm your current Kubernetes context is the intended
customer cluster:

```bash
kubectl config current-context
```

Enable evals in your saved configuration before installing:

```bash
python3 scripts/eval-config.py enable \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml
```

This local migration sets missing or zero eval capacities to five, preserves
positive custom capacities, and adds eval permissions to the matching service
identity. It preserves existing passwords, tokens and identity restrictions.
If evals were intentionally disabled, skip this command and keep both eval
capacities at zero.

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

Afterward, sign in with your existing account. Start a new workflow to use the
new Agent features, including chat attachments and pool setup scripts. Existing
workflows keep their pinned Agent image and bundle. If a pool overrides the Agent
image, update that override to a compatible version before using the new features.
Pool secret variables use the encryption key retained in `values.secrets.yaml`.

## Alternative: release archive

Download `phoenix-byoc-0.2.4.tar.gz` and its `.sha256` file from the
[release page](https://github.com/canonix-engineering/phoenix-byoc/releases/tag/v0.2.4).
Verify and extract them into a new directory:

```bash
sha256sum -c phoenix-byoc-0.2.4.tar.gz.sha256
tar -xzf phoenix-byoc-0.2.4.tar.gz
cd phoenix-byoc-0.2.4
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
