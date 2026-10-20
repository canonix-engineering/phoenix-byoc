# Chart preparation rehearsal — 2026-10-20

This is evidence for chart preparation, not an application release or permission
to upgrade CSG. Application image pins and release metadata in `release.yaml`
remain unchanged. The rehearsal used a private, ignored values overlay containing
the images actually running in Test.

## Sources and package dependency

- BYOC base: `1c79dfc1690093da6deac325dea8f66363b12b92`.
- DevOps chart source base: `f0d04b5e0811c51b9874d6c6af070609177e5d84`.
- Local chart versions: Web `0.2.3`, Gateway `0.5.0`, Workflow Engine `0.2.5`,
  OpenSandbox controller `0.2.3`.

These four OCI package versions were subsequently published from DevOps commit
`454a77cd597960988d866bb6da0e74678064cb23` by
[Publish BYOC charts run 39476082654](https://github.com/canonix-engineering/phoenix-devops/actions/runs/39476082654).
Public visibility and exact-version pulls passed. A subsequent rehearsal with
the frozen Preview application candidate installed the published OCI charts and
passed `verify.sh`. This report records the original chart-only rehearsal;
application release pins are maintained in the separate release-candidate PR.

## Rehearsal configuration

Cluster: `cnx-dev-eks`; namespace: `phoenix-byoc`. This is the existing deployment
simulator. PostgreSQL, Valkey, Cortex PostgreSQL and ClickHouse remained bundled.
The existing shared OpenSandbox controller was not upgraded. Cluster settings,
nodes and other namespaces were not changed.

Actual Test application image tags used:

| Component | Tag |
| --- | --- |
| Web and Frontend | `sha-f7d42d4b4d2c9471f98c99dcc7f9dfa139db7e7f` |
| Gateway | `sha-301f909ae4a16d272d21693532499902f340a24d` |
| Engine and OpenSandbox | `sha-d83e65f12311bf4231a726bbd46f901802c5a38e` |
| Agent | `sha-f452b19bd5c80432a79a09e411613eaea48b6a02` |
| Lab | `agent-lab-poc3` |

The Agent sandbox was observed running the expected image, with digest
`sha256:e0f2c428d53ba1b16a4bd5fe72792353e5aa7013cef74f1e223273c28496af45`.
Image overrides, credentials, database backups and raw logs are ignored local
files and are excluded from this PR.

Existing resource classes, sandbox node placement, admission limit of six,
tenant, volumes and service credentials were retained. Standalone agent bundle
lookup and evaluation result details were enabled in the rehearsal overlay;
Web publication remained disabled. Gateway stayed in `observe` mode.

## Checks completed

- Full `scripts/test.sh` suite passed with local chart sources, including
  Kubernetes schema validation, Valkey checks, secret reconciliation and the
  new release-preparation wiring tests.
- Additional rendered checks cover Web/worker publisher `secretKeyRef`, shared
  token wiring, GCP service-account annotations, sandbox placement, scoped
  Gateway routes and database migration tasks without demo seeding.
- Preflight rejects publisher/service token reuse, publication without standalone
  lookup, and an agent-bundle namespace unsupported by the current applications.
- Ordinary `scripts/install.sh --generate-secrets` completed and its final
  `verify.sh` passed. All 64 rendered live resources passed schema validation.
- PostgreSQL dumps were taken before the upgrade. Immediately after the upgrade,
  before synthetic functional-test records were created, user/enterprise/app/
  ticket/workflow-run counts remained `2/1/1/6/12`. Applied Web migrations
  increased from 134 to 158. All seven original PVC identities and volume bindings
  remained unchanged.
- Existing secret values were preserved; the new independent publisher token
  was generated without replacing the original secrets file.
- After removing the temporary smoke catalog as described below, the ordinary
  installer completed again. All ten namespace Helm releases were deployed,
  the catalog root was restored to `/workflow_definitions`, and the migration
  count remained 158. All seven original PVC bindings, all existing secret
  values and the new publisher token were unchanged. The standalone artifact
  uploaded before the repeat upgrade downloaded with the same SHA-256 afterward.
- Frontend HTTP, API health, password login, authenticated current-user request,
  authenticated ActionCable connection and worker heartbeat passed. Temporary
  non-admin test users were deactivated and their sessions removed.
- Artifact API returned the typed missing-key response, accepted a TUS upload
  and finalization, resolved the key, and returned a byte-identical download.
- Gateway health, MCP tool discovery and an actual workflow-summary tool call
  passed.
- In-process workflow completed successfully:
  `01a159ad-335c-7877-ad0f-f0cc285adaac`.
- The complete adapted Agent smoke test passed for workflow
  `01a159c4-bdee-75f9-87c2-aeb0da446c2b`: draft, human-requested revision,
  approval and final verification. Assertions checked reviewer-comment
  propagation, previous-report nonce preservation, downloaded reports and a
  native trace proving the Agent used the Read tool. Actual provider invocations
  and costs were recorded.

## Functional-test adaptations

The old DevOps smoke harness assumes database-loaded workflow definitions and
legacy Agent output fields. Current Test images load a file catalog and require
`output_schema_relpath`. The local rehearsal preserved the image's built-in
catalog and temporarily added smoke definitions, published immutable synthetic
bundles, and supplied the same artifact-key grants as Web.

Initial fixture runs exposed retired output fields, an absolute artifact path
in model output, and an empty previous-nonce field despite a successful workflow.
These are recorded as failed test attempts, not counted as passing assertions.
The fixture was adapted to the current domain-output contract and native
`runtime/trace.jsonl` format. No application source changes are included.

Removing that temporary catalog initially failed the Engine pre-upgrade hook:
the hook read `/etc/workflow-defs` from the previous ConfigMap although its new
pod no longer mounted that path. Restoring the ConfigMap's ordinary
`/workflow_definitions` value was required before retrying the standard installer.
The initial customer-shaped upgrade did not require this adjustment. A deployment
that intentionally switches catalog mounts needs the same hook-ordering review.

The existing namespace snapshot ECR credential initially produced HTTP 403 when
the shared controller read the Test Agent image. Only that namespace-local
expiring credential was refreshed. Subsequent snapshot jobs succeeded without
changing the shared controller or application credentials. This simulator
credential maintenance is not a customer GCP upgrade step.

## Limits

- Customer GCP VM lifecycle and Workload Identity were not exercised against GCP;
  their chart wiring was rendered and existing settings preserved.
- The shared controller was not replaced. Snapshot URI configuration was tested
  by rendering; incidental simulator snapshot jobs use the existing controller.
- Web bundle publication was tested at the chart/Secret wiring level; the live
  publication API test used Artifact API directly. Web publication stayed off.
- Evaluation controls were rendered and verified in deployed configuration;
  no full evaluation dataset or budget-exhaustion scenario was run.
- The unchanged Lab image was checked in runtime configuration. The current Lab
  workflow is a no-op, so this is not a dynamic Lab execution test.
- Gateway `enforce` mode was not tested: the actual Test Engine image does not
  establish compatibility with capability signing.

Use [the customer draft](client-upgrade-message.md) only after the final
application release and chart packages are available.
