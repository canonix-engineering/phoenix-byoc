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
   and OCI referrers. Update **every** `release.yaml` image to the verified final
   digest; also update the OpenSandbox chart version after publishing it.
3. Prepare the exact corresponding source for every component marked
   `copyleft` in the inventories, including native libraries shipped inside
   Python wheels. Include applicable modifications, scripts and instructions
   necessary to build/install the covered code. Document the applicable LGPL
   replacement/relinking mechanism. An upstream homepage alone is insufficient.
4. Build `source-index.json` and check its archives against those actual image
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

5. Run the packager with registry read access, Python 3.11+, PyYAML, crane and
   cosign installed:

   ```sh
   python3 scripts/package-release.py --source-root /path/to/corresponding-source --output dist
   ```

   It checks the trusted GitHub signing identity, exact signed image subjects,
   every runnable platform, notice-file checksums, complete SBOM attribution
   and source-archive checksums. Missing evidence blocks packaging. The
   `scripts/compliance` verifier is vendored from `phoenix-devops`; update its
   five Python/shell files together with upstream changes.

6. Alternatively run **Package BYOC compliance release**, pointing it to an
   existing release asset named `corresponding-source.tar.gz` whose root holds
   the index and source files. `create_draft=true` attaches the archive, checksum,
   source offer and combined notices to a draft customer release. Publishing
   that reviewed draft is the release owner's final handoff step. The workflow
   expects images readable from public registries/GHCR; local packaging can use
   existing authenticated ECR access for development snapshots.

## Verification and mirroring

`scripts/images.sh verify` now requires valid license and signed SBOM evidence
for every release image. `scripts/images.sh mirror` uses cosign and ORAS to
preserve both legacy attachments and OCI referrers, then verifies the target.
Copying just the image manifest does not preserve the evidence.

The exported attestation envelopes are records of successful online verification;
they are not standalone Sigstore trust bundles. Customers verify signatures
against the registry using the pinned digests and `compliance/policy.json`.

## Rollout status

The current development manifest still points to previously published images;
some have no pinned digest. It has deliberately not been changed to nonexistent
new releases. It cannot pass the new release gate until all images are rebuilt,
the OpenSandbox chart is published, and corresponding-source archives exist.
Optional chart-provided images outside `release.yaml` also need an explicit
distribution review before enabling them in a customer release.

Run the packaging tests with:

```sh
python3 -m unittest discover -s tests -p 'test_compliance_*.py' -v
```
