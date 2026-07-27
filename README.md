# Phoenix BYOC

Public deployment orchestration for installing Phoenix in a customer-owned
Kubernetes cluster. The application charts are built from the private
`phoenix-devops` source repository and published as immutable public OCI
artifacts.

> [!WARNING]
> The checked-in `stable` channel is currently marked `development`. It is
> renderable for integration work but must not be presented as a supported
> customer release until the referenced charts and images are public.

## What is installed

- OpenSandbox controller
- Phoenix Gateway
- Phoenix Web
- Phoenix Web frontend
- Phoenix Workflow Engine
- optional ingress-nginx
- optional standalone Redis
- optional standalone PostgreSQL for kind/demo only
- optional Cortex PostgreSQL

Twenty HQ, Mattermost, Headlamp, observability and production HA are outside
this repository.

## Quick start

Install the versions of Helm, Helmfile and kubectl declared in `.mise.toml`,
then:

```bash
./scripts/bootstrap.sh
# Edit values.yaml and values.secrets.yaml.
./scripts/preflight.sh --environment default
./scripts/render.sh --environment default
./scripts/install.sh --environment default
```

Use `--environment kind` for the bundled test profile and `--environment
external` when PostgreSQL, Redis and Cortex PostgreSQL are all customer
managed.

Installation is intentionally interactive. For reviewed automation, pass
`--yes` to `install.sh`.

## Configuration files

- `config/defaults.yaml`: defaults owned by this repository.
- `config/values.example.yaml`: public customer configuration example.
- `config/values.secrets.example.yaml`: secret inventory with placeholders.
- `values.yaml`: local customer overrides; ignored by Git.
- `values.secrets.yaml`: local secret values; ignored by Git.
- `releases/stable.yaml`: exact chart and image versions.

Read [the installation guide](docs/installation.md) before applying anything.
The customer/platform responsibility boundary is defined in
[BYOC_CONTRACT.md](BYOC_CONTRACT.md).
Release owners must also complete the
[public-repository checklist](docs/publication-checklist.md).

## Common commands

```bash
task preflight ENVIRONMENT=default
task render ENVIRONMENT=default
task install ENVIRONMENT=default
task verify ENVIRONMENT=default
```

An AI agent should follow [AGENTS.md](AGENTS.md) and the
`install-phoenix-byoc` skill.
