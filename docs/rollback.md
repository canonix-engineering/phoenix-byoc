# Rollback

Application rollback means restoring the previous exact chart and image
versions in `releases/stable.yaml`, rendering the result and applying it again.

Database migrations are not automatically reversed. Before upgrading:

- review whether migrations are backward compatible;
- take a PostgreSQL backup;
- record the currently installed release manifest.

Do not delete PVCs, CRDs or namespaces as part of a rollback. Restore a
database backup only through the customer's database recovery procedure.
