# Installation

## Inputs supplied before installation

The installation package must already contain populated `values.yaml` and
`values.secrets.yaml`. Registry credentials and kubeconfig access are supplied
out of band. The customer does not select an installation profile.

The kubeconfig current context must point to the intended cluster:

```bash
kubectl config current-context
```

The installer never selects or changes a context.

## Install

Run the only installation command with the target namespace:

```bash
./scripts/install.sh --namespace phoenix
```

The script:

1. validates tools, configuration and cluster access;
2. rejects unresolved `CHANGE_ME` placeholders;
3. renders `.rendered/all.yaml`;
4. displays the release, context, namespace and bundled components;
5. installs or upgrades enabled Helm releases;
6. waits for Deployments and prints Pods, Services and PVCs.

The rendered file contains Kubernetes Secrets and remains local with mode
`0600`.

## Access the UI

When the customer has not enabled an Ingress, use port-forwarding:

```bash
kubectl -n phoenix port-forward service/phoenix-web-frontend 8080:80
```

Open <http://localhost:8080>.
