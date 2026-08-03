---
name: install-phoenix-byoc
description: Validate, install, upgrade, verify, and troubleshoot Phoenix from the phoenix-byoc repository in a customer-owned Kubernetes cluster. Use for a prepared BYOC installation package, external PostgreSQL, optional bundled services, ingress and scheduling configuration, private registry mirroring, safe rollback preparation, or agent-driven BYOC operation.
---

# Install Phoenix BYOC

Operate the checked-out `phoenix-byoc` repository without taking ownership of
customer infrastructure. Treat kube-context selection, database changes and
Helm apply operations as approval boundaries.

## Prepare

1. Locate the repository root containing `helmfile.yaml.gotmpl`.
2. Read `BYOC_CONTRACT.md`, `AGENTS.md`, `docs/prerequisites.md`, and
   `docs/installation.md`.
3. Inspect `release.yaml` and report its channel and source environment.
4. Ask the user to identify the intended kube-context and namespace when they
   are not already explicit. Never switch context automatically.
5. Require populated `values.yaml` and `values.secrets.yaml`. When either is
   absent, stop because the installation package is incomplete.
6. Never display, retain or commit populated secret values.

## Configure

1. Read `values.yaml`.
2. Preserve the customer's PostgreSQL ownership, ingress, node placement,
   StorageClass and registry decisions.
3. Use `./scripts/images.sh list` for the exact runtime inventory.
4. When the customer mirrors images, use `./scripts/images.sh mirror --to
   <registry/path>` and set only `imageRegistry` plus `imagePullSecrets`.
5. Do not change `release.yaml`.

## Validate and apply

1. Run `./scripts/preflight.sh`.
2. Run `./scripts/render.sh`.
3. Inspect `.rendered/all.yaml` without printing rendered Secret values.
4. Report the release, current context, namespace, enabled bundled components
   and warnings.
5. Obtain explicit user confirmation.
6. Run `./scripts/install.sh --namespace <approved-namespace>`.
7. Report failed resources and relevant logs; never delete PVCs, CRDs,
   namespaces or customer databases as remediation.

## Upgrade or roll back

Read `docs/upgrades.md` or `docs/rollback.md`. Require a customer-confirmed
database backup before applying an upgrade with migrations. Use only exact
versions committed to `release.yaml`.

## Guardrails

- Never create node labels or choose placement for the customer.
- Never install ingress-nginx when `ingressNginx.enabled=false`.
- Never request or retain cluster access for Phoenix engineers.
- Never decode, log or commit secrets.
- Never delete Jobs, PVCs, CRDs, namespaces or customer databases.
- Never treat a successful Helm command as completion until verification passes.
