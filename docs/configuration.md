# Configuration

Customer configuration lives in `values.yaml`; credentials live in
`values.secrets.yaml`.

## Scheduling

`scheduling.nodeSelector`, `scheduling.tolerations` and
`scheduling.affinity` are passed to Phoenix workloads and bundled data
services. Empty values leave placement to the cluster scheduler.

Sandbox sizes are configured under `scheduling.sandboxResourceClasses`.
Confirm that at least one node can satisfy every enabled class.

## Images

`releases/stable.yaml` owns public image repositories and tags. Do not override
them during a supported installation. `imagePullSecrets` exists for testing a
private pre-release registry.

## Ingress

`ingressNginx.enabled` controls installation of the ingress controller.
Individual application ingress resources are controlled under `ingress.*`.

## Secrets

`values.secrets.yaml` supplies the existing secret and database fields of the
application charts. There is no additional BYOC runtime Secret or configuration
translation layer.

`secrets.application.internalServiceTokens` is an advanced override. Leave it
empty to derive the Workflow Engine service identity from
`secrets.application.workflowEngineToken`.
