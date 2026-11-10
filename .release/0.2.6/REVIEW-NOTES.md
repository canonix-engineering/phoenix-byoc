# CSG 0.2.6 review in progress

## Remaining qualification blockers

- Frozen Gateway Preview `a0f6b604a7ecc9bebff3d6f487d8aa9a691ad184` has
  failing CI and no development ECR image. Release retains v0.2.5 Gateway.
  CI repair PR #96 now pins the merged Debian resolver workflow; it requires
  reviewer approval, successful checks and promotion before explicit Gateway
  snapshot refresh. Do not bypass reviews or silently substitute main.
- Upstream Engine retention defaults delete terminal workflow runs after
  14 days and retain zero previous snapshots. CSG policy/configuration is
  awaiting a decision. Existing BYOC values do not expose the new controls.
- Customer registry access, exact final service compatibility, and the
  recommended authorized AWS upgrade rehearsal remain pending. Do not fill
  qualification hashes or claim customer readiness.

## Checks performed

- Baseline: published v0.2.5 at
  `a2972883c7d0778aed31f6363db69a369c07c140`.
- AWS SSO restored. Separate temporary development-account ReadOnlyAccess
  credentials resolve all five Web/frontend/Engine/OpenSandbox/Agent images.
  These are administrator-side evidence, not customer-access proof.
- Frozen Web, Engine and Agent Preview commits were explicitly refreshed
  without changing their SHAs; Gateway and DevOps snapshots were preserved.
- Preview read access uses the existing Headlamp proxy in a separate private
  kubeconfig. Personal AWS configuration and current kube-context are unchanged.
- Engine/OpenSandbox were behind the freeze. Existing deployment workflow
  [42835210617](https://github.com/canonix-engineering/phoenix-devops/actions/runs/42835210617)
  successfully deployed the exact existing images. Agent runtime configuration
  was already current; a redundant queued Agent deployment was cancelled.
- Eight Preview Deployments passed observed-generation, replica/readiness and
  live image-digest checks. Engine ConfigMap and running API pod agree on the
  frozen Agent reference. Sanitized evidence: `preview-check.json`.
- Final fixture rendering: 66 resources. kubeconform 0.7 validation: 63 valid,
  zero invalid/errors, three skipped for unavailable custom resource schemas.
- 46 existing BYOC tests and 15 internal release-tool tests passed earlier in
  this candidate. New pin/configuration checks are recorded in `REPORT.md`.
- No customer cluster access, AWS BYOC rehearsal or release publication.

## Charts and main/Preview differences

Retain published chart pins. Seven anonymous OCI chart downloads were compared
with clean frozen DevOps source (`chart-diff.json`). Gateway source adds a
configurable startup threshold with unchanged default 12. Engine source adds
optional internal Testbox, operator volumes and OpenSandbox identity settings;
these are not required by the candidate. Do not overwrite published versions.
The removed internal `postgresql-external` chart is outside BYOC.

Web Preview excludes later main development, including the newer bundle editor;
Agents Preview deliberately excludes the Pi migration and subsequent runtime
architecture changes. Neither main tree was substituted for Preview. These
exclusions require no adoption of newer schemas or Pi contracts in this release.

## Maintained tooling limitations observed

The CLI `chart-diff` dispatch raises `KeyError('chart-diff')` because its function
is named `chart_diff`. The existing function was invoked directly without code
changes and verified the exact clean frozen DevOps checkout.

The tool's label-only Web pod selection counts other controller-owned pods,
including workers and completed migration Jobs. The final check scoped pods by
Deployment UID -> ReplicaSet UID -> Pod controller owner UID, including all old
ReplicaSets, then used the unchanged maintained `deployment_check` function.
The successful checks are separate evidence; the automated overall plan still
correctly blocks publication on Gateway. No release-tool code was modified.
