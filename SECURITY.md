# Security

## Secrets

Never commit `values.secrets.yaml`, `.rendered/` or generated Kubernetes Secret
manifests. The supplied `values.secrets.yaml` must have mode `0600`; the
installer enforces that mode before rendering. Both paths are ignored by Git.

The current upstream application charts receive sensitive values through Helm
and render Kubernetes Secrets. Helm stores release data in Secrets in the
target namespace; access to those objects is equivalent to access to
application credentials.

Rotate at minimum:

- PostgreSQL passwords and URLs;
- Redis password and URL;
- Rails `SECRET_KEY_BASE`;
- Workflow Engine tokens;
- agent provider credentials.

Do not expose Phoenix Gateway ingress unless the deployment is intentionally
isolated and `services.gateway.allowUnauthenticatedIngress` is explicitly set.

## Supply chain

Use only the exact versions in `release.yaml`. Publication workflows
refuse to overwrite an existing chart or image version and verify anonymous
public access after publication.

## Reporting

Report vulnerabilities through the private security contact supplied with the
customer agreement. Do not open a public issue containing credentials,
customer topology or exploitable details.
