# Third-party evidence for a BYOC release

The release bundle contains `THIRD_PARTY_NOTICES.md`, `SOURCE_OFFER.md`,
`release.yaml`, `image-index.json`, per-image/per-platform notices and CycloneDX
SBOMs, verified attestation envelopes, corresponding source archives and
`SHA256SUMS`. Registry attestations remain attached to the final image digests.
CI artifacts are temporary review outputs; the compliance archive must also be
attached to the customer GitHub release and delivered with offline releases.

## Contact

`compliance/source-offer.json` uses <https://canonix.ai/>. The source offer
directs recipients to the email contact published on that site and asks for
the release version and component. Keep that contact available for the offer's
duration. The website is a contact route; the actual source accompanies the
release in `sources/`.

## Prepare a release

1. Build all images through the license-enabled Phoenix build workflows.
   Resolve missing license texts or source locations using the component
   inventories produced by the failed build. Never mark missing evidence as
   approved solely because an SPDX identifier is known.
2. Publish/mirror the final images together with their signatures, attestations
   and OCI referrers. Selecting new image digests or chart versions is a separate
   release-promotion change. This compliance PR preserves the existing
   `release.yaml` versions, repositories, tags and digests.
3. The pipeline archives source and build instructions in signed OCI artifacts.
   The release packager downloads them automatically. For components not covered
   by automatic resolvers, prepare the exact corresponding source for each component marked
   `copyleft` in the inventories, including native libraries shipped inside
   Python wheels. Include applicable modifications, scripts and instructions
   necessary to build/install the covered code. Document the applicable LGPL
   replacement/relinking mechanism. An upstream homepage alone is insufficient.
4. For an offline override, build `source-index.json` and check its archives against those actual image
   versions. Example entry (replace all values with real evidence):

   ```json
   {
     "schemaVersion": 1,
     "components": [{
       "purl": "pkg:generic/component@version",
       "sourceUrl": "https://upstream.example/exact-source-version",
       "reviewedBy": "Source reviewer",
       "modifications": "Description of modifications, or none",
       "archive": "component/source.tar.gz",
       "archiveSha256": "SHA-256 of the source archive",
       "buildInstructions": "component/BUILD.md",
       "buildInstructionsSha256": "SHA-256 of the build instructions"
     }]
   }
   ```

5. Run the packager with registry read access, Python 3.12+, PyYAML, crane, oras and
   cosign installed:

   ```sh
   python3 scripts/package-release.py --output dist
   # Optional reviewed offline source override:
   # python3 scripts/package-release.py --source-root /path/to/corresponding-source --output dist
   ```

   It checks the trusted GitHub signing identity, exact signed image subjects,
   every runnable platform, notice-file checksums, complete SBOM attribution
   and source-archive checksums. Missing evidence blocks packaging. The
   `scripts/compliance` verifier is vendored from `phoenix-devops`; update its
   Python/shell files together with upstream changes.

6. For private ECR development candidates, run **Package BYOC compliance release**
   in `phoenix-devops` with the reviewed full BYOC commit SHA. DevOps already
   owns ECR publication access. Its job checks out that exact public BYOC
   revision, runs this same packager with all verification gates, and produces
   the complete release artifact. Download the artifact and attach its archive,
   checksum and individual documents/SBOMs to the draft BYOC GitHub release.
   Do not grant a public repository the shared ECR push role merely to package
   a release.

7. For published images, alternatively run **Package BYOC compliance release**
   in this repository. Leave `source_release`
   empty to use signed image source artifacts. An optional offline override is an
   existing release asset named `corresponding-source.tar.gz` whose root holds
   the index and source files. `create_draft=true` attaches the archive, checksum,
   source offer, combined notices and individual per-image SBOMs to a draft customer release. Publishing
   that reviewed draft is the release owner's final handoff step. The workflow authenticates to GHCR. Private ECR use here requires an
   explicitly configured `AWS_ROLE_BYOC_ECR_READ` role with read-only registry
   permissions and narrowly scoped GitHub OIDC trust; otherwise use DevOps as
   above. Local packaging uses existing registry credentials. No customer cluster access is involved.

## Verification and mirroring

`scripts/images.sh verify` now requires valid license and signed SBOM evidence
for every release image. `scripts/images.sh mirror` uses cosign and ORAS to
preserve both legacy attachments and OCI referrers, then verifies the target.
Copying just the image manifest does not preserve the evidence.

The exported attestation envelopes are records of successful online verification;
they are not standalone Sigstore trust bundles. Customers verify signatures
against the registry using the pinned digests and `compliance/policy.json`.

## Rollout status

This PR leaves `release.yaml` identical to the existing main-branch baseline.
It does not select a new BYOC version, change image repositories/tags/digests,
or promote a new chart version. Rebuilding and selecting the shipped versions
will be handled separately. The unchanged baseline is **not** claimed to pass
the new image-evidence gates; those gates remain strict and may reject older
images that lack the required evidence.

The end-to-end test used the historical BYOC snapshot
`790365eda68fcafa12c690df913a1c1fdd9d8276`, containing 12 compliance validation
images. The DevOps packaging workflow pins that snapshot for its integration
check; a real release must explicitly select its separately reviewed BYOC
commit. Its verification results apply to that test snapshot, not the current
installation manifest.

[Validation evidence](https://github.com/canonix-engineering/phoenix-byoc/releases/tag/untagged-f1660c15926f8e79efcc)
is retained in an unpublished draft named **OSS compliance validation — not a
BYOC release**. The archive's historical `0.2.0-development.16` identifier is
only a test-bundle label, not a selected next release. Do not publish that draft
or reuse its notices/SBOMs/source offer for a different set of image digests.
The original verified files are retained unchanged for reproducibility.

The archived OpenSandbox chart contains the upstream license and modification
notice. Selecting and publishing a new chart version is deferred together with
release version updates.

Optional chart-provided images outside `release.yaml` also need an explicit
distribution review before enabling them in a customer release.

Run the packaging tests with:

```sh
python3 -m unittest discover -s tests -p 'test_compliance_*.py' -v
```
