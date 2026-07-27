# Runtime image inventory

The Helm charts require more images than their own primary application image.
All entries must have immutable, anonymously pullable references before a
customer release is promoted.

| Image | Private immutable source today | Public-release status |
| --- | --- | --- |
| `phoenix-gateway` | service CI, ECR `sha-<commit>` | mirror workflow ready |
| `phoenix-web` | service CI, ECR `sha-<commit>` | mirror workflow ready |
| `phoenix-web-frontend` | service CI, ECR `sha-<commit>` | mirror workflow ready |
| `phoenix-workflow-engine` | service CI, ECR `sha-<commit>` | mirror workflow ready |
| `phoenix-opensandbox` | Workflow Engine CI, ECR `sha-<commit>` | mirror workflow ready |
| `phoenix-agent` | Agents CI, ECR `sha-<commit>` | mirror workflow ready |
| `phoenix-opensandbox-controller` | local/manual devops build only | gated `sha-<commit>` source pipeline required |
| `phoenix-lab` | local/manual build only | gated `sha-<commit>` source pipeline required |
| `cortex-postgresql` | existing GHCR commit-tagged image | approve and promote to a supported immutable release tag |

The two incomplete source pipelines are release blockers, even though their
names are accepted by the mirror workflow. The mirror does not build images and
will fail closed if the requested ECR source tag does not exist.
