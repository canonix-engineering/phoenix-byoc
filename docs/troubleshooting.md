# Troubleshooting

## Manifest rendering fails

Run:

```bash
./scripts/render.sh --environment default
```

Replace all placeholders and confirm that the selected profile matches the
external or bundled services.

## Chart pull is unauthorized

Confirm that the referenced GHCR package is public and that the exact version
exists. A supported release must be pullable without organization credentials.

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
