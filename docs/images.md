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

The optional direct-ECR refresher bootstraps with digest-pinned public AWS CLI
and Kubernetes `kubectl` images. Cluster nodes must be able to pull from
`public.ecr.aws` and `registry.k8s.io` before the private ECR pull Secret exists.

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

For a mirrored customer registry, create registry credentials in the target
namespace before installation or configure node-level registry access. Phoenix
does not request, store or rotate credentials for that customer registry.

When `imagePullSecrets` is non-empty, `install.sh` verifies those Secrets and
links them to the namespace default ServiceAccount. This is required because
OpenSandbox creates runtime Pods dynamically. Static Phoenix workloads receive
the same pull-secret names through their Helm values.

## Pull directly from the Phoenix ECR

Direct pull is optional and disabled by default. It uses the same per-customer
read-only IAM user as mirroring. Enable the managed refresh mechanism in
`values.yaml` (the same overlay is available as
`examples/direct-ecr.values.yaml`):

```yaml
imageRegistry: ""
imagePullSecrets:
  - name: phoenix-ecr-pull

registry:
  ecrRefresh:
    enabled: true
    region: us-east-1
    schedule: "0 */6 * * *"
    pullSecretName: phoenix-ecr-pull
    credentialsSecretName: ""
```

With an empty `credentialsSecretName`, place the IAM credentials in the
protected, untracked `values.secrets.yaml`:

```yaml
secrets:
  registry:
    ecr:
      accessKeyId: <provided-access-key-id>
      secretAccessKey: <provided-secret-access-key>
      sessionToken: ""
```

Alternatively, set `credentialsSecretName` to a pre-created Kubernetes Secret
containing `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optional
`AWS_SESSION_TOKEN`. The Secret may be produced by an ExternalSecret, but it must
exist in the target namespace before installation.

The helper release:

1. creates the `kubernetes.io/dockerconfigjson` pull Secret;
2. runs an initial refresh Job before any private Phoenix image is pulled;
3. refreshes the ECR authorization token every six hours by default;
4. grants its ServiceAccount permission to update only the configured pull
   Secret.

Because the helper images are public bootstrap dependencies, environments that
cannot reach their public registries must use the mirroring path instead.

AWS documents ECR authorization tokens as valid for 12 hours. Keep the refresh
schedule comfortably below that lifetime. The long-lived IAM access key remains
in its credentials Secret; only the short-lived ECR token is written to the pull
Secret.

After installation, verify the CronJob and the managed Secret without decoding
either credential:

```bash
kubectl -n phoenix get cronjob/ecr-pull-secret-refresh
kubectl -n phoenix get secret/phoenix-ecr-pull
```

Node-level ECR credential providers remain a supported customer-owned
alternative. In that case leave `registry.ecrRefresh.enabled=false` and do not
configure the managed pull Secret.

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
