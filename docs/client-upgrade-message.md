# Client handoff — Phoenix BYOC 0.2.0

Hi Pushpendra,

Phoenix BYOC 0.2.0 is available:
https://github.com/canonix-engineering/phoenix-byoc/releases/tag/v0.2.0

Please download `phoenix-byoc-0.2.0.tar.gz` and its `.sha256` file from that
release, verify the checksum, and follow `UPGRADE.md` inside the archive.
The same instructions are attached to the release as `UPGRADE-0.2.0.md`.

Keep your existing `values.yaml`, `values.secrets.yaml`, namespace and GCP
settings. The instructions identify the small agent-bundle values block to
merge. The installer preserves existing passwords/tokens and generates the
new separate publisher token automatically. Your existing read-only ECR
credentials continue to provide access to the release images.

Please schedule a maintenance window and take the database and persistent-volume
recovery checkpoint described in the instructions before starting. Run the
provided install command with your existing configuration, then complete the
verification steps, including your usual GCP-backed workflow.

Please send the upgrade result through this conversation. If a step fails, keep
the output and contact us before changing settings or attempting a rollback;
Helm rollback alone does not reverse database migrations. Do not send credentials,
rendered manifests or database backups.
