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
5. Require a values file copied from `examples/`. The selected secrets file may
   be absent only when the user selected `--generate-secrets`; the installer
   then creates it from the current example. Internal `GENERATE_HEX_*` and
   `DERIVE_*` markers may remain only for that workflow.
6. Never display, retain or commit populated secret values.

## Configure

1. Read the selected values file.
2. Preserve the customer's PostgreSQL ownership, ingress, node placement,
   StorageClass and registry decisions.
3. Use `./scripts/images.sh list` for the exact runtime inventory.
4. When the customer mirrors images, use `./scripts/images.sh mirror --to
   <registry/path>` and set only `imageRegistry` plus `imagePullSecrets`.
5. When direct ECR refresh is enabled, verify that `imageRegistry` is empty,
   `imagePullSecrets` contains the managed Secret name, and the IAM credential
   source exists without printing or decoding it.
6. Preserve `opensandboxController.enabled`. When it is `false`, require an
   existing compatible cluster-wide controller and CRDs; never change their
   Helm ownership annotations.
7. Do not change `release.yaml`.
8. For a complete bundled installation, `--generate-secrets` creates or
   reconciles the selected secrets file, fills `GENERATE_HEX_*` internal
   passwords and tokens, and resolves known `DERIVE_*` values. Confirm that all
   four bundled dependencies are enabled and that the selected path is not
   tracked by Git. It never generates IAM, mail-provider or agent-provider
   credentials.

## Validate and apply

1. Without secret generation, export the approved namespace and selected file
   paths as `PHOENIX_BYOC_NAMESPACE`, `PHOENIX_BYOC_VALUES_FILE` and
   `PHOENIX_BYOC_SECRETS_FILE`, then run `./scripts/preflight.sh` and
   `./scripts/render.sh` with the same environment.
2. With secret generation, do not run standalone preflight against unresolved
   internal placeholders. After explicit approval, let `install.sh
   --generate-secrets` generate, validate and render in that order.
3. Inspect `.rendered/all.yaml` without printing rendered Secret values.
4. Report the release, current context, namespace, enabled bundled components
   and warnings.
5. Obtain explicit user confirmation.
6. Run `./scripts/install.sh --namespace <approved-namespace> --values
   <values-path> --secrets <secrets-path>` and add `--generate-secrets` only for
   the approved bundled-generation workflow.
7. Report failed resources and relevant logs; never delete PVCs, CRDs,
   namespaces or customer databases as remediation.
8. Explain that a fresh database has no administrator account. After successful
   verification, offer the procedure in
   `docs/installation.md#create-the-initial-administrator` as a separate
   database mutation and obtain explicit confirmation before running it.

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
