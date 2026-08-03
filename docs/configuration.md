# Configuration

Customer configuration lives in `values.yaml`; credentials live in
`values.secrets.yaml`.

`release.yaml` and `defaults/values.yaml` are owned by Phoenix and must not be
edited during a supported installation.

## Component selection

- `postgresql.bundled.enabled`: install PostgreSQL or use the externally
  configured PostgreSQL service.
- `redis.bundled.enabled`: deploy or omit bundled Redis.
- `cortex.bundled.enabled`: deploy or omit Cortex PostgreSQL.
- `ingressNginx.enabled`: install or omit ingress-nginx.
- `postgresql.hooks.*`: let Phoenix hooks provision databases and run
  migrations, or delegate both tasks to the customer.

## Scheduling

`scheduling.nodeSelector`, `scheduling.tolerations` and
`scheduling.affinity` are passed to Phoenix workloads and bundled data
services. Empty values leave placement to the cluster scheduler.

Sandbox sizes are configured under `scheduling.sandboxResourceClasses`.
Confirm that at least one node can satisfy every enabled class.

## Images

`release.yaml` owns image names and tags. `imageRegistry` changes only their
registry prefix after all nine images are mirrored. `imagePullSecrets` names
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

`values.secrets.yaml` supplies the existing secret and database fields of the
application charts. When direct ECR refresh is enabled without an existing
credentials Secret, it also supplies the read-only IAM access key used by the
refresh helper. The populated file and `.rendered/all.yaml` must remain
protected because both contain that long-lived credential.

Bundled PostgreSQL, Redis and Cortex URLs are derived automatically. External
services require explicit URLs or credentials.

Phoenix Web also requires `application.cortex.host`,
`application.clickhouse.url`, `application.mailer.*` and the four matching
application secret fields shown in `values.secrets.yaml.example`. These values
are validated during render because the current application image refuses to
start when any of them is empty.

`secrets.application.internalServiceTokens` is an advanced override. Leave it
empty to derive the Workflow Engine service identity from
`secrets.application.workflowEngineToken`.
