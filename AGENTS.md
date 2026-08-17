# AI agent instructions

These instructions are vendor-neutral and apply to any AI agent operating this
repository.

Before any mutation:

1. Read `BYOC_CONTRACT.md` and `docs/installation.md`.
2. Read `release.yaml` and the selected `--values` file.
3. Confirm that the selected `--secrets` file exists without printing it.
4. Export `PHOENIX_BYOC_NAMESPACE`, `PHOENIX_BYOC_VALUES_FILE` and
   `PHOENIX_BYOC_SECRETS_FILE`, then run `./scripts/preflight.sh`.
5. Run `./scripts/render.sh` with the same environment.
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
