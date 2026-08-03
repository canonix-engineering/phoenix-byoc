# Redis

Redis is required by Phoenix Web ActionCable, workflow-event streaming and
conversation streams.

## Bundled

```yaml
redis:
  bundled:
    enabled: true
```

The pinned upstream chart deploys one persistent Redis instance without
authentication, matching the internal Phoenix environments. The in-cluster URL
is derived automatically; leave `secrets.redis.url` empty.

This mode is not highly available.

## External

```yaml
redis:
  bundled:
    enabled: false
```

Set `secrets.redis.url` to `redis://` or `rediss://`, including credentials and
the selected database number.
