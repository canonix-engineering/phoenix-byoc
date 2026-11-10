# Upgrade from Phoenix BYOC 0.2.5 to 0.2.6

This release updates Web, frontend, Engine, OpenSandbox, Agents and Gateway
from the selected Preview commits. Existing PostgreSQL, Valkey, Cortex and
ClickHouse installations remain in place.

## Workflow history is preserved by default

This BYOC release explicitly disables the new completed-workflow retention.
Existing customer values inherit `services.workflowEngine.runRetention.enabled: false`; no new values or credentials are required for this upgrade. Keep it
false throughout the upgrade. Cleanup is not automatically enabled afterward.
A later opt-in requires a separate customer retention decision; see
[retention configuration](docs/configuration.md#workflow-history-retention).

The release adds the required internal Web permission during rendering while
preserving existing tokens and identity restrictions, including custom
`internalServiceTokens`. No manual edit of a populated secrets file is needed.

## Prepare the upgrade

The supported starting point is stable 0.2.5. Earlier installations must follow
the intervening upgrade procedures first. Finish active workflows and pause new
starts and definition-seeding jobs until the installer completes.

Preserve existing `values.yaml`, `values.secrets.yaml`, database credentials,
PVCs, namespace, GCP VM-pool configuration and Workload Identity bindings. Do
not replace customer files with the examples. Keep the existing FUSE plugin
and retained-Agent settings; see [AgentFS prerequisites](docs/agentfs.md).

Take a recovery backup of databases, artifact data, snapshots and configuration
under your deployment's backup policy before enabling cleanup. The installer
does not take backups, and restoring a database alone may not restore deleted
artifact or snapshot content.

Web adds six migrations for the CI capability, retention fields/concurrent
indexes/constraints, historical business-record references, and dataset
repository provenance. The installer must prepare the incoming Web schema
before upgrading Engine; Engine requires the new retention indexes. When
application database hooks are disabled, complete the service-owned migrations
before upgrading Engine. Index creation can extend installation time.

## Select the published release

From your existing BYOC checkout:

```bash
git fetch origin --tags
git checkout v0.2.6
kubectl config current-context
```

If Git reports local tracked changes, preserve and resolve them before
continuing. Do not force checkout. Verify the Kubernetes context points to the
intended customer cluster.

Alternatively, download `phoenix-byoc-0.2.6.tar.gz` and its checksum from the
[published release](https://github.com/canonix-engineering/phoenix-byoc/releases/tag/v0.2.6),
then verify and extract into a new directory:

```bash
sha256sum -c phoenix-byoc-0.2.6.tar.gz.sha256
tar -xzf phoenix-byoc-0.2.6.tar.gz
cd phoenix-byoc-0.2.6
sha256sum -c SHA256SUMS
```

Use the existing customer configuration and secrets paths with the extracted
release. Never overwrite those files with examples from the archive.

## Apply and verify

Use the existing namespace and files
(the example assumes namespace `phoenix`):

```bash
./scripts/install.sh \
  --namespace phoenix \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml \
  --generate-secrets
```

For the bundled topology, `--generate-secrets` preserves existing populated
credentials and synchronizes newly introduced fields. It does not rotate them.
External dependency installations must follow their existing explicit-secret
contract; do not enable bundled dependencies to use this flag.

Keep the existing ordered Web database preparation, Engine migration, then
application rollout. Do not run installers concurrently, reset workflow
catalog markers, delete customer definitions or create a new administrator.
Valkey is unchanged; do not add `--discard-redis-state` for this upgrade.

Wait for the installer to exit successfully, including its verification step,
before starting new workflows. Standalone verification uses the same inputs:

```bash
./scripts/verify.sh \
  --namespace phoenix \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml
```

Sign in with the existing account and exercise a new workflow. Deployment
readiness alone does not verify every workflow feature. If a migration fails,
stop and share the named migration and sanitized error with Phoenix support;
do not delete data or reset migration state to force progress.

## Recovery limits

Do not run database down-migrations or the previous installer as a generic
rollback. Retention removes the usage-account foreign key and makes the
pull-request run reference nullable on run deletion. Restoring old foreign keys
can fail after cleanup removes referenced runs. Old images cannot recover
removed workflow history or artifact/snapshot content. Coordinate recovery with
Phoenix support using the pre-upgrade backups and the exact migration state.
The previous workflow-catalog constraints still apply; see
[the 0.2.5 rollback guidance](docs/rollback.md#rolling-back-from-025).

## Qualification

The upgrade from 0.2.5 was applied with the maintained installer on the AWS
`phoenix-byoc` simulation. Installation verification passed. The six new Web
migrations were applied, original database records and PVC identities were
preserved, and existing configuration and secret values were retained.
The running Artifact API reports retention disabled. A workflow smoke check
completed with a non-root FUSE workspace, and an existing workflow artifact was
verified unchanged. No customer GCP test was performed.
