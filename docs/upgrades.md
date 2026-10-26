# Upgrades

Stable BYOC releases are delivered through immutable Git tags and release
archives. For `0.2.2`, follow [the upgrade procedure](../UPGRADE.md).
Keep the existing `values.yaml` and generated `values.secrets.yaml`; do not copy
the examples over them or create a new secrets file. Record the installed
revision and download the new release into a separate directory.

If using a Git checkout instead of the release archive:

```bash
git rev-parse HEAD
git fetch origin tag v0.2.1
git switch --detach v0.2.1
```

For releases before `0.2.0-development.15`, read the
[Redis-to-Valkey migration procedure](redis.md#existing-redis-installations)
first. The installer blocks an ordinary upgrade while the legacy Redis
StatefulSet exists. For a PoC that can discard Redis-held state, use the explicit
`--discard-redis-state` option described in
[the legacy migration procedure](redis.md#existing-redis-installations).
An installation already on `0.2.1` keeps Valkey and does not need this flag.

Review the new `release.yaml` and repository changes. Backups are optional if
you accept the risk of data loss if the update fails; take a backup when you
want a recovery checkpoint. Apply the update
with the same namespace and configuration files used for the installation:

```bash
./scripts/install.sh \
  --namespace phoenix \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml \
  --generate-secrets
```

Replace `phoenix` with the existing installation namespace. The installer
performs preflight and rendering before it upgrades the enabled releases.
After the update, verify the installation with the same inputs:

```bash
./scripts/verify.sh \
  --namespace phoenix \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml
```

Chart and image versions are immutable. Never edit a published version in
place.

`--generate-secrets` synchronizes fields added to the example by the new
release. It preserves existing passwords, tokens and customer-specific fields,
generates new supported `GENERATE_*` values and refreshes derived internal URLs. New
external `CHANGE_ME_*` fields stop preflight and are reported by path until the
customer supplies them.

## Required configuration for 0.2.0

The `0.2.0` chart packages are published and the application images are pinned
to the digests used during qualification. For artifact-backed agent bundles, add to
the existing `values.yaml` (merge into `application`, do not duplicate the key):

```yaml
application:
  agentBundles:
    namespace: agent-bundles
    globalPublisherUserIds: []
```

Keep the existing `application.tenantId`, GCP project and VM pool settings,
Workload Identity annotations, storage, DNS, registry and placement settings.
No EKS configuration is needed at the customer.

Run the ordinary install command above with `--generate-secrets`. It adds the
new publisher token while retaining existing passwords, the Gateway encryption
key and service tokens. Do not copy credentials from the supplier's Test
environment. Web publication is enabled by default. Remove obsolete
`standaloneEnabled` and `publicationEnabled` overrides; retain credentials and
permissions as documented in
[Configuration](configuration.md#agent-bundle-lookup-and-publication).

Do not copy Test's concurrency or placement values into the customer deployment.
Retain an existing sandbox admission limit and resource classes. Evaluation result
details and metrics are optional; enable
`services.workflowEngine.operator.evalResultDetailEnabled` only with compatible
Web/Engine images. Gateway defaults to `observe`; `enforce` requires an Engine
release that signs toolbox capabilities.

If the customer has custom agent bundles, validate them against the new Agent
release before rollout. The tested Agent requires a bundle-local result schema
referenced by `output_schema_relpath`; legacy `status_file`, `status_schema`,
`stage_data_schema_relpath` and inline `output_schema` are rejected. A chart
upgrade cannot migrate custom bundle contents. Bundles supplied inside the
released Agent image are maintained with that image.

Web runs `db:create`, `db:migrate`, then `apps:rematerialize`; demo seeding is
disabled. Gateway and Engine follow Web so the new schema exists before they
start. Expect an application maintenance window during this sequence.

After verification, sign in with an existing user, open an existing app, run a
workflow, check its artifact, and complete a human-input question and resume.
Check the worker and any customer-enabled GCP integration separately. If a
migration or workflow fails, retain the command output and stop further rollout;
do not reinstall into an empty namespace or regenerate secrets.

Application/database rollback is not guaranteed by Helm rollback. Review the
release's migrations and restore a coordinated database/PVC backup when a
schema change cannot be reversed safely.
