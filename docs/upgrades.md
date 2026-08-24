# Upgrades

BYOC releases are delivered through the `main` branch. Before updating, keep
the existing `values.yaml` and generated `values.secrets.yaml`; do not copy the
examples over them or create a new secrets file.

Record the currently installed repository revision, then update the local
checkout:

```bash
git rev-parse HEAD
git switch main
git pull --ff-only origin main
```

Review the new `release.yaml` and repository changes, then back up all
customer-managed PostgreSQL databases and persistent volumes. Apply the update
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
generates new `GENERATE_HEX_*` values and refreshes derived internal URLs. New
external `CHANGE_ME_*` fields stop preflight and are reported by path until the
customer supplies them.
