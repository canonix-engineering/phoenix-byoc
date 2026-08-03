# Rollback

Application rollback means checking out the previous supported repository tag,
rendering its `release.yaml` and applying it again.

Database migrations are not automatically reversed. Before upgrading:

- review whether migrations are backward compatible;
- take a PostgreSQL backup;
- record the currently installed release manifest.

Do not delete PVCs, CRDs or namespaces as part of a rollback. Restore a
database backup only through the customer's database recovery procedure.
