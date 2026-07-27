# Upgrades

1. Read the target release notes.
2. Back up all customer-managed PostgreSQL databases and persistent volumes.
3. Update the exact versions in `releases/stable.yaml`.
4. Run preflight and render.
5. Review image, chart, Job, CRD and database migration changes.
6. Run `install.sh`.
7. Run `verify.sh` and application smoke tests.

Chart and image versions are immutable. Never edit a published version in
place.
