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

The supplier provides per-customer AWS access keys for a read-only IAM user.
Store them in an AWS CLI profile using your approved credential-storage process;
do not put them in `values.yaml`, `values.secrets.yaml`, or Kubernetes.

Install the AWS CLI and `crane`, authenticate `crane` to the destination
registry, then copy all nine images. The mirror command obtains a short-lived
source ECR token using the selected AWS profile without printing it:

```bash
./scripts/images.sh mirror \
  --source-ecr-profile phoenix-byoc-source \
  --to registry.customer.example/phoenix
```

You may authenticate to the source separately when diagnosing access:

```bash
./scripts/images.sh ecr-login --profile phoenix-byoc-source
./scripts/images.sh verify
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

Amazon ECR authorization tokens expire after 12 hours. The source IAM user is
therefore intended for copying the release into the customer registry. Do not
turn its short-lived token into a permanent Kubernetes `imagePullSecret`.

Direct pulls from the supplier ECR are supported only when the customer configures
node-level dynamic ECR authentication, such as an ECR kubelet credential provider.
That cluster-specific configuration remains customer-owned.

For a customer-owned destination Amazon ECR, authenticate `crane` separately
with credentials for that destination:

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
