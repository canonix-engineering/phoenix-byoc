# Phoenix BYOC contract

## Phoenix provides

- immutable public OCI Helm charts listed in `releases/stable.yaml`;
- immutable public container images for the same release;
- Helmfile orchestration and example values;
- configuration for the database hooks already provided by the application charts;
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
- application/API credentials required by the enabled workflows.

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

Bundled PostgreSQL is available only for kind/demo validation. It is not the
supported production database topology.

## Release support

Only chart and image versions committed to a non-development release manifest
are supported. Floating chart ranges, `latest` image tags and mutable releases
are prohibited.
