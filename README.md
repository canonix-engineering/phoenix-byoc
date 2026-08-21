# Phoenix BYOC

This repository installs the complete Phoenix platform into a customer-owned
Kubernetes cluster. Phoenix engineers do not require access to that cluster.

## What is installed

- Phoenix Web and Web Frontend;
- Phoenix Gateway;
- Phoenix Workflow Engine;
- OpenSandbox server and, on a fresh cluster, its cluster-wide controller;
- Redis;
- Cortex PostgreSQL;
- ClickHouse;
- optional PostgreSQL and ingress-nginx when enabled in the selected values
  file.

## Installation contract

The installation package contains:

- this repository;
- complete values and secrets examples under `examples/`;
- access to the exact chart and image repositories from `release.yaml`;
- a kubeconfig whose current context points to the intended cluster.

The installation operator copies the examples, fills the cluster-specific
settings and external credentials, selects the target namespace and runs one
command. For the bundled installation, `--generate-secrets` creates the
internal database passwords, connection URLs and service tokens in the
selected secrets file before validation.

If the selected secrets file does not exist, the generator creates it from the
current example with mode `0600`. On every run it adds fields introduced by a
new release without overwriting existing operator-provided or generated
values. Secret values are never printed. The script then performs preflight
validation, renders the complete manifest, installs or upgrades every enabled
release, waits for workloads and prints the result. It never changes
kube-context, node labels or cluster infrastructure.

## Quick start

Install the [required tools](docs/prerequisites.md), make sure the current
kube-context points to the target cluster and prepare the configuration files:

```bash
mise install
kubectl config current-context
cp examples/values.yaml values.yaml
cp examples/values.secrets.yaml values.secrets.yaml
chmod 600 values.secrets.yaml
```

In `values.yaml`, replace every `CHANGE_ME` value and adapt DNS, ingress,
StorageClass, node placement and resources to the target cluster. In
`values.secrets.yaml`, provide only credentials issued by external systems,
including ECR credentials when direct ECR access is selected and the mail and
agent-provider credentials used by the installation. Leave all
`GENERATE_HEX_*` and `DERIVE_*` markers unchanged.

Install the complete bundled platform into the selected namespace:

```bash
./scripts/install.sh \
  --namespace phoenix \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml \
  --generate-secrets
```

Replace `phoenix` with the required namespace. The exact fields that must be
configured and generated are listed in
[Installation](docs/installation.md#prepare-the-inputs).

A fresh database does not contain an administrator account. After the workloads
are ready, create the first owner with `scripts/create-initial-admin.sh` as
documented in
[Installation](docs/installation.md#create-the-initial-administrator).

```bash
./scripts/create-initial-admin.sh \
  --namespace phoenix \
  --enterprise-name "Example organization" \
  --enterprise-domain example.com \
  --email admin@example.com \
  --name "Platform Administrator"
```

The exact release versions are recorded in `release.yaml`. Do not replace them
during installation. See [Configuration](docs/configuration.md#bundled-data-service-versions)
for the bundled PostgreSQL, Redis, Cortex PostgreSQL and ClickHouse versions.

## Images

Print the exact Phoenix image inventory:

```bash
./scripts/images.sh list
```

To use another registry, copy the images without changing names or tags:

```bash
./scripts/images.sh mirror \
  --source-ecr-profile phoenix-byoc-source \
  --to registry.example.com/phoenix
```

Then set `imageRegistry` and, when required, `imagePullSecrets` in the selected
values file. The source AWS credentials are used only on the mirroring host and
are never stored in Kubernetes. See [Container images](docs/images.md).

To pull directly from the Phoenix ECR instead, enable the optional token
refresher and reference its managed pull Secret:

```yaml
imageRegistry: ""
imagePullSecrets:
  - name: phoenix-ecr-pull
registry:
  ecrRefresh:
    enabled: true
    pullSecretName: phoenix-ecr-pull
```

The installer populates the Secret before Phoenix workloads start and refreshes
the 12-hour ECR token every six hours. See [Container images](docs/images.md).

## Tools

Install the pinned tool versions with:

```bash
mise install
```

See [Prerequisites](docs/prerequisites.md) for cluster requirements.

## Documentation

- [Installation](docs/installation.md)
- [Configuration](docs/configuration.md)
- [Container images](docs/images.md)
- [PostgreSQL](docs/postgresql.md)
- [ClickHouse](docs/clickhouse.md)
- [Ingress](docs/ingress.md)
- [Scheduling](docs/scheduling.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Responsibility boundary](BYOC_CONTRACT.md)

Any AI agent can follow [AGENTS.md](AGENTS.md) and the vendor-neutral
`install-phoenix-byoc` skill in `.agents/skills/`.
