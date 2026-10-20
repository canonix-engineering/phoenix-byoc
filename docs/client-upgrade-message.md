# Client message for the application release

Draft for Pushpendra for the 2026-10-20 release candidate. Charts are published;
send only after the candidate is promoted to a verified stable release and image
access is confirmed. See [release gates](releases/0.2.0-rc.1.md).

---

Hi Pushpendra,

For the next Phoenix upgrade, please keep your existing `values.yaml` and
`values.secrets.yaml`. Do not replace them with the example files or generate a
new secrets file.

Before starting, take a backup of the bundled PostgreSQL application and internal
databases and the persistent volumes. Plan a maintenance window for the application
update and database migrations. Record the currently installed Git revision and
backup locations so the application and database can be recovered together.

Merge the following settings into the existing `application` section of your
`values.yaml`:

```yaml
application:
  agentBundles:
    standaloneEnabled: true
    publicationEnabled: false
    namespace: agent-bundles
    globalPublisherUserIds: []
```

These settings enable the artifact lookup used by the new agents. Publishing
custom agent bundles from Web remains a separate option.

If you maintain custom agent bundles, please have us validate them with the new
Agent version before the upgrade. Their output definitions must use
`output_schema_relpath`; the older `status_file` and `status_schema` settings are
no longer accepted.

Keep your existing tenant ID, GCP project and VM pool settings, Workload Identity
annotations, registry access, domain names, storage and node placement.
PostgreSQL and Valkey continue running as part of the bundled BYOC deployment.

Once we confirm that the release is available, update your BYOC checkout:

```bash
git rev-parse HEAD
git switch main
git pull --ff-only origin main
kubectl config current-context
```

Confirm that the displayed context is your existing GCP cluster. From the BYOC
repository, run:

```bash
./scripts/install.sh \
  --namespace phoenix \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml \
  --generate-secrets
```

Use your existing namespace if it is different from `phoenix`.
`--generate-secrets` preserves your current passwords, service tokens and Gateway
encryption key. It adds the new internal publisher token automatically; you do
not need to obtain or copy that token from us.

The installer runs the database migrations without demo seeding, then updates
the applications in dependency order. After it finishes, run:

```bash
./scripts/verify.sh \
  --namespace phoenix \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml
```

Please then sign in, open an existing app, run a workflow, open its resulting
artifact, and complete a workflow question through answer and resume. Also check
your normal GCP-backed workflow.

If the installer or a migration fails, keep the output and contact us before
retrying with changed settings. Do not delete the namespace or volumes, replace
the secrets file, or assume that a Helm rollback reverses database migrations.
