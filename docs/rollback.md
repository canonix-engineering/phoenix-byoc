# Rollback

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
