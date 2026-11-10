# BYOC 0.2.6 — incomplete CSG candidate
Baseline: v0.2.5 (a2972883c7d0778aed31f6363db69a369c07c140)
Services: web, engine, agents, gateway
DevOps source: c519c153f8652a7046c18afe2fb6482963384b10

## Blockers
phoenixWeb: aws ecr failed (exit 255); inspect privately
phoenixWebFrontend: aws ecr failed (exit 255); inspect privately
phoenixWorkflowEngine: aws ecr failed (exit 255); inspect privately
phoenixOpensandbox: aws ecr failed (exit 255); inspect privately
phoenixAgent: aws ecr failed (exit 255); inspect privately
phoenix-gateway: latest same-SHA branch CI is not successful: https://github.com/canonix-engineering/phoenix-gateway/actions/runs/42802706957
phoenixGateway: aws ecr failed (exit 255); inspect privately

## Source changes
- web: https://github.com/canonix-engineering/phoenix-web/compare/6ed895a91f520df3e041d630bee18bebc01cd66b...90d83bd7a2a8e1429c023e73516a595d9355ba75
  main/Preview trees equal: False; CI: https://github.com/canonix-engineering/phoenix-web/actions/runs/42802602774
- engine: https://github.com/canonix-engineering/phoenix-workflow-engine/compare/98839e41e8a7c6e1d6b78feff5bbf9f086dcfa73...2cdbffd40b80bf55779ee03b7893a5f12edd8ff2
  main/Preview trees equal: True; CI: https://github.com/canonix-engineering/phoenix-workflow-engine/actions/runs/42784537685
- agents: https://github.com/canonix-engineering/phoenix-agents/compare/a3f3609376cde6e61f2856a76df6ad461f6ceab9...ba492b4c587eda3b6f21fa48475979cfd189fd6f
  main/Preview trees equal: False; CI: https://github.com/canonix-engineering/phoenix-agents/actions/runs/42806155782
- gateway: https://github.com/canonix-engineering/phoenix-gateway/compare/34430765908eeaef442dcf3c2651f319799f5e47...a0f6b604a7ecc9bebff3d6f487d8aa9a691ad184
  main/Preview trees equal: True; CI: blocked

Review chart changes, required values/secrets, exact mixed-version compatibility and upgrade instructions.
No images built; no cluster deployment or AWS upgrade rehearsal performed.
Complete review.json after applicable tests; see devops-skills/phoenix-byoc-release/references/automation.md.

## Review status

No candidate application image has been resolved: all application pins remain at
v0.2.5. AWS SSO for `canonix-shared-developer` has expired. Preview, customer
registry access and final rendering/qualification remain pending.

Gateway retry attempt 2 passed category vocabulary after the Agents promotion,
but failed image packaging on missing archived Debian ca-certificates source
(`20250419~deb12u1`, Debian 12.15), using DevOps revision
`8a40f269c98125c021a07dc7f0e85fc89bf92d5f`. Deployment was skipped.
The existing Gateway CI repair PR is
https://github.com/canonix-engineering/phoenix-gateway/pull/96 .
Do not substitute another source commit or bypass image qualification.

Retention is enabled by default (14 days; zero previous snapshots), and six Web
migrations precede Engine startup. This is a critical persistent-state change;
review the policy and perform an authorized AWS rehearsal before qualification.
See REVIEW-NOTES.md and docs/releases/0.2.6.md. UPGRADE.md is still the published
0.2.5 procedure and must be finalized for this candidate before publication.

Checks: 46 existing BYOC tests and 15 internal release-tool tests passed.
Seven OCI chart downloads/comparisons succeeded anonymously; chart pins remain
unchanged. No images were rebuilt locally, no cluster was upgraded, and no
release or customer message was published.
