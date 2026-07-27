---
name: install-phoenix-byoc
description: Safely validate, render, install, upgrade, and verify Phoenix from the public phoenix-byoc repository. Use when an AI agent is asked to prepare or operate a Phoenix BYOC deployment in a customer-owned Kubernetes cluster, including kind tests, external PostgreSQL/Redis configuration, ingress selection, troubleshooting, and rollback preparation.
---

# Install Phoenix BYOC

Operate the checked-out `phoenix-byoc` repository without taking ownership of
customer infrastructure. Treat context selection, database changes and Helm
apply operations as approval boundaries.

## Prepare

1. Locate the repository root containing `helmfile.yaml.gotmpl`.
2. Read `BYOC_CONTRACT.md`, `AGENTS.md`, `docs/prerequisites.md`, and
   `docs/installation.md`.
3. Inspect `releases/stable.yaml`; stop on the `development` channel unless the
   user explicitly authorizes pre-release validation.
4. Ask the user to identify the intended kube-context, namespace and profile if
   they are not already explicit. Never switch context automatically.
5. Run `./scripts/bootstrap.sh` only when local values files are absent. Never
   display or commit populated secret values.

## Validate

1. Read `values.yaml` without changing scheduling, ingress or database ownership
   decisions.
2. Confirm that `values.secrets.yaml` exists without printing it.
3. Run `./scripts/preflight.sh --environment <profile>`.
4. Run `./scripts/render.sh --environment <profile>`.
5. Inspect `.rendered/<profile>/all.yaml` without printing rendered Secret
   values.
6. Report the current context, namespace, enabled bundled components and any
   warnings.

## Apply

1. Obtain explicit user confirmation after rendering.
2. Run `./scripts/install.sh --environment <profile> --yes`.
3. Run `./scripts/verify.sh --environment <profile>`.
4. Report failed resources and relevant logs; never delete PVCs, CRDs,
   namespaces or customer databases as remediation.

## Upgrade or roll back

Read `docs/upgrades.md` or `docs/rollback.md`. Require a customer-confirmed
database backup before applying an upgrade with migrations. Use only exact
versions committed to `releases/stable.yaml`; never invent or overwrite a
published version.

## Guardrails

- Never create node labels or choose placement for the customer.
- Never install ingress-nginx when `ingressNginx.enabled=false`.
- Never request or retain cluster access for Phoenix engineers.
- Never decode, log or commit secrets.
- Never delete Jobs, PVCs, CRDs, namespaces or customer databases.
- Never treat a successful Helm command as completion until verification passes.
