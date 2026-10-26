# Upgrade from Phoenix BYOC 0.2.1 to 0.2.2-rc.1

**Release candidate — AWS EKS rehearsal pending.** This procedure accompanies
`0.2.2-rc.1` (`development` channel). It is not a published stable release or a
message to send to the customer. After the `phoenix-byoc` rehearsal passes, the
stable delivery will include the final version, download link and checksums.

The upgrade keeps bundled PostgreSQL and Valkey and uses the existing ECR
credentials. The installer downloads the exact charts and images in
`release.yaml`. No application rebuild or registry migration is needed.

## 1. Keep the existing configuration

Finish active workflows and pause new submissions for the update. Keep the
existing namespace, tenant, storage, resource classes, node placement, domain,
registry credentials and provider settings. Customer GCP project, VM pool and
Workload Identity settings are retained when preparing the final instructions.
Do not replace existing values or secrets with the examples.

Use Bash and the tools in [Prerequisites](docs/prerequisites.md), including
Python 3.9 or newer for the AgentFS checks. Set the existing configuration path
and namespace; `phoenix-byoc` is the AWS rehearsal namespace:

```bash
set -euo pipefail
export BYOC_CONFIG=/absolute/path/to/existing-config
export BYOC_NAMESPACE=phoenix-byoc
test -f "$BYOC_CONFIG/values.yaml"
test -f "$BYOC_CONFIG/values.secrets.yaml"
kubectl config current-context
kubectl -n "$BYOC_NAMESPACE" get deployments,statefulsets,pvc
```

Confirm the intended cluster before applying. The installer does not select a
context. Release qualification runs only in the `phoenix-byoc` AWS EKS simulator;
no deployment or test in the customer's GCP environment is part of qualification.

## 2. Optional recovery checkpoint

A backup is optional if you accept the risk of losing data if an update fails.
For a recovery checkpoint, save the current values/secrets, installer version,
PostgreSQL databases and persistent volumes using your existing backup procedure.
Keep database and volume backups consistent by pausing writes. The installer does
not create backups. Store them privately; never include them in support messages.

## 3. Use the complete candidate directory

Extract the supplied candidate archive into a new directory, retaining the old
installer and configuration. Verify the archive's `.sha256` file and then its
internal file checksums:

```bash
sha256sum -c phoenix-byoc-0.2.2-rc.1.tar.gz.sha256
tar -xzf phoenix-byoc-0.2.2-rc.1.tar.gz
cd phoenix-byoc-0.2.2-rc.1
sha256sum -c SHA256SUMS
```

On macOS, use `shasum -a 256 -c` instead of `sha256sum -c`.
`DELIVERY.json` identifies the source commit and qualification status;
`image-index.json` and `chart-index.json` identify the pinned artifacts.
Do not substitute images from a moving branch.

## 4. Check AgentFS and publisher configuration

The release enables AgentFS and installs a FUSE node plugin by default. Linux
sandbox nodes need `/dev/fuse` and the permissions described in
[AgentFS prerequisites](docs/agentfs.md). The installer checks eligible node
capacity before updating Engine and preserves permissions for prior Agent images.

For the AWS rehearsal, reuse the cluster's existing FUSE provider by merging
this into the rehearsal values file:

```yaml
fuseDevicePlugin:
  install: false
```

This override is specific to a cluster with an existing provider; do not copy it
to a customer installation that needs BYOC to install the plugin. Do not install
or adopt a second provider. Keep the existing OpenSandbox controller selection.

Preserve the existing `application.agentBundles` configuration:

```yaml
application:
  agentBundles:
    namespace: agent-bundles
    globalPublisherUserIds: []
```

The empty allowlist above is the default, not an instruction to clear a populated
one. Keep existing publisher permissions. Remove obsolete `standaloneEnabled`
and `publicationEnabled` overrides if still present: the new applications always
require publication configuration.

`--generate-secrets` preserves existing passwords and tokens and generates a
missing `secrets.application.artifactPublisherToken`. It must be distinct from
the Workflow Engine and Artifact API service tokens. The charts supply the same
publisher token and namespace to Web, Engine and their migration hooks, using
the existing deployment tenant. No manual token rotation is required.

## 5. Apply the update

From the candidate directory:

```bash
set -o pipefail
umask 077
./scripts/install.sh \
  --namespace "$BYOC_NAMESPACE" \
  --values "$BYOC_CONFIG/values.yaml" \
  --secrets "$BYOC_CONFIG/values.secrets.yaml" \
  --generate-secrets 2>&1 | tee "$BYOC_CONFIG/upgrade-0.2.2-rc.1.log"
```

Do not add `--discard-redis-state` when upgrading from 0.2.1: Valkey is already
installed and its data is retained. Older Redis-based installations require the
separate [legacy migration procedure](docs/redis.md#existing-redis-installations).

Wait for the installer to finish before starting a workflow. Do not run two
installers at once. Web migrations run before Gateway and Engine. The new Web
migrations add overview settings and the `master-agent` toolbox kind. Existing
users are retained; do not run initial administrator creation during an upgrade.
Rendered manifests contain Secrets and must remain private.

A successful run exits with status zero and ends with
`Phoenix verification passed in namespace <your namespace>.`

## 6. Verify the AWS rehearsal

```bash
./scripts/verify.sh \
  --namespace "$BYOC_NAMESPACE" \
  --values "$BYOC_CONFIG/values.yaml" \
  --secrets "$BYOC_CONFIG/values.secrets.yaml"
helm list -n "$BYOC_NAMESPACE"
kubectl -n "$BYOC_NAMESPACE" get deployments,statefulsets,pods,pvc
```

Confirm existing records, PVC bindings and secrets remain intact. Sign in with
an existing account, open an existing app, publish/use an agent bundle, run a
workflow and download its artifact. Exercise a human-input answer and resume,
then verify AgentFS checkpoint capture and recovery. Check worker processing,
UI progress and FUSE capacity. Record these results before stable publication.

After qualification, provide the customer with the stable delivery and commands
using their existing namespace and settings. The customer applies the upgrade
and checks their normal workflows; Phoenix does not test in their GCP cluster.

## 7. If the update fails

Keep the maintenance window active. Preserve the installer log and failed
Job/Pod names, and resolve the reported cause before retrying the same candidate
with the same values/secrets. Share only redacted diagnostics.

Do not delete PVCs or namespaces, regenerate credentials or remove the FUSE
provider to force progress. Existing workflows can retain older Agent images;
keep their FUSE permissions and compatible OpenSandbox runtime. See
[AgentFS rollback restrictions](docs/agentfs.md#existing-workflows-and-rollback).
Helm rollback does not undo database migrations or restore a coordinated data
checkpoint. Choose recovery using the saved database/volume checkpoint and
matching application configuration before reverting application versions.
