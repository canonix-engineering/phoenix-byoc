# Installation

## Inputs supplied before installation

Copy the complete Kubernetes-neutral examples and replace every `CHANGE_ME`
value:

```bash
cp examples/values.yaml values.yaml
cp examples/values.secrets.yaml values.secrets.yaml
chmod 600 values.secrets.yaml
```

Registry credentials and kubeconfig access are supplied out of band. The
customer does not select an installation profile.

The kubeconfig current context must point to the intended cluster:

```bash
kubectl config current-context
```

The installer never selects or changes a context.

## Install

Run the only installation command with the target namespace:

```bash
./scripts/install.sh \
  --namespace phoenix \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml
```

The script:

1. validates tools, configuration and cluster access;
2. rejects empty files, unresolved `CHANGE_ME` placeholders and missing
   required merged values;
3. renders `.rendered/all.yaml`;
4. displays the release, context, namespace and bundled components;
5. installs or upgrades enabled Helm releases;
6. waits for Deployments and StatefulSets and prints Pods, Services and PVCs.

The rendered file contains Kubernetes Secrets and remains local with mode
`0600`.

The same explicit inputs are used for standalone verification:

```bash
./scripts/verify.sh \
  --namespace phoenix \
  --values ./values.yaml \
  --secrets ./values.secrets.yaml
```

When `registry.ecrRefresh.enabled=true`, Helmfile installs the ECR refresh helper
first. Its initial Job must successfully populate the configured pull Secret
before any Phoenix release that uses a private image is installed. The scheduled
CronJob then renews the token automatically.

## Access the UI

When the customer has not enabled an Ingress, use port-forwarding:

```bash
kubectl -n phoenix port-forward service/phoenix-web-frontend 8080:80
```

Open <http://localhost:8080>.
