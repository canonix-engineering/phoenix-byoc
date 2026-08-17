# ClickHouse

Phoenix BYOC includes a Kubernetes-neutral, single-node ClickHouse StatefulSet.
It is enabled in the complete example and uses the multi-architecture image
pinned by tag and digest in `release.yaml`.

## Bundled ClickHouse

```yaml
clickhouse:
  bundled:
    enabled: true
    username: phoenix
    database: phoenix
    persistence:
      size: 10Gi
      storageClass: ""
```

Set the URL-safe password in the selected secrets file:

```yaml
secrets:
  clickhouse:
    password: <password>
    url: ""
```

The local ClickHouse release creates `Secret/clickhouse`. Phoenix Web reads the
HTTP URL from that Secret through its existing `web.extraEnv` support. The URL
does not appear in the Phoenix Web ConfigMap.

## External ClickHouse

Disable the StatefulSet and provide the complete URL in the secrets file:

```yaml
clickhouse:
  bundled:
    enabled: false
```

```yaml
secrets:
  clickhouse:
    password: ""
    url: https://user:password@clickhouse.customer.internal:8443/phoenix
```

The connection Secret is still created, but no ClickHouse Service,
StatefulSet or PVC is installed.

The bundled topology is intended for functional BYOC installation and is not a
production HA topology. The customer owns backup, restore and HA decisions.
