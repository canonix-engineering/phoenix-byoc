# Installation

## Inputs supplied before installation

Copy the complete examples and replace every `CHANGE_ME` value. The supplied
placement matches the Phoenix `test` environment; replace or remove the
`canonix.ai/node-role` selector and toleration for a customer cluster that uses
different node labels or taints:

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

## Create the initial administrator

A fresh database does not contain an Enterprise or an administrator account,
and Phoenix Web does not expose public self-registration. Create the first
owner after the workloads are ready. The password is read from the terminal
and streamed to the Rails process; it is not included in the shell command or
printed by the command.

```bash
export PHOENIX_NAMESPACE=phoenix-byoc
export ENTERPRISE_NAME='Customer name'
export ENTERPRISE_PRIMARY_DOMAIN='customer.example'
export INITIAL_ADMIN_EMAIL='admin@customer.example'
export INITIAL_ADMIN_NAME='Platform Administrator'
printf 'Initial administrator password: ' >&2
IFS= read -r -s INITIAL_ADMIN_PASSWORD
printf '\n' >&2

printf '%s' "$INITIAL_ADMIN_PASSWORD" | kubectl -n "$PHOENIX_NAMESPACE" exec -i \
  deployment/phoenix-web -- env \
  ENTERPRISE_NAME="$ENTERPRISE_NAME" \
  ENTERPRISE_PRIMARY_DOMAIN="$ENTERPRISE_PRIMARY_DOMAIN" \
  INITIAL_ADMIN_EMAIL="$INITIAL_ADMIN_EMAIL" \
  INITIAL_ADMIN_NAME="$INITIAL_ADMIN_NAME" \
  /rails/bin/rails runner '
    password = STDIN.read
    ApplicationRecord.transaction do
      enterprise = Enterprise.first || Enterprise.create!(
        name: ENV.fetch("ENTERPRISE_NAME"),
        primary_domain: ENV.fetch("ENTERPRISE_PRIMARY_DOMAIN")
      )
      email = ENV.fetch("INITIAL_ADMIN_EMAIL").downcase
      administrator = User.find_by(email: email)
      if administrator
        raise "Existing administrator is not an owner of this Enterprise" unless
          administrator.enterprise_id == enterprise.id && administrator.enterprise_role == "owner"
        puts "Initial administrator already exists"
      else
        raise "Other users already exist; refusing initial-owner bootstrap" if User.exists?
        User.create!(
          email: email,
          name: ENV.fetch("INITIAL_ADMIN_NAME"),
          password: password,
          password_confirmation: password,
          enterprise: enterprise,
          enterprise_role: :owner
        )
        puts "Initial administrator created"
      end
    end
  '

unset INITIAL_ADMIN_PASSWORD
```

The operation is safe to repeat with the same administrator. It does not reset
the password of an existing account and refuses to create a new initial owner
after other users have been added.
