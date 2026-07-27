# kind validation

The `kind` profile enables ingress-nginx, standalone PostgreSQL, standalone
Redis and Cortex PostgreSQL. It is for installation acceptance, not production.

After a stable release contains public images:

```bash
kind create cluster --name phoenix-byoc
./scripts/bootstrap.sh
# Replace all placeholders in values.secrets.yaml.
./scripts/install.sh --environment kind
```

The profile uses the public image references in `releases/stable.yaml` with
`IfNotPresent`. Internal developers may override those references in their
ignored `values.yaml` when testing locally built images.

Delete the test cluster only after confirming its exact name:

```bash
kind delete cluster --name phoenix-byoc
```
