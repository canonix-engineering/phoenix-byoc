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

## Phoenix chart versions

The current release installs these exact Phoenix-owned chart versions:

| Component | Helm chart version |
| --- | --- |
| Cortex PostgreSQL | `0.1.0` |
| OpenSandbox controller | `0.2.0` |
| Phoenix Gateway | `0.2.0` |
| Phoenix Web | `0.2.2` |
| Phoenix Web Frontend | `0.1.0` |
| Phoenix Workflow Engine | `0.2.1` |
| PostgreSQL bootstrap (included in this repository) | `0.1.0` |

The chart version is independent from the runtime image tag. Both are pinned
in `release.yaml` and must be updated as one tested release.

## Scheduling

`scheduling.nodeSelector`, `scheduling.tolerations` and
`scheduling.affinity` are passed to Phoenix workloads and bundled data
services. Empty values leave placement to the cluster scheduler.

Dynamic sandbox placement and sizes are configured separately under every
entry in `scheduling.sandboxResourceClasses`. Resource classes accept
`nodeSelector`, `tolerations`, `affinity` and `resources`. Confirm that at least
one matching node can satisfy every enabled class. See `docs/scheduling.md`.

The ECR token refresh Job and CronJob use the common `scheduling.*` placement.
The optional ingress controller uses its dedicated
`ingressNginx.nodeSelector`, `ingressNginx.tolerations` and
`ingressNginx.affinity` values.

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

## Phoenix Web runtime

`application.actionCableAllowedOrigins` is passed to Phoenix Web as
`ACTION_CABLE_ALLOWED_ORIGINS`. Use a comma-separated list of allowed WebSocket
origins, including the scheme, for example
`https://phoenix.customer.example`.

`application.skipCsrf` controls the existing `web.skipCsrf` chart setting. The
example uses `true` to match the source `test` environment. Set it to `false`
after CSRF behavior has been validated for the customer's final ingress and
application topology.

Mail delivery values are passed through `application.mailer`:

- `from` and `domain` configure the sender and Mailgun domain;
- `deliveryMethod` is passed as `MAIL_DELIVERY_METHOD`; an empty value keeps
  the application image's default delivery method;
- `smtp.address`, `port`, `userName`, `authentication`,
  `enableStarttlsAuto` and `heloDomain` are passed as their corresponding
  `SMTP_*` variables;
- `secrets.application.mailgunApiKey` and
  `secrets.application.smtpPassword` contain provider credentials.

Preflight requires the Mailgun domain and API key when `deliveryMethod` is
empty or `mailgun`. When it is `smtp`, the SMTP address and port are required;
an SMTP password is required when a username is configured.

## Claude Code through Google Vertex AI

`vertex.enabled` optionally routes sandboxed Claude Code agents through Google
Vertex AI. This mode is supported only on GKE with Workload Identity enabled.
It does not mount a Google service-account key.

The customer configures the non-secret values under `vertex`:

- `projectId`: GCP project used for Vertex requests;
- `region`: Vertex endpoint location;
- `serviceAccount.name`: Kubernetes ServiceAccount assigned to sandbox Pods;
- `serviceAccount.gcpServiceAccount`: Google Service Account impersonated by
  the Kubernetes ServiceAccount;
- `serviceAccount.create`: create and annotate the Kubernetes ServiceAccount,
  or reference one managed separately by the customer;
- `models.*`: Vertex model identifiers available in the customer's Model
  Garden.

The Google Service Account needs `roles/aiplatform.user`. The customer must
also grant `roles/iam.workloadIdentityUser` to
`serviceAccount:<PROJECT_ID>.svc.id.goog[<NAMESPACE>/<KSA_NAME>]`. When
`serviceAccount.create=false`, the existing Kubernetes ServiceAccount must
already carry the `iam.gke.io/gcp-service-account` annotation.

When `vertex.enabled=true`, the workflow-engine chart deliberately omits
`CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY` from sandbox credentials.
Those two fields in `values.secrets.yaml` may remain empty. Other provider and
Git credentials remain independent.

## Workflow execution limits

The customer-facing workflow settings are under `services.workflowEngine` and
`services.opensandbox`:

- `operator.maxConcurrentSandboxTasks` and
  `operator.maxConcurrentInProcessTasks` cap work admitted by each operator
  replica;
- `operator.inProcessWorkflowStepRunTimeout` controls deterministic-step
  timeout;
- `operator.resources` configures the operator Pod requests and limits;
- `artifactApiTokenTtl` configures artifact-token lifetime;
- `sdlcIncrementalReindexEnabled` controls incremental SDLC reindexing;
- `supervisor.enabled` enables the Phoenix Web callback, Redis handoff and
  supervisor sandbox resource class together; it is disabled by default to
  match the source `test` environment;
- `agentSandboxIdleTTL` controls how long a successfully completed agent
  sandbox remains available for runtime activation;
- `outputArchiveMaxBytes`, `outputArchiveMaxFiles`,
  `outputArchiveMaxSingleFileBytes` and `outputArchiveMaxTotalFileBytes` bound
  archives read from sandboxes.

These values are passed directly to the Phoenix Workflow Engine chart. They do
not change node labels, placement policy or cluster capacity.

The example also exposes the application workload resources observed in the
source `test` environment under `services.web.resources`,
`services.worker.resources`, `services.frontend.resources`,
`services.gateway.resources`, `services.workflowEngine.apiResources`,
`services.workflowEngine.operator.resources`,
`opensandboxController.resources`, and `cortex.bundled.resources`.

## Secrets

The file selected with `--secrets` supplies the existing secret and database
fields of the application charts. When direct ECR refresh is enabled without
an existing credentials Secret, it also supplies the read-only IAM access key
used by the refresh helper. The populated file and `.rendered/all.yaml` must
remain protected because both contain that long-lived credential.

For the complete bundled installation, pass `--generate-secrets` to
`install.sh`. If the selected file is absent, the installer creates it from
`examples/values.secrets.yaml`. If it exists, the current template is merged
into it with existing values taking priority. The installer then replaces
`GENERATE_HEX_32` and `GENERATE_HEX_64` markers for:

- the PostgreSQL superuser, application and internal workflow database roles;
- bundled Cortex PostgreSQL and ClickHouse;
- `secretKeyBase`, the agent harness, artifact API and Workflow Engine tokens;
- internal guardrails, JavaScript transform and tool invocation tokens;
- the Gateway entry in `internalServiceTokens`.

It replaces the explicit `DERIVE_*` markers with the PostgreSQL admin, Redis,
Cortex PostgreSQL and ClickHouse URLs and the internal service-token mapping.
Existing random values are preserved, while derived values are refreshed for
the selected namespace. Bundled Redis matches the source `test` environment and
has authentication disabled, so no Redis password is generated.

The marker mechanism is recursive. A new release may add any number of
`GENERATE_HEX_32` or `GENERATE_HEX_64` fields to the example without adding a
path-specific generator rule. A derived value still requires explicit release
logic because its format depends on service names, users, databases and the
selected namespace.

An empty string means that an optional external credential is not configured.
For example, `sessionToken` is empty for IAM user credentials and
`smtpPassword` is empty while Mailgun rather than authenticated SMTP is used.
It never means that the installer should derive a value.

ECR IAM keys, mail-provider credentials and agent/provider credentials are
never generated. External services require explicit URLs or credentials.
Replace optional external `CHANGE_ME_*` placeholders with empty strings when the
corresponding integration is disabled or supplied through an existing Secret;
preflight rejects every unresolved placeholder, includes its exact YAML path,
and never generates external credentials.

Phoenix Web also requires the compatibility `application.cortex.host`,
`application.spaHost`, `application.mailer.*` and the matching application
secret fields shown in the example secrets file. The complete example already
contains the Cortex compatibility value; no Cortex HTTP service is installed.

`secrets.application.internalServiceTokens` is an advanced override. Leave it
empty to derive the Phoenix Gateway service identity from
`secrets.application.workflowEngineToken`.
