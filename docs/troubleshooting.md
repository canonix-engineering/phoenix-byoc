# Troubleshooting

## Manifest rendering fails

Render with the same explicit inputs without applying any resources:

```bash
PHOENIX_BYOC_NAMESPACE=phoenix \
PHOENIX_BYOC_VALUES_FILE=./customer-values.yaml \
PHOENIX_BYOC_SECRETS_FILE=./customer-secrets.yaml \
  ./scripts/render.sh
```

Replace all reported placeholders or missing fields in the selected files.
Confirm that each external or bundled service matches the intended mode.

## Chart pull is unauthorized

Confirm that the referenced GHCR package is public and that the exact version
exists. Run `./scripts/images.sh verify` for runtime images.

## OpenSandbox CRD is owned by another release

OpenSandbox CRDs are cluster-scoped and can belong to only one Helm release.
Do not change their Helm annotations. If the cluster's existing compatible
controller is intended to manage the BYOC namespace, set:

```yaml
opensandboxController:
  enabled: false
  crds:
    install: false
```

On a fresh customer cluster, keep both fields enabled so Phoenix installs the
controller and CRDs itself.

## Direct ECR pulls fail

Check the refresh schedule and recent Jobs without printing either Secret:

```bash
kubectl -n phoenix get cronjob/ecr-pull-secret-refresh
kubectl -n phoenix get jobs -l app.kubernetes.io/name=ecr-pull-secret-refresh
```

If the refresh Job reports `AccessDenied`, confirm that the per-customer IAM
access key is active and still has `ecr:GetAuthorizationToken`. If the pull
Secret is missing, confirm that `registry.ecrRefresh.pullSecretName` is also
listed under `imagePullSecrets`.

## Phoenix Web migration fails

Inspect:

```bash
kubectl -n phoenix logs job/phoenix-web-db-init --all-containers
```

Verify the PostgreSQL host, credentials and hook settings.

## Application reports that PostgreSQL refused TLS

With bundled PostgreSQL, keep `postgresql.bundled.enabled=true`; BYOC
automatically renders `sslmode=disable` for application connections. With an
external PostgreSQL service, set `postgresql.external.sslmode` to the mode
required by the customer database. Do not disable certificate verification for
an external production database merely to bypass a connection error.

## Pods remain Pending

Check node selectors, taints, PVC binding and sandbox resource requests:

```bash
kubectl -n phoenix describe pod POD
kubectl get storageclass
```

## Redis connection fails

Ensure the URL scheme, credentials, service hostname and database number match
the selected Redis mode.

## Ingress has no address

An application Ingress does not install a controller. Enable optional
ingress-nginx or configure the customer's ingress class and load balancer.
