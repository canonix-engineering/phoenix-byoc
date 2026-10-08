# Valkey and Redis-compatible connections

The bundled cache is Valkey 9.1.2. Its server license is
[BSD-3-Clause](https://github.com/valkey-io/valkey/blob/9.1.2/COPYING).
The server license does not describe every operating-system package in the image.
Phoenix Web ActionCable and Redis-compatible workflow/conversation transports
use the existing Redis protocol. Client names and `redis://` URLs stay unchanged.

## Bundled

```yaml
redis:
  bundled:
    enabled: true
```

`release.yaml` pins the multi-platform image:

```text
docker.io/valkey/valkey:9.1.2@sha256:418652cfb58ef879d4978c33553735d7147016032d5aefaa14c828e611eb9dfd
```

The Helm release remains `redis`, using Helmforge `redis` chart 1.6.18 with
an explicit image override. The Valkey image includes the `redis-server` and
`redis-cli` compatibility executables used by the chart. The chart runs
`redis-server /etc/redis/redis.conf`; all three probes run `redis-cli ping`.
The generated config enables AOF, periodic snapshots and `/data` storage.
No Redis Stack modules are configured or required.

The StatefulSet is `valkey`, with a new `data-valkey-0` PVC. The `redis-client`
Service selects only Valkey pods and preserves the existing connection URL.
Leave `secrets.redis.url` empty for bundled mode. Authentication remains disabled;
restrict access to the trusted application network. This mode is not highly
available. Database numbers remain unchanged, including DB 1 and DB 14.

`scripts/images.sh list` includes Valkey. `images.sh mirror --to <registry/path>`
copies it with the other release images and checks the destination digest.
When `imageRegistry` is set, the chart uses `<registry/path>/valkey` with the
same tag and digest and the configured `imagePullSecrets`.

## Existing Redis installations

Do not perform an ordinary image replacement or point Valkey at the old Redis
PVC. Redis 8 RDB/AOF files are not assumed compatible. The installer blocks an
upgrade while `statefulset/redis` exists, and blocks a fresh install over a
retained `data-redis-0` PVC without an existing Valkey deployment.

An operator must complete a coordinated migration before normal installation
can resume:

1. Record the context, namespace, installed images, Helm revisions, clients,
   database numbers, key types, expirations and any stream consumer state.
2. Back up Redis and verify restoration in an isolated instance of the exact
   source version. Retain the old PVC and Helm history.
3. Quiesce all writers and event producers. Pub/Sub messages are not durable;
   arrange application reconnection and state refresh after the interruption.
4. Stage Valkey on a separate volume with this release's image and rendered
   configuration, without switching `redis-client`. For durable data, use a
   type-aware logical migration and compare values, TTLs and stream state.
   An empty cache is acceptable only after confirming no required state exists.
5. Upgrade the existing Helm release `redis` with the rendered BYOC values in
   the maintenance window. Preserve the old PVC; the new StatefulSet and
   compatibility Service must point exclusively to the validated Valkey data.
6. Resume applications and run `scripts/verify.sh`, cross-process ActionCable
   checks and the affected business workflows. A Helm success is insufficient.
7. Resume `scripts/install.sh` with the original values and secrets only after
   the cache migration is complete. Never delete the retained PVC to bypass
   the guard. A rollback after new writes requires a reverse data migration;
   blindly restoring the old release loses those writes.

## Verification

Run `scripts/test.sh` to render bundled, external and mirrored configurations.
It rejects Redis 8 images and verifies the pinned image, commands, probes,
Service selectors, mirroring and legacy-upgrade guard.

With local Docker running, `scripts/smoke-valkey.sh` then runs the exact chart
configuration and probes. It checks Pub/Sub, expiry, DB 14 hashes and data/TTL
preservation across restart. Its disposable container and volume are removed
following the test; no cluster data is used.

For the selected installation, `scripts/verify.sh` checks the deployed image
against the render, PING through `redis-client`, the actual `valkey_version`
and a module allowlist (only Valkey’s built-in Lua engine). Full Web/workflow
acceptance remains a separate live check.

## External

```yaml
redis:
  bundled:
    enabled: false
```

Set `secrets.redis.url` to `redis://` or `rediss://`, including credentials and
the selected database number. The customer supplies and manages the external
Redis-compatible service. Disabling bundled mode does not establish the license
or version of that external service; record it in the installation inventory.
