# PostgreSQL

Phoenix uses five databases:

- `phoenix_web_production`;
- `phoenix_web_production_cache`;
- `phoenix_web_production_queue`;
- `phoenix_web_production_cable`;
- `phoenix_workflow_engine_internal`.

The first four are owned by `phoenix_web`. The internal database should be
owned by `phoenix_workflow_engine_internal`.

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

If `postgresql.hooks.phoenixWeb=true`, the existing Phoenix Web pre-install
hook creates/alters the `phoenix_web` role with `CREATEDB` and runs
`rails db:prepare`.

If `postgresql.hooks.workflowEngine=true`, the existing Workflow Engine hook
creates the internal role/database.

Both modes require `secrets.postgresql.adminUrl`. The hooks are unchanged from
the internal deployment charts.

If the hooks are disabled, the customer is responsible for creating the roles
and databases and running the required migrations.

Bundled PostgreSQL is intended only for kind/demo validation and is disabled in
the customer-managed default.
