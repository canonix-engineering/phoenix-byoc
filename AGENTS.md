# AI agent instructions

These instructions are vendor-neutral and apply to any AI agent operating this
repository.

Before any mutation:

1. Read `BYOC_CONTRACT.md` and `docs/installation.md`.
2. Read `release.yaml` and the selected `--values` file.
3. Confirm that the selected `--secrets` path is not tracked by Git. It may be
   absent only when the user explicitly selected `--generate-secrets`; the
   installer then creates it from the current example.
4. When the user explicitly requests internal secret generation, confirm that
   all bundled dependencies are enabled. Use `install.sh --generate-secrets`;
   do not run standalone preflight before the file has been created,
   synchronized and its `GENERATE_*` and `DERIVE_*` markers have been resolved.
5. Otherwise export `PHOENIX_BYOC_NAMESPACE`, `PHOENIX_BYOC_VALUES_FILE` and
   `PHOENIX_BYOC_SECRETS_FILE`, then run `./scripts/preflight.sh` and
   `./scripts/render.sh` with the same environment.
6. Show the user the current context, namespace, enabled bundled dependencies
   OpenSandbox controller mode, ECR refresh mode and rendered manifest
   location.
7. Obtain explicit confirmation before running install, upgrade, rollback or
   uninstall commands.

Never:

- add or change node labels;
- install an ingress controller unless `ingressNginx.enabled=true`;
- create customer PostgreSQL users when both DB hooks are disabled;
- commit or print decoded secrets;
- switch kube-context automatically;
- delete PVCs, namespaces, CRDs or customer-managed databases;
- change Helm ownership annotations on existing OpenSandbox CRDs;
- claim success before `verify.sh` passes;
- print or decode IAM credentials or the managed ECR pull Secret.

Use exact versions from `release.yaml`. Never invent image or chart versions.
Report the release channel and source environment before applying it.
