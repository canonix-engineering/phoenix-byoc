# Container images

## Supported images

`release.yaml` pins all runtime images required by the platform:

1. `cortex-postgresql`
2. `phoenix-opensandbox-controller`
3. `phoenix-agent`
4. `phoenix-gateway`
5. `phoenix-lab`
6. `phoenix-opensandbox`
7. `phoenix-web`
8. `phoenix-web-frontend`
9. `phoenix-workflow-engine`

Print exact references:

```bash
./scripts/images.sh list
```

Images such as PostgreSQL, Redis, OpenSandbox execd/egress and init containers
come from the upstream charts. Inspect `.rendered/all.yaml` for the complete
deployment inventory.

## Use the release image locations

Leave this value empty:

```yaml
imageRegistry: ""
```

The cluster must be able to pull the references printed by `images.sh list`.
The current development snapshot records the exact references configured in
`cnx-dev-eks/test`. Authenticate to that registry or mirror the images before
installation. A stable customer release must use customer-accessible image
locations.

## Mirror to a customer registry

Install `crane`, authenticate to the destination registry, then copy all nine
images:

```bash
./scripts/images.sh mirror --to registry.customer.example/phoenix
```

Preview without copying:

```bash
./scripts/images.sh mirror \
  --to registry.customer.example/phoenix \
  --dry-run
```

The command preserves release-owned names and tags. Configure only the prefix:

```yaml
imageRegistry: registry.customer.example/phoenix
imagePullSecrets:
  - name: phoenix-registry
```

Create registry credentials in the target namespace before installation, or
configure node-level registry access. Phoenix does not request, store or rotate
customer registry credentials.

When `imagePullSecrets` is non-empty, `install.sh` verifies those Secrets and
links them to the namespace default ServiceAccount. This is required because
OpenSandbox creates runtime Pods dynamically. Static Phoenix workloads receive
the same pull-secret names through their Helm values.

For Amazon ECR, authenticate `crane` with:

```bash
aws ecr get-login-password --region REGION |
  crane auth login ACCOUNT.dkr.ecr.REGION.amazonaws.com \
    --username AWS \
    --password-stdin
```

EKS nodes may instead use their node IAM role. Cross-account registries also
require an ECR repository policy permitting the node role to pull.

## Verify availability

```bash
./scripts/images.sh verify

# Or verify the mirrored copies:
./scripts/images.sh verify \
  --registry registry.customer.example/phoenix
```
