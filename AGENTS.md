# Agent instructions

Operate only on the Kubernetes context and namespace explicitly approved by the
user.

Before any mutation:

1. Read `BYOC_CONTRACT.md` and `docs/installation.md`.
2. Read the selected profile and both local values files.
3. Run `./scripts/preflight.sh --environment <environment>`.
4. Run `./scripts/render.sh --environment <environment>`.
5. Show the user the current context, namespace, enabled bundled dependencies
   and rendered manifest location.
6. Obtain explicit confirmation before running install, upgrade, rollback or
   uninstall commands.

Never:

- add or change node labels;
- install an ingress controller unless `ingressNginx.enabled=true`;
- create customer PostgreSQL users when both DB hooks are disabled;
- commit or print decoded secrets;
- switch kube-context automatically;
- delete PVCs, namespaces, CRDs or customer-managed databases;
- claim success before `verify.sh` passes.

Use exact versions from `releases/stable.yaml`. Stop if the release channel is
`development`, unless the user explicitly authorizes pre-release validation.
