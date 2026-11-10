# BYOC 0.2.6 — incomplete CSG candidate
Baseline: v0.2.5
Snapshot refreshed/rechecked explicitly; previous qualification invalidated.

## Blockers
gateway: phoenix-gateway: latest same-SHA branch CI is not successful: https://github.com/canonix-engineering/phoenix-gateway/actions/runs/42802706957
- agents: https://github.com/canonix-engineering/phoenix-agents/compare/a3f3609376cde6e61f2856a76df6ad461f6ceab9...ba492b4c587eda3b6f21fa48475979cfd189fd6f
- engine: https://github.com/canonix-engineering/phoenix-workflow-engine/compare/98839e41e8a7c6e1d6b78feff5bbf9f086dcfa73...2cdbffd40b80bf55779ee03b7893a5f12edd8ff2
- gateway: https://github.com/canonix-engineering/phoenix-gateway/compare/34430765908eeaef442dcf3c2651f319799f5e47...a0f6b604a7ecc9bebff3d6f487d8aa9a691ad184
- web: https://github.com/canonix-engineering/phoenix-web/compare/6ed895a91f520df3e041d630bee18bebc01cd66b...90d83bd7a2a8e1429c023e73516a595d9355ba75

## Updated evidence and outstanding review

AWS access is restored. Five exact existing images are resolved and pinned for
Web/frontend, Engine/OpenSandbox and Agents. Gateway remains at the published
v0.2.5 pin; its selected Preview image does not exist. Do not publish this mix.
See aws-image-check.json and REVIEW-NOTES.md.

Eight candidate Preview Deployments and Engine's configured/running Agent
reference passed readiness and live digest checks. Engine/OpenSandbox were
reconciled through the existing deploy-only workflow:
https://github.com/canonix-engineering/phoenix-devops/actions/runs/42835210617
No application image was rebuilt locally. This is not an AWS BYOC rehearsal.

Fixture render/schema check: 66 resources, 63 valid, zero invalid/errors, three
skipped for unavailable CRD schemas. Seven OCI charts were downloaded
anonymously and compared; existing published chart versions are retained.

Gateway's old workflow failed to archive Debian ca-certificates sources. Repair
PR https://github.com/canonix-engineering/phoenix-gateway/pull/96 now also pins
the merged DevOps resolver workflow. Eight CI-routing tests, go test ./..., go
vet ./..., and six resolver tests passed locally; gofmt and diff checks clean.
Reviewer approval and new CI are required before promotion and explicit refresh.

Retention policy is awaiting a CSG decision: upstream defaults permanently
expire terminal runs after 14 days and keep zero previous snapshots. Six Web
migrations must precede Engine. UPGRADE.md is a draft with commands, preservation
requirements and recovery limits. Customer image access, final compatibility,
retention configuration and authorized AWS rehearsal remain outstanding.
