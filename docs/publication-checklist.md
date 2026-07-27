# Public repository checklist

Complete this checklist before sharing `phoenix-byoc` with a customer.

## Repository and legal

- Create the public `phoenix-byoc` GitHub repository.
- Choose and commit the organization-approved license or customer terms.
- Configure branch protection and required review.
- Confirm that documentation contains no private hostnames, credentials or
  customer data.
- Inspect packaged chart metadata, default values, comments and maintainer
  contacts as public material.

No license has been selected in this working tree. Public visibility alone does
not grant customers installation or redistribution rights.

## Private publisher configuration

- Create the protected `byoc-publication` GitHub Environment in
  `phoenix-devops` and require an approver.
- Confirm `AWS_ROLE_SHARED_ECR` can read only the approved private ECR sources.

## Artifacts

- Bump every changed private chart to a new exact SemVer version.
- Run `Publish BYOC charts` in dry-run mode, then with approval.
- Make each newly created GHCR package public and rerun the anonymous-pull gate.
- Link the public GHCR chart packages to the public `phoenix-byoc` repository.
- Complete every runtime source-image pipeline in
  [image-inventory.md](image-inventory.md).
- Mirror all runtime images to exact SemVer public tags.
- Update all chart and image references in `releases/stable.yaml`.
- Change `release.channel` to `stable` only in a reviewed release commit.

## Acceptance

- Clone the public repository without organization credentials.
- Run `./scripts/test.sh`.
- Install the `kind` profile into a clean cluster using only public artifacts.
- Install the `external` profile against disposable external PostgreSQL, Redis
  and Cortex services.
- Verify migrations, a basic API request and one sandbox workflow.
- Record release notes, compatibility and rollback results.
