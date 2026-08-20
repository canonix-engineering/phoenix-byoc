# Installation

## Inputs supplied before installation

Copy `values.yaml` and replace every `CHANGE_ME` value in it. The supplied
placement matches the Phoenix `test` environment; replace or remove the
`canonix.ai/node-role` selector and toleration for a customer cluster that uses
different node labels or taints:

```bash
cp examples/values.yaml values.yaml
cp examples/values.secrets.yaml values.secrets.yaml
chmod 600 values.secrets.yaml
```

Copying `values.secrets.yaml` is optional. When the selected file does not
exist, `install.sh --generate-secrets` creates it from the current example with
mode `0600`, generates internal values and stops at preflight until required
external credentials are filled. Copying it before the first run lets those
credentials be supplied before installation begins.

For the default direct-ECR and Mailgun configuration, the customer supplies:

- `secrets.registry.ecr.accessKeyId` and `secretAccessKey`, unless
  `registry.ecrRefresh.credentialsSecretName` selects an existing Kubernetes
  Secret; replace both placeholders with empty strings when they are unused;
- `secrets.application.mailgunApiKey`, or the SMTP password when SMTP is
  selected; replace the unused Mailgun placeholder with an empty string;
- only the Claude, Anthropic, GitHub, OpenAI or Gemini credentials required by
  the workflows the customer intends to use.

Do not replace the PostgreSQL, Cortex, ClickHouse or internal application
`GENERATE_HEX_32`, `GENERATE_HEX_64` and `DERIVE_*` markers when using
`--generate-secrets`. Empty strings are reserved for optional external
credentials that are not used by the selected configuration.

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
  --secrets ./values.secrets.yaml \
  --generate-secrets
```

`--generate-secrets` currently applies to the complete bundled installation:
PostgreSQL, Redis, Cortex PostgreSQL and ClickHouse must all be enabled. It:

1. creates the selected secrets file from `examples/values.secrets.yaml` when
   it does not exist;
2. adds fields introduced by the current example while preserving existing
   values and customer-specific extra fields;
3. replaces every supported `GENERATE_HEX_*` marker with a random value;
4. preserves every already populated password and token;
5. replaces the explicit `DERIVE_*` markers with the PostgreSQL admin, Redis,
   Cortex PostgreSQL and ClickHouse URLs and the internal service-token mapping
   computed from the namespace and selected values;
6. writes the result back to `values.secrets.yaml` with mode `0600` without
   printing any secret value.

The installer refuses to populate a Git-tracked secrets file. A repeated run
does not rotate generated credentials. If the namespace changes, only the
derived internal URLs are refreshed. New external `CHANGE_ME_*` fields are
added but never generated; preflight lists their exact paths and stops until
they are populated or explicitly set to an empty string when optional.

The script then:

1. validates tools, configuration and cluster access;
2. rejects empty files, remaining `CHANGE_ME_*`, `GENERATE_*` or `DERIVE_*`
   markers and missing required merged values;
3. renders `.rendered/all.yaml`;
4. displays the release, context, namespace and bundled components;
5. installs or upgrades enabled Helm releases;
6. waits for Deployments and StatefulSets and prints Pods, Services and PVCs.

The rendered file contains Kubernetes Secrets and remains local with mode
`0600`.

For later upgrades, reuse the same generated secrets file and supply
`--generate-secrets` again. Existing random values are preserved, while new
fields from the release template are synchronized before validation.

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
twice and streamed to the Rails process; it is not included in the shell
command, environment or output.

```bash
./scripts/create-initial-admin.sh \
  --namespace phoenix-byoc \
  --enterprise-name "Customer name" \
  --enterprise-domain customer.example \
  --email admin@customer.example \
  --name "Platform Administrator"
```

The script displays the current kube-context and selected namespace, waits for
`deployment/phoenix-web` to become available, and then performs the one-time
application bootstrap. The operation is safe to repeat with the same
administrator. It does not reset the password of an existing account and
refuses to create a new initial owner after other users have been added.
