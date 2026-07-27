# Prerequisites

## Tools

- Kubernetes 1.28 or newer
- Helm 3.18
- Helmfile 0.171
- kubectl compatible with the cluster
- kubeconform for local schema validation

`mise install` installs the versions declared in `.mise.toml`.

## Cluster

The installing identity must be able to create namespaced workloads, Secrets,
Services, Jobs, PVCs and RBAC resources. OpenSandbox also installs CRDs and
cluster-scoped RBAC.

A default StorageClass, or an explicit StorageClass for every enabled PVC, is
required whenever bundled Redis, PostgreSQL, Cortex or Workflow Engine
persistence is enabled.

The customer chooses node labels, tolerations and affinity. This repository
provides no scheduling defaults beyond resource requests.

## Network

Cluster workloads require access to:

- public GHCR and any referenced upstream image registries;
- the customer PostgreSQL endpoint;
- the customer Redis endpoint when external Redis is selected;
- Git and model-provider endpoints required by enabled workflows.

The Phoenix team does not require access to the customer cluster.
