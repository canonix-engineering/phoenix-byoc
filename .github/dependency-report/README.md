# PR dependency and license report

Each PR receives one updated comment with a result, new/existing unknown licenses,
dependency changes, a license summary and a collapsed package table. The full
artifact contains `report.json`, `report.md` and `packages-licenses.md`.

## Results

- **PASS**: license metadata is available for every inventoried package and there
  were no analysis errors. This is not approval of license compatibility.
- **ATTENTION NEEDED**: at least one package version has an unknown license.
- **INCOMPLETE**: a required lookup/parser failed or no packages were inventoried.
- **REFERENCES ONLY**: an explicitly configured infrastructure repository has no
  package inventory. Image/chart changes are shown without claiming license checks.

Counts deduplicate by ecosystem/name/version. Conflicting declarations are retained,
separated by semicolons. SPDX expressions are not split. The comment shows the six
largest license groups and the first 30 package rows; the artifact keeps every row.
There are no vulnerability lookups, license allow/deny rules or merge blockers.
Existing image scans and required checks remain unchanged.

## Activation

The commenting workflow runs after it is merged into the PR base branch, on opened,
reopened, synchronize, edited and ready-for-review events. It includes draft PRs.
The read-only regression workflow generates a reviewable artifact before merge;
a maintainer can publish that artifact through the same comment publisher.

Set `DEPENDENCY_REPORT_ENABLED=false` to disable the commenting workflow.
The manual workflow accepts a PR number. Do not add these jobs to required checks
or deployment dependencies. Each repository contains a complete copy, so rollout
PRs can be merged independently without relying on an unmerged workflow revision.

## Inputs and scope

- npm v2/v3 lockfiles and Ruby `Gemfile.lock`, including transitive packages.
  Ruby platforms are retained; local workspace links are skipped. npm direct scope
  means declared in the lockfile root or a workspace.
- Go requirements in `go.mod`, including indirect requirements and `replace`
  directives. Replacement licenses use the effective module/version. Local and
  Canonix modules are not queried publicly and retain unknown licenses. `go.sum`
  is not an installed dependency list. Go workspaces are flagged for manual review.
- Python `uv.lock`, including optional/transitive packages and marker-dependent
  versions. The local root project is excluded. Exact `requirements*.txt` pins
  are inventoried as declared dependencies; their transitive graph is not resolved.
  Ranges, includes and custom indexes are reported for review. Without `uv.lock`,
  PEP 621 dependencies are inventoried and unresolved versions are explicit.
- npm/Ruby/Python licenses use version-specific public registry metadata.
  Go licenses use the [deps.dev version API](https://docs.deps.dev/api/v3/).
  Only license fields are consumed; advisory fields are discarded. Metadata gaps
  remain unknown; service failures are incomplete checks.
- `.github/dependency-report.json` can declare external source dependencies with
  `name`, `versionFile`, `versionArg`, `source`, and `license`. Versions are read
  from Docker ARG defaults; licenses are repository declarations, not upstream
  verification. Build-time overrides are not resolved. When this configuration
  is first introduced, the same declarations are applied to the base snapshot so
  adding reporting does not look like adding runtime packages.
- `excludePaths` omits fixture inventories; `referencesOnly` explicitly opts into
  reporting references without package-license evaluation. Configuration is data.
- Docker FROM, Actions uses, chart metadata and `release.yaml` values are textual
  reference comparisons. OS packages, build-time downloads, bundled native
  libraries and image contents remain the image compliance pipeline's responsibility.
- Manifest changes without a corresponding lockfile change are flagged. No package
  resolution, installation or project-code execution occurs. Outputs are bounded;
  public package names/versions are sent only to the documented metadata services.

## Permissions

`pull_request_target` checks out `github.workflow_sha`, the trusted base reporting
implementation. PR/base Git blobs are fetched at immutable SHAs and parsed as data.
GitHub credentials never go to metadata services, redirects are refused, checkout
credentials are not persisted, and an outdated run cannot overwrite a newer PR
report. The publisher updates only its own marked comment. The regression workflow
has a read-only token and never publishes comments.

Failures are informational. A fallback updates the comment if execution fails and
GitHub still permits it. Runner outages, cancellation and denied permissions can
prevent publication; the comment retains its original SHA and timestamp. Artifacts
follow repository visibility and expire after 30 days.

## Development

```sh
python3 -m unittest discover -s .github/dependency-report/tests -v
python3 .github/dependency-report/report.py --repo OWNER/REPO --pr NUMBER --output /tmp/report
```

The CLI uses `GH_TOKEN` or the existing `gh` login. Add `--publish` to update its own
comment. Python 3.11+ is required; there are no runtime package dependencies.
