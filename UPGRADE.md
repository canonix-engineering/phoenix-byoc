# Upgrade from Phoenix BYOC 0.2.5 to 0.2.6

**Incomplete candidate: do not install.** Gateway's intended Preview image is
not yet available, retention policy is under review, and AWS upgrade rehearsal
has not been performed. The commands below apply only after the final stable
release has been published and this warning has been removed.

## Review retention before updating

The incoming Engine enables completed-workflow cleanup by default. Its upstream
policy expires terminal runs after 1,209,600 seconds (14 days) and retains zero
previous attempt snapshots. Existing historical runs can qualify immediately.
Deletion of workflow history, associated artifacts and snapshots cannot be
undone by returning to old images. CSG's retention policy and its supported
configuration must be settled before publication. Do not assume the previous
release's history-preservation behavior continues indefinitely.

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

After the stable release is qualified, use the existing namespace and files
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

## Qualification status

Candidate fixture rendering and schema validation passed: 66 resources,
63 valid and three skipped for unavailable CRD schemas. Eight updated Preview
Deployments and Engine's runtime Agent reference matched candidate digests.
Gateway remains on its previous published image. These are Preview and static
checks, not an upgrade rehearsal on the AWS `phoenix-byoc` installation or a
customer GCP test. Final mixed-version compatibility, customer image access,
retention configuration and recovery qualification remain pending.
