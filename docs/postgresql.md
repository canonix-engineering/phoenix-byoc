# PostgreSQL

Phoenix uses five databases:

- `phoenix_web_production`;
- `phoenix_web_production_cache`;
- `phoenix_web_production_queue`;
- `phoenix_web_production_cable`;
- `phoenix_workflow_engine_internal`.

The first four are owned by `phoenix_web`. The internal database should be
owned by `phoenix_workflow_engine_internal`.

## Bundled PostgreSQL

For a functional installation with all dependencies in the target namespace:

```yaml
postgresql:
  bundled:
    enabled: true
```

The bundled chart does not enable PostgreSQL TLS. BYOC therefore derives every
application DSN with `sslmode=disable`, regardless of the external PostgreSQL
setting. `postgresql.external.sslmode` is used only when
`postgresql.bundled.enabled=false`.

Bundled PostgreSQL is single-node and is intended for installation validation,
not production HA.

## External PostgreSQL

When `postgresql.bundled.enabled=false`, configure
`postgresql.external.host`, `port` and `sslmode`. The selected `sslmode` is
preserved in the Phoenix Gateway, Phoenix Web and Workflow Engine connections.

## Existing hooks

To run the same database jobs used by the internal environments:

```yaml
postgresql:
  bundled:
    enabled: false
  hooks:
    phoenixWeb: true
    workflowEngine: true
```

If `postgresql.hooks.phoenixWeb=true`, BYOC first creates or updates the
`phoenix_web` role and primary database, then runs the Phoenix Web schema
migrations. This bootstrap removes the first-install dependency cycle between
Phoenix Web and Workflow Engine. After Workflow Engine is available, the
existing Phoenix Web hook runs `rails db:prepare` and the configured application
initialization tasks.

If `postgresql.hooks.workflowEngine=true`, the existing Workflow Engine hook
creates the internal role/database.

Both modes require `secrets.postgresql.adminUrl` when external PostgreSQL is
selected. With bundled PostgreSQL, BYOC derives the administrative URL from the
bundled superuser password.

If the hooks are disabled, the customer is responsible for creating the roles
and databases and running the required migrations.
