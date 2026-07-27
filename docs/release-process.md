# Release process

Chart and image publication is initiated manually from the private
`phoenix-devops` repository.

## Charts

Run `Publish BYOC charts`, select a Git ref and one allow-listed chart or `all`.
The workflow:

1. lints and packages the charts;
2. waits for the `byoc-publication` Environment approval;
3. reuses an identical existing version and rejects different content;
4. pushes to public GHCR;
5. verifies anonymous pull.

Every chart change requires a SemVer bump in its private `Chart.yaml`. A changed
chart cannot overwrite an already published version. After publication, update
the exact version in `releases/stable.yaml` with a normal reviewed commit to
`main`.

## Images

Run `Publish BYOC image` for each runtime image. The workflow mirrors an
immutable `sha-<commit>` ECR image to a SemVer public GHCR tag, compares digests
and verifies anonymous access. Image tags may use a SemVer prerelease suffix but
not `+build` metadata, because `+` is not valid in a container image tag.

The source ECR image must already exist. See [image-inventory.md](image-inventory.md)
for components whose gated source-image pipeline still needs to be completed.

Before promoting `releases/stable.yaml` from `development`, verify every chart
and image reference anonymously and run the kind test profile from a clean
cluster.

New GHCR packages are private by default. An organization package administrator
must change each newly created chart/image package to public. The publication
workflows then pass their anonymous-pull gate. A rerun is safe only when the
existing artifact content/digest is identical; different content at the same
version is rejected.

Do not change `release.channel` to `stable` until every item in
[publication-checklist.md](publication-checklist.md) is complete.
