# Phoenix BYOC contract

## Phoenix provides

- immutable public OCI Helm charts listed in `release.yaml`;
- exact container image references for the release and tools to mirror them;
- bundled single-node ClickHouse, or configuration for an external ClickHouse;
- an optional in-cluster refresher for direct pulls from the Phoenix private ECR;
- Helmfile orchestration and example values;
- BYOC database bootstrap orchestration and the application database hooks;
- render, preflight, install and verification scripts;
- upgrade and rollback documentation.

## Customer provides

- a supported Kubernetes cluster and administrative access for installation;
- namespaces, StorageClasses and sufficient compute capacity;
- node labels, taints, tolerations and placement policy;
- a production PostgreSQL service, its backup policy and credentials;
- DNS, TLS certificates and the preferred ingress controller;
- Redis when bundled Redis is disabled;
- Cortex PostgreSQL when bundled Cortex is disabled;
- ClickHouse when bundled ClickHouse is disabled;
- a compatible cluster-wide OpenSandbox controller and CRDs when
  `opensandboxController.enabled=false`;
- application/API credentials required by the enabled workflows;
- protected storage for the per-customer IAM access key when direct ECR refresh
  is enabled.

## Explicitly out of scope

- production high availability;
- an observability stack;
- backup or restore automation for customer databases;
- automatic node labelling or infrastructure provisioning;
- installation of Twenty HQ, Mattermost or Headlamp;
- `postgresql-external`, which is an internal engineering LoadBalancer helper;
- access by Phoenix engineers to the customer cluster.

## Supported database ownership

The customer may enable the existing chart hooks and provide an administrative
PostgreSQL URL, or disable the hooks and create users/databases independently.
When the hooks are disabled, database provisioning and migrations are the
customer's responsibility.

Bundled PostgreSQL is optional and is not the supported production database
topology.

## Release support

Only chart and image versions committed to a stable `release.yaml`
are supported. Floating chart ranges, `latest` image tags and mutable releases
are prohibited.

Development snapshots may point to restricted source registries for validation.
They are not customer handoff releases until every artifact is accessible to
the customer and the release channel is changed to `stable`.
