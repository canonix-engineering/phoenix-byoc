# AgentFS prerequisites and upgrades

This is release preparation. AgentFS is disabled in the current `0.2.1`
configuration. The next release must publish and pin Engine chart `0.2.6` or
later, the FUSE device-plugin chart, and compatible Engine/OpenSandbox and Agent
images before enabling `services.opensandbox.fuse.enabled`. Enabling it against
Engine chart `0.2.5` fails preflight and rendering instead of silently ignoring it.
Application versions are not changed by this preparation.

## Cluster requirements

Linux sandbox nodes must provide `/dev/fuse`. The node plugin advertises
`devic.es/fuse`; each AgentFS sandbox requests one allocation. The plugin is a
privileged DaemonSet that mounts only `/dev/fuse` and the kubelet device-plugin
directory and does not receive a Kubernetes API token. Its image is pinned by
digest in `release.yaml` and included in `scripts/images.sh list` and mirroring.

The OpenSandbox server adds `SYS_ADMIN`, unconfined AppArmor and permission for
the `fusermount3` setuid helper only to exact allowlisted Agent images. Agent
containers remain non-root and are not privileged. Lab and other images do not
receive those permissions. The cluster admission policy must permit this setup;
the installer does not change namespace security policies or node labels.

For GCP, use eligible Linux nodes in GKE Standard. The usual
[GKE Autopilot restrictions](https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-security)
block the required privileged node plugin, host paths and sandbox capabilities;
this deployment is not qualified for Autopilot or GKE Sandbox. Verify the
customer's cluster mode and admission policies before handing over the release.

## Install or reuse the node plugin

Once AgentFS is enabled by the release, the installer manages one
`fuse-device-plugin` Helm release in `phoenix-system` by default. The plugin
selects Linux nodes. Narrow `fuseDevicePlugin.nodeSelector` and its `tolerations`
to the customer's sandbox pools where needed; retain `kubernetes.io/os: linux`.
All Linux resource classes used by Agents need eligible nodes with FUSE.

If the cluster already has a plugin providing `devic.es/fuse`, reuse it:

```yaml
fuseDevicePlugin:
  install: false
```

For example, the shared plugin in the Phoenix EKS simulation cluster is already
managed outside BYOC. Do not install a second plugin there. Reuse mode omits
this Helm release entirely, so it cannot uninstall or adopt the existing one.
An installation in another namespace must also reuse the cluster's plugin.
Only its original owner should update or remove it.

When mirroring images to a private registry, the plugin namespace must already
have pull access through node credentials or its default ServiceAccount's
`imagePullSecrets`. This infrastructure chart does not inject the application's
pull secret. The installer waits for the plugin and fails before updating Engine
if the mirrored image cannot be pulled.

## Upgrade behavior

Use the normal `scripts/install.sh` command with existing values and secrets.
Python 3 is required, using only its standard library for the AgentFS checks.
Before applying workloads the installer:

1. Validates the Engine chart and FUSE settings.
2. Reads the deployed OpenSandbox image allowlist and merges it with
   `services.opensandbox.fuse.retainedImages`. Read or parse errors stop the
   update; they are never interpreted as an empty list.
3. Refuses to install a second FUSE provider when an existing provider is
   detected. It never changes Helm ownership.
4. Installs and waits for the managed plugin, or verifies the existing plugin's
   node capacity. Each configured Linux sandbox class must have a Ready,
   schedulable node advertising FUSE and tolerating its placement constraints.
5. Updates the applications with current and retained exact Agent image refs.
   Verification checks the deployed allowlist, node capacity, and (when managed)
   the plugin's Helm version, image and rollout.

The capacity check is not a full scheduler simulation: resource availability,
custom affinity and admission webhooks are also exercised by the release's
functional sandbox tests. Plugin readiness alone does not qualify an upgrade.

For an offline render, explicitly provide any historical image refs in
`services.opensandbox.fuse.retainedImages` or
`PHOENIX_AGENTFS_RETAINED_IMAGES_JSON`. A standalone render does not query the
cluster. For direct Helmfile operations, capture the deployed list first using
the same namespace and context:

```bash
export PHOENIX_BYOC_NAMESPACE=phoenix
export PHOENIX_BYOC_VALUES_FILE="$PWD/values.yaml"
export PHOENIX_BYOC_SECRETS_FILE="$PWD/values.secrets.yaml"
export PHOENIX_AGENTFS_CONTEXT="$(kubectl config current-context)"
PHOENIX_AGENTFS_RETAINED_IMAGES_JSON=$(./scripts/agentfs.sh retain)
export PHOENIX_AGENTFS_RETAINED_IMAGES_JSON
```

Prefer `install.sh`, which also enforces the installation order and checks.

## Existing workflows and rollback

Existing workflows keep their pinned Agent image, including when creating a new
sandbox for a later step. Upgrades A → B → C and rollbacks must preserve A and B
in the FUSE allowlist. The installer preserves the whole previous list and does
not prune it automatically.

Keep the plugin, compatible OpenSandbox server and allowlist until all workflows
and retained sessions using AgentFS have finished. Do not roll back to an Engine
or BYOC version that lacks this support while these workflows exist. Do not
delete or recreate their BatchSandboxes, workspace databases or volumes, and do
not disable FUSE as a shortcut. Removing an obsolete image permission is a
separate manual operation after confirming no workflow or session needs it.

No migration of existing workspace files is performed by this chart change.
Fresh sandbox startup and workflow pause/resume must pass in `phoenix-byoc`
before a customer release is published.
