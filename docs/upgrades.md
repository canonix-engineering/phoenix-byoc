# Upgrades

1. Read the target release notes.
2. Back up all customer-managed PostgreSQL databases and persistent volumes.
3. Check out the Git tag containing the target `release.yaml`.
4. Run preflight and render.
5. Review image, chart, Job, CRD and database migration changes.
6. Run `install.sh --generate-secrets` with the same `--namespace`, `--values`
   and generated `--secrets` file. Do not create a new secrets file for an
   upgrade.
7. Run `verify.sh` with the same arguments and application smoke tests.

Chart and image versions are immutable. Never edit a published version in
place.

`--generate-secrets` synchronizes fields added to the example by the new
release. It preserves existing passwords, tokens and customer-specific fields,
generates new `GENERATE_HEX_*` values and refreshes derived internal URLs. New
external `CHANGE_ME_*` fields stop preflight and are reported by path until the
customer supplies them.
