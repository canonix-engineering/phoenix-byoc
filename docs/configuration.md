# Configuration

Customer configuration and secrets are explicit `--values` and `--secrets`
inputs to the installer. Start from the complete files under `examples/`.

`release.yaml` and `defaults/values.yaml` are owned by Phoenix and must not be
edited during a supported installation.

## Component selection

- `opensandboxController.enabled`: install the cluster-wide OpenSandbox
  controller, or reuse an explicitly customer-provided compatible controller.
- `postgresql.bundled.enabled`: install PostgreSQL or use the externally
  configured PostgreSQL service.
- `redis.bundled.enabled`: deploy or omit bundled Redis.
- `cortex.bundled.enabled`: deploy or omit Cortex PostgreSQL.
- `clickhouse.bundled.enabled`: deploy or omit ClickHouse.
- `ingressNginx.enabled`: install or omit ingress-nginx.
- `postgresql.hooks.*`: let Phoenix hooks provision databases and run
  migrations, or delegate both tasks to the customer.

The OpenSandbox controller watches cluster-scoped CRDs. A second controller in
another namespace would reconcile the same resources and must not be installed.
On a fresh customer cluster, keep `opensandboxController.enabled=true`. Set it
to `false` only when the cluster already contains the compatible OpenSandbox
CRDs and an existing cluster-wide controller that should manage Phoenix
sandboxes. Preflight checks that all required CRDs exist and never changes their
Helm ownership.

## Bundled data-service versions

The current release installs these exact versions when the corresponding
bundled component is enabled:

| Component | Helm chart | Runtime image |
| --- | --- | --- |
| PostgreSQL | `2.0.4` | `postgres:18.4-trixie` |
| Redis | `1.6.18` | `redis:8.8.0` |
| Cortex PostgreSQL | `0.1.0` | `cortex-postgresql:61b95bb` |
| ClickHouse | `0.1.0` | `clickhouse-server:25.1-alpine` pinned by the digest in `release.yaml` |

`release.yaml` is the authoritative source. The table documents the current
release and must be updated together with it.

## Scheduling

`scheduling.nodeSelector`, `scheduling.tolerations` and
`scheduling.affinity` are passed to Phoenix workloads and bundled data
services. Empty values leave placement to the cluster scheduler.

Sandbox sizes are configured under `scheduling.sandboxResourceClasses`.
Confirm that at least one node can satisfy every enabled class.

## Images

`release.yaml` owns image names, tags and the pinned ClickHouse digest.
`imageRegistry` changes only their registry prefix after all ten images are
mirrored. `imagePullSecrets` names
Kubernetes pull secrets used by static Phoenix workloads and dynamic OpenSandbox
Pods.

For direct pulls from the Phoenix private ECR, set
`registry.ecrRefresh.enabled=true`, leave `imageRegistry` empty, and include
`registry.ecrRefresh.pullSecretName` in `imagePullSecrets`. The helper creates
the pull Secret, populates it before Phoenix workloads start, and refreshes its
12-hour ECR token on `registry.ecrRefresh.schedule` (every six hours by default).

The read-only IAM credentials can come from the protected
`secrets.registry.ecr` values or from a pre-created Secret selected by
`registry.ecrRefresh.credentialsSecretName`. An existing Secret must contain
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optional `AWS_SESSION_TOKEN`.
It may be managed by an ExternalSecret.

## Ingress

`ingressNginx.enabled` controls installation of the ingress controller.
Individual application ingress resources are controlled under `ingress.*`.

## Secrets

The file selected with `--secrets` supplies the existing secret and database
fields of the application charts. When direct ECR refresh is enabled without
an existing credentials Secret, it also supplies the read-only IAM access key
used by the refresh helper. The populated file and `.rendered/all.yaml` must
remain protected because both contain that long-lived credential.

Bundled PostgreSQL, Redis, Cortex PostgreSQL and ClickHouse URLs are derived
automatically. External services require explicit URLs or credentials.

Phoenix Web also requires the compatibility `application.cortex.host`,
`application.spaHost`, `application.mailer.*` and the matching application
secret fields shown in the example secrets file. The complete example already
contains the Cortex compatibility value; no Cortex HTTP service is installed.

`secrets.application.internalServiceTokens` is an advanced override. Leave it
empty to derive the Workflow Engine service identity from
`secrets.application.workflowEngineToken`.
