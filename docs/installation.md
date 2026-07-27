# Installation

## 1. Choose a profile

- `default`: external primary PostgreSQL, bundled Redis and bundled Cortex.
- `external`: external PostgreSQL, Redis and Cortex.
- `kind`: bundled ingress-nginx, PostgreSQL, Redis and Cortex for testing.

## 2. Create local configuration

```bash
./scripts/bootstrap.sh
```

Edit `values.yaml` and `values.secrets.yaml`. Neither file should be committed.
Replace every `CHANGE_ME` value.

## 3. Prepare PostgreSQL

Choose one method:

- enable both DB hooks and provide `secrets.postgresql.adminUrl`;
- disable both hooks and let the customer manage database provisioning and
  migrations.

See [postgresql.md](postgresql.md).

## 4. Validate and render

```bash
./scripts/preflight.sh --environment default
./scripts/render.sh --environment default
```

Review `.rendered/default/all.yaml`. It contains rendered Secrets and must
remain local.

## 5. Install

```bash
./scripts/install.sh --environment default
```

The script repeats preflight and rendering, shows the current context, requests
confirmation, and runs Helmfile. Enabled database hooks run as part of the
corresponding chart installation.

## 6. Verify again

```bash
./scripts/verify.sh --environment default
```

Configure DNS only after Services and ingress resources have the expected
addresses.
