# Ordinary BYOC release automation

The manual **Prepare BYOC release** and **Publish BYOC release** workflows live
in `phoenix-devops`. They call `scripts/release_ops.py` in this repository.
This tool handles ordinary online delivery archives; `package-release.py` remains
the separate compliance-bundle tool. Neither button builds application images
or deploys a Kubernetes workload.

## Prepare

Run Prepare on DevOps main with a new stable version and `services=all`, or a
comma-separated selection of `web,engine,agents,gateway`. Unselected groups keep
the previous published release's images. Web includes frontend and worker;
Engine includes OpenSandbox. Agents is a runtime image configured in Engine.

Preparation resolves the latest published stable BYOC baseline, freezes each
selected Preview SHA, records main/Preview tree differences and checks the latest
branch CI for that exact SHA. Successful same-SHA main builds are accepted.
Main/Preview tree differences are informational: review intended exclusions.
The tool resolves existing ECR tags, checks Preview rollout and live pod digests,
and verifies the running Engine API Agent configuration. It never rebuilds images.

The workflow compares the pinned published charts with the frozen DevOps chart
sources, then creates a draft `release/<version>` PR containing `release.yaml`
and `.release/<version>/{plan.json,review.json,REPORT.md,chart-diff.json}`.
A source or rollout blocker leaves the candidate incomplete and is recorded in
its report; it is not permission to publish. Authentication and chart-download
failures stop the workflow. Preparation artifacts survive a later PR failure.

Repeated preparation refuses an existing branch so a rerun cannot silently
replace reviewed versions. If the push succeeded but PR creation failed, create
the PR from that existing branch using its `REPORT.md`; do not rerun preparation.
For an existing candidate, use these explicit operations on its branch:

```bash
# Retry evidence checks without choosing newer Preview commits.
python3 scripts/release_ops.py recheck --context YOUR_EKS_CONTEXT

# Add or refresh only Agents after the developer promotes it.
python3 scripts/release_ops.py refresh --services agents --context YOUR_EKS_CONTEXT
```

Refresh preserves other frozen service groups and edited charts/docs. Both
operations invalidate qualification and update the report. If other frozen
services no longer match Preview, review whether to refresh those groups too;
do not claim that the old combination is still deployed. Missing images during
initial preparation must be resolved by explicit refresh of that group.

## Complete the release PR

Automation supplies evidence; it does not decide application compatibility or
write service migrations. Review the source comparisons and chart report:

- Required configuration, secrets, schema hooks and installation order.
- Exact selected/retained service combination, including shared interfaces.
- Relevant DevOps chart changes and corresponding BYOC values/templates.
- Whether critical changes require an AWS `phoenix-byoc` rehearsal.

Publish required new chart versions with the existing **Publish BYOC charts**
workflow before updating BYOC pins. Do not overwrite published versions. No
GCP deployment or testing is part of this automation.

Update `UPGRADE.md` and `docs/releases/<version>.md` with the actual changes and
supported baseline. The customer message stays out of tracked files.
Run affected repository checks and fixture rendering. For critical persistent
state, hook, storage or incompatible interface changes, discuss the risk and
perform the authorized AWS rehearsal. Ordinary compatible image-only changes
can record a reason for not rehearsing. Do not claim a rehearsal took place
based on Preview readiness or fixture tests.

Complete `review.json`:

| Field | Required evidence or assessment |
| --- | --- |
| `compatibility` | Compatibility of selected and retained versions |
| `chartsAndValues` | Chart comparison and required settings |
| `upgradeInstructions` | Baseline and update/rollback requirements |
| `customerRegistryAccess` | Customer access check, scope and evidence |
| `customerChanges` | Short English summary to include in the customer message |
| `validationEvidence` | Check links or sanitized candidate records |
| `criticalChanges` | Explicit boolean, based on the actual diff |
| `rehearsal` | `performed`, evidence when performed, or reason for omission |
| `inputSha256` | Final delivery `input-hash` output |
| `planSha256` | Generated plan checksum; changes invalidate qualification |

Descriptions must be concrete; nonempty fields are not proof of their truth.
The PR reviewer owns these assessments. Preserve raw private logs outside Git.
For an executed rehearsal, record the starting version, candidate input hash
and scope of functional verification. CI cannot independently prove a human
review or historical rehearsal from a text field.

```bash
python3 scripts/release_ops.py input-hash
```

The hash covers tracked and nonignored delivery files, including scripts and
upgrade instructions, excluding `.release/` evidence. Complete review fields,
commit the PR, and merge after checks and review. Other changes incorporated at
merge invalidate the hash: refresh the review instead of bypassing it.

## Publish

Run Publish on DevOps main with the exact merged BYOC PR commit. The existing
`byoc-publication` environment gates the job. Publication verifies the commit
belongs to a merged main PR, main tests passed, and the baseline has not advanced.
It validates the reviewed snapshot, resolves all application image manifests
and layer URLs with the runner's AWS role, and anonymously downloads pinned
charts. Runner ECR access is **not** proof of customer access; that remains a
separate scoped review item. External infrastructure images retain their pins
and require review when changed.

CI renders actual published charts with fake fixture values and runs schema
validation, allowing missing custom resource schemas. It packages only a clean
committed checkout, retains executable modes and includes internal checksums.
The nine public delivery assets are the archive, its checksum, release manifest,
image/chart inventories, delivery metadata, verification record, upgrade guide
and release notes. Rendered manifests, kubeconfig and secrets are not artifacts.
The image inventory covers `release.yaml`; chart-internal helper images are
visible in rendering and must be reviewed when chart content changes.

The tool creates a draft GitHub release, uploads and downloads each asset to
verify exact bytes, then publishes. Retry is allowed for identical artifacts;
differing existing assets, tags or targets stop without replacement. Timestamps
from fresh checks do not change deterministic delivery bytes. A completed
published release is verified, not rewritten.

A separate `customer-message-draft` artifact is generated after publication.
Review it for required YAML additions, change-specific instructions and accurate
claims before sending. No automatic messaging is implemented.

## Local requirements and limitations

Python 3.10+ with PyYAML 6.0.3, Git, GitHub CLI, AWS CLI, kubectl and Helm are
needed; publishing checks also use Helmfile and kubeconform. Use explicit
kubeconfig context; local commands never switch context. Running `printenv` for
`WORKFLOW_RUNTIME_IMAGES` inside Preview Engine pods requires pods/exec access;
it reads this one nonsecret setting only. A missing tool or access error is a
blocker, not a cue to change IAM policies automatically.

Unit tests use synthetic manifests and temporary Git repositories. Run:

```bash
python3 -m unittest discover -s tests -p 'test_release_ops.py' -v
```

These tests exercise deterministic archives, partial pin preservation, stale
review rejection, image readiness and failure handling. They do not deploy a
release or establish that the CI credentials are configured.
