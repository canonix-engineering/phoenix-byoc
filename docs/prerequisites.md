# Prerequisites

## Tools

- Kubernetes 1.28 or newer
- Helm 3.18
- Helmfile 0.171
- kubectl compatible with the cluster
- kubeconform for local schema validation
- yq 4.49

`mise install` installs the versions declared in `.mise.toml`.

`crane` is optional and required only when verifying or mirroring runtime
images.

The AWS CLI is required when the release images are read from the supplier's
private Amazon ECR. Configure the supplier-provided read-only IAM credentials in
a local profile before running `images.sh ecr-login` or
`images.sh mirror --source-ecr-profile`. Those credentials are not Kubernetes
installation inputs.

## Cluster

The installing identity must be able to create namespaced workloads, Secrets,
Services, Jobs, PVCs and RBAC resources. OpenSandbox also installs CRDs and
cluster-scoped RBAC.

A default StorageClass, or an explicit StorageClass for every enabled PVC, is
required whenever bundled Redis, PostgreSQL, Cortex PostgreSQL, ClickHouse or
Workflow Engine persistence is enabled.

The customer chooses node labels, tolerations and affinity. Phoenix-owned
defaults do not force placement. The supplied example demonstrates the
placement used by the Phoenix `test` environment and must be replaced or
removed when the customer cluster uses different labels or taints.

## Optional Google Vertex AI prerequisites

Vertex mode is available only on GKE. Before setting `vertex.enabled=true`,
the customer must provide:

- GKE Workload Identity and the GKE metadata server for the sandbox nodes;
- a Google Service Account with `roles/aiplatform.user`;
- a `roles/iam.workloadIdentityUser` binding for the exact Phoenix namespace
  and Kubernetes ServiceAccount name;
- all configured `vertex.models.*` enabled in Model Garden;
- sandbox egress to the GKE metadata server and Vertex endpoints.

No Google service-account JSON key is an installation input.

## Network

Cluster workloads require access to:

- public GHCR and any referenced upstream image registries;
- the customer PostgreSQL endpoint;
- the customer Redis endpoint when external Redis is selected;
- Git and model-provider endpoints required by enabled workflows.

The Phoenix team does not require access to the customer cluster.
