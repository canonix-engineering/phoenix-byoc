# Troubleshooting

## Manifest rendering fails

Run:

```bash
./scripts/render.sh
```

Replace all placeholders and confirm that `values.yaml` matches the external or
bundled services.

## Chart pull is unauthorized

Confirm that the referenced GHCR package is public and that the exact version
exists. Run `./scripts/images.sh verify` for runtime images.

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
