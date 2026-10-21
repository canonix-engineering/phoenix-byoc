# Upgrade an existing CSG installation to Phoenix BYOC 0.2.1

Release: **0.2.1**, channel: **stable**, Git tag: **v0.2.1**.

Use this procedure for the existing bundled PostgreSQL and Redis/Valkey installation on
GCP, keeping its current direct-ECR access. This is an online installer: the
archive contains the installer, local charts, templates and documentation;
container images and external charts are downloaded from their pinned registries.
The qualified runtime platform is Linux amd64.

## 1. Prepare the maintenance window

- Stop submitting new workflows and let active workflows finish, or coordinate
  their interruption before taking the recovery checkpoint.
- Keep the current namespace, tenant, GCP project/zone/VM pool, Workload Identity,
  DNS/TLS, StorageClasses, PVCs, resource classes and node placement.
- Keep the existing `values.yaml`, `values.secrets.yaml`, registry credentials
  and Gateway encryption key. Do not replace them with the examples.
- Retain the old installer/revision and its `release.yaml` for recovery.
- Use the tools in [Prerequisites](docs/prerequisites.md). `mise install` from
  the extracted directory installs the pinned versions. Bash, OpenSSL and a
  SHA-256 utility must also be available. The installer host and cluster need
  access to the configured registries and enabled GCP/provider endpoints.
- If using custom agent bundles, validate them before the window: outputs must
  use `output_schema_relpath`. Legacy `status_file`, `status_schema`,
  `stage_data_schema_relpath` and inline `output_schema` are no longer accepted.
  Bundles supplied by the released Agent image already use the supported format.

Set these variables to the **existing** configuration directory and namespace.
Use absolute paths; `phoenix` is only the example namespace:

```bash
set -euo pipefail
export BYOC_CONFIG=/absolute/path/to/existing-config
export BYOC_NAMESPACE=phoenix
test -f "$BYOC_CONFIG/values.yaml"
test -f "$BYOC_CONFIG/values.secrets.yaml"
kubectl config current-context
kubectl -n "$BYOC_NAMESPACE" get deployments,statefulsets,pvc
```

Confirm the displayed context is the intended existing GCP cluster. The
installer does not change it. Do not proceed with an unexpected context.

## 2. Optional backup

For a disposable PoC, you may skip this section if you accept the risk of
losing data if the update goes wrong. A backup is recommended for anything you
want to keep. The installer does not back up databases or volumes.

If taking a backup, prevent application writes while taking the database and
volume checkpoint, using your existing maintenance procedure. Keep backups private:

```bash
umask 077
export BYOC_BACKUP="$BYOC_CONFIG/backups/before-0.2.1-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BYOC_BACKUP"
cp "$BYOC_CONFIG/values.yaml" "$BYOC_BACKUP/values.yaml"
cp "$BYOC_CONFIG/values.secrets.yaml" "$BYOC_BACKUP/values.secrets.yaml"
helm list -n "$BYOC_NAMESPACE" -o json > "$BYOC_BACKUP/helm-releases.json"
kubectl -n "$BYOC_NAMESPACE" get pvc -o yaml > "$BYOC_BACKUP/pvc.yaml"
```

Back up all databases in the bundled PostgreSQL server, including roles and
Web's cache/queue/cable databases. The command below selects the standard BYOC
PostgreSQL Pod and reads its credentials inside the Pod; it prints no password:

```bash
BYOC_PG_POD=$(kubectl -n "$BYOC_NAMESPACE" get pods \
  -l app.kubernetes.io/instance=postgresql \
  -o jsonpath='{.items[0].metadata.name}')
test -n "$BYOC_PG_POD"
kubectl -n "$BYOC_NAMESPACE" exec "$BYOC_PG_POD" -- sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dumpall -h 127.0.0.1 -U "$POSTGRES_USER"' \
  > "$BYOC_BACKUP/postgresql-all.sql"
test -s "$BYOC_BACKUP/postgresql-all.sql"
```

Also take your established GCP backup/snapshot of the persistent volumes,
including workflow artifacts, Cortex PostgreSQL, ClickHouse and Valkey. Record
the snapshot/backup IDs with the database dump and previous release revision.
The dump contains sensitive database contents and role hashes; do not send it
in a support message. Confirm the checkpoint can be restored before updating.

For the small PoC, the command in step 5 replaces legacy Redis with a fresh
Valkey instance, without copying Redis contents. Finish active workflows and ask
users to pause activity first. Old Redis queues, streams and other Redis-held
state will not be available in Valkey; start new workflows after the update.
PostgreSQL records and artifact files are not deleted by this cache cutover.
The old Redis PVC is retained, but it is not a coordinated application backup.

If you need to preserve Redis-held state, do not use the PoC option. Follow the
[coordinated migration](docs/redis.md#existing-redis-installations) instead.

## 3. Download the immutable release

Use a new directory, keeping the old installer and configuration available:

```bash
curl -fLO https://github.com/canonix-engineering/phoenix-byoc/releases/download/v0.2.1/phoenix-byoc-0.2.1.tar.gz
curl -fLO https://github.com/canonix-engineering/phoenix-byoc/releases/download/v0.2.1/phoenix-byoc-0.2.1.tar.gz.sha256
sha256sum -c phoenix-byoc-0.2.1.tar.gz.sha256
tar -xzf phoenix-byoc-0.2.1.tar.gz
cd phoenix-byoc-0.2.1
```

On macOS use `shasum -a 256 -c` in place of `sha256sum -c`. The extracted
`SHA256SUMS` verifies the files inside the installer. `DELIVERY.json` identifies
the source Git commit. `release.yaml` and `image-index.json` record the exact
images; `chart-index.json` records chart versions and downloaded checksums.

Do not substitute current Preview or main versions. No image rebuild,
old-image repackaging, registry migration or new AWS credentials are required.

## 4. Merge the required values

Merge this block into the existing `application` section of
`$BYOC_CONFIG/values.yaml`; do not create a duplicate YAML key or replace the
whole section. A copy is in `examples/upgrade-0.2.0.values.yaml`.

```yaml
application:
  agentBundles:
    namespace: agent-bundles
    globalPublisherUserIds: []
```

Agent bundle lookup and publication are enabled by default. Remove obsolete
`standaloneEnabled` and `publicationEnabled` overrides from existing values.
Retain publisher credentials and the global publisher-user allowlist; see the
[publication configuration](docs/configuration.md#agent-bundle-lookup-and-publication).

| Setting | Required action |
| --- | --- |
| `secrets.application.artifactPublisherToken` | No manual value is needed. `--generate-secrets` adds a separate random token. |
| `secrets.application.workflowEngineToken` | Retain the existing real token. It must be nonempty and must not equal `phoenix-workflow-engine-default-token`; the chart passes the same value to Web, Gateway and Engine. |
| `services.gateway.toolboxAuthMode` | Keep `observe` (the default). This release does not require `enforce`. |
| Gateway ingress | Existing enablement/hostname/TLS stay unchanged. The updated adapter supplies the scoped agent routes automatically. |
| Bundled PostgreSQL, Valkey, Cortex and ClickHouse | Keep enabled. `--generate-secrets` requires the complete bundled topology. |
| GCP, Workload Identity, VM pool, resource classes, volumes and placement | Retain the existing customer values. Do not copy supplier Test/Preview settings. |
| Direct ECR access | Retain `imageRegistry: ""`, the existing ECR refresh settings, pull Secret and read-only credentials. |
| OpenSandbox controller and CRDs | Retain the current ownership and enablement. Do not adopt another release's CRDs or install a second controller. |

Check for an invalid existing Engine token without printing it:

```bash
yq -e '.secrets.application.workflowEngineToken != null and
  .secrets.application.workflowEngineToken != "" and
  .secrets.application.workflowEngineToken != "phoenix-workflow-engine-default-token"' \
  "$BYOC_CONFIG/values.secrets.yaml" >/dev/null
```

If this check fails, stop and resolve the shared-token configuration with the
release contact before the maintenance window. Do not rotate an already valid
token or replace the secrets file. New optional external secret fields reported
by preflight must be filled only when their integration is used; otherwise set
them to an empty string as described in [Installation](docs/installation.md).

## 5. Apply the update

From the extracted release directory, run in Bash so a failing installer is not
hidden by the log-writing command:

```bash
set -o pipefail
umask 077
./scripts/install.sh \
  --namespace "$BYOC_NAMESPACE" \
  --values "$BYOC_CONFIG/values.yaml" \
  --secrets "$BYOC_CONFIG/values.secrets.yaml" \
  --generate-secrets \
  --discard-redis-state 2>&1 | tee "$BYOC_CONFIG/upgrade-0.2.1.log"
```

`--discard-redis-state` explicitly accepts starting with empty Valkey data. It
pauses the Phoenix Deployments, waits for their Pods to exit, upgrades only the
cache, checks Valkey through the existing `redis-client` endpoint and restores
the original replica counts before continuing the platform update. It preserves
the old Redis PVC and does not reuse it for Valkey. If Valkey is already
installed, the option does not clear or reset it.

The shortcut supports the standard PoC namespace with only Phoenix workloads
and no autoscalers. Active sandbox Pods, jobs or remaining Redis clients stop
the cutover so you can finish them and retry. Do not run two installers at once.

The installer preserves existing passwords/tokens, adds the publisher token,
checks inputs, renders manifests and updates the enabled Helm releases. Web
migrations and application rematerialization run before Gateway and Engine;
demo data is not seeded. Existing users are retained: do not run initial-admin
creation during an upgrade. The generated `.rendered/all.yaml` contains Secrets
and must remain private.

A successful run exits with status zero and ends with
`Phoenix verification passed in namespace <your namespace>.`

## 6. Verify before ending the window

```bash
./scripts/verify.sh \
  --namespace "$BYOC_NAMESPACE" \
  --values "$BYOC_CONFIG/values.yaml" \
  --secrets "$BYOC_CONFIG/values.secrets.yaml"
helm list -n "$BYOC_NAMESPACE"
kubectl -n "$BYOC_NAMESPACE" get deployments,statefulsets,pods,pvc
kubectl -n "$BYOC_NAMESPACE" get cronjob/ecr-pull-secret-refresh
```

All enabled Helm releases should be `deployed`, workloads Ready and the existing
PVCs Bound. Then use an existing account to:

1. Sign in and open an existing app; confirm existing records remain available.
2. Run the normal customer workflow and open/download its resulting artifact.
3. Answer a workflow question or review request and confirm execution resumes.
4. Confirm queued work is processed and workflow progress updates in the UI.
5. Exercise the customer's enabled GCP VM workflow with its existing project,
   VM pool and Workload Identity settings.

The EKS qualification passed the application and human-review scenarios. It
cannot exercise the customer's GCP project, so step 5 is the customer acceptance
check. Report the installed version, completion time and these results through
the existing support conversation.

## 7. If an upgrade step fails

If the cache cutover fails, the script attempts to restore the original
application replica counts and keeps its recovery journal under `.tmp/`.
Keep the same extracted directory. Resolve the reported cause (for example,
finish active workflows/jobs or fix image-pull/storage errors) and rerun the
same install command. Do not delete the journal or the old Redis PVC. If the
cache is unavailable, the applications may remain unready until the retry
succeeds.

For other failures, keep the maintenance window active and stop further rollout. Preserve the
upgrade log, failed Job/Pod names and events. Share only redacted diagnostics;
never share the secrets file, rendered manifests, database dump or registry
credentials. See [Troubleshooting](docs/troubleshooting.md).

Do not delete the namespace/PVCs, regenerate credentials, repeat migrations with
changed settings, or start the old application against an upgraded database
without a recovery decision. A Helm rollback does not undo database migrations.

For a full recovery, prevent application writes, restore the coordinated
pre-upgrade database and volume checkpoint using the existing GCP recovery
procedure, restore the saved values/secrets and deploy the recorded previous
release. Keep the database, artifact volumes and application versions from the
same checkpoint. Verify the recovered installation before reopening access.
