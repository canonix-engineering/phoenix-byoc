# Upgrades

Stable BYOC releases are delivered through immutable Git tags and release
archives. The `0.2.4` procedure is currently a [draft](../UPGRADE.md) pending Agents promotion.
Do not apply the development preparation branch to a customer installation.
Keep the existing `values.yaml` and generated `values.secrets.yaml`; do not copy
the examples over them or create a new secrets file. Record the installed
revision and download the new release into a separate directory.

If using a Git checkout instead of the release archive:

```bash
git rev-parse HEAD
git fetch origin tag v0.2.4
git switch --detach v0.2.4
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

## Enable evaluations on an existing installation

The eval defaults fix is a source change after `0.2.3`; use a release containing
`scripts/eval-config.py`. It does not change application image or chart pins.
Existing values override the new defaults, and an existing service-token mapping
is deliberately preserved by `--generate-secrets`.

To enable evaluations, update the same saved files used for installation:

```bash
python3 scripts/eval-config.py enable \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml
```

This command only edits local files. It changes missing or zero eval capacities
to `5`, preserves positive custom capacities, and adds the two eval scopes to
the identity matching the Gateway's `workflowEngineToken`. It preserves tokens,
other identities, existing scopes and tenant/app restrictions. An empty mapping
continues to use the values template's generated identity. The command refuses
tracked secrets, ambiguous credentials and malformed mappings; it never prints
secret values. If eval capacity overrides are stored in the secrets file, move
them to the values file first; otherwise their higher precedence would hide the
updated settings. Repeating the command does not rotate credentials or duplicate
scopes.

Do not run this command if evals are deliberately disabled. Keep both capacities
at `0` in that case. Custom identity mappings must already contain the credential
used by Gateway; repair a missing/mismatched entry before using the command.

Then run the normal install/upgrade and verification commands above with these
same files and the existing namespace. Helm's configuration checksums roll the
operator, Web and Web worker automatically. Manual edits to running ConfigMaps
or Secrets are not durable substitutes for these saved inputs.

After deployment, launch a small eval and confirm its child ticket progresses
and its result is saved without a 403. Local render tests do not replace this
runtime acceptance check.

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
