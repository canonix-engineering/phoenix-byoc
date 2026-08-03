# Phoenix BYOC

This repository installs the complete Phoenix platform into a customer-owned
Kubernetes cluster. Phoenix engineers do not require access to that cluster.

## What is installed

- Phoenix Web and Web Frontend;
- Phoenix Gateway;
- Phoenix Workflow Engine;
- OpenSandbox server and controller;
- Redis;
- Cortex PostgreSQL;
- optional PostgreSQL and ingress-nginx when enabled in `values.yaml`.

Twenty HQ, Mattermost, Headlamp, observability, production HA and
infrastructure provisioning are not installed.

## Installation contract

Before handoff, the installation package contains:

- this repository;
- populated `values.yaml` and `values.secrets.yaml`;
- access to the exact chart and image repositories from `release.yaml`;
- a kubeconfig whose current context points to the intended cluster.

The customer selects only the target namespace and runs one command:

```bash
./scripts/install.sh --namespace phoenix
```

The script performs preflight validation, renders the complete manifest,
installs or upgrades every enabled release, waits for workloads and prints the
result. It never changes kube-context, node labels or customer infrastructure.

## Preparing the package

Phoenix/customer administrators prepare the two files before installation:

```bash
cp values.yaml.example values.yaml
cp values.secrets.yaml.example values.secrets.yaml
chmod 600 values.secrets.yaml
```

`values.yaml` contains PostgreSQL, Redis, Cortex, ingress, storage and
scheduling settings. `values.secrets.yaml` contains credentials and must never
be committed.

The exact versions configured in `cnx-dev-eks/test` are recorded in
`release.yaml`. Do not replace them during installation.

## Images

Print the exact Phoenix image inventory:

```bash
./scripts/images.sh list
```

To use another registry, copy the images without changing names or tags:

```bash
./scripts/images.sh mirror \
  --source-ecr-profile phoenix-byoc-source \
  --to registry.customer.example/phoenix
```

Then set `imageRegistry` and, when required, `imagePullSecrets` in
`values.yaml`. The source AWS credentials are used only on the mirroring host
and are never stored in Kubernetes. See [Container images](docs/images.md).

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
- [Ingress](docs/ingress.md)
- [Scheduling](docs/scheduling.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Responsibility boundary](BYOC_CONTRACT.md)

Any AI agent can follow [AGENTS.md](AGENTS.md) and the vendor-neutral
`install-phoenix-byoc` skill in `.agents/skills/`.
