# Rollback

For a rollback from 0.2.5, follow the additional requirements below before
using a previous installer.

Before an upgrade, record the current repository revision with
`git rev-parse HEAD`. Application rollback means checking out that recorded
commit, reviewing its `release.yaml` and applying it again with the same
namespace, values and secrets files.

```bash
git switch --detach <previous-commit>

./scripts/install.sh \
  --namespace phoenix \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml \
  --generate-secrets
```

Replace `phoenix` with the installation namespace. After the rollback, return
the repository checkout to the delivery branch with `git switch main`.

Database migrations are not automatically reversed. Before upgrading:

- review whether migrations are backward compatible;
- take a PostgreSQL backup;
- record the currently installed release manifest.

Do not delete PVCs, CRDs or namespaces as part of a rollback. Restore a
database backup only through the customer's database recovery procedure.

## Rolling back from 0.2.5

Pause workflow starts, definition publication and definition-seeding jobs. Restore
the previous Web servers/workers first, then the previous Engine. Coordinate this
application-only rollback with Phoenix support: the old generic installer order
is not a substitute for this sequence. Do not run Rails down migrations for the
catalog bootstrap or the new agent-kind migration.

The previous Engine uses its file catalog and cannot start new app-specific
published definitions. Drain runs depending on those definitions before a full
downgrade. Preserve catalog tables, immutable content and the import marker;
never reset the marker or delete records to force another import. Database
recovery, if required, follows the customer's backup procedure.
