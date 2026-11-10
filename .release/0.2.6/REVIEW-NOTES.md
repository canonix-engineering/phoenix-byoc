# CSG 0.2.6 review in progress

## Qualification blockers

- Local `canonix-shared-developer` SSO is expired; no candidate application
  digest or customer image access has been verified.
- The local kubeconfig has no `cnx-dev-eks` context. After authentication,
  discover the authorized existing EKS access path using a separate kubeconfig;
  do not change the user's current context.
- Retention is enabled by default and performs persistent deletions. Review
  policy and how to configure it before claiming compatibility or readiness.
- Perform the recommended AWS upgrade rehearsal only with explicit
  authorization, using qualified candidate images and preserved existing data.
- Final source identity, Preview rollout and pod runtime-Agent checks,
  fixture/schema checks, upgrade/rollback instructions and customer-access
  evidence are still required. Leave review qualification hashes unset.

## Checks performed

- Baseline: published v0.2.5, commit
  `a2972883c7d0778aed31f6363db69a369c07c140`.
- Frozen sources and CI: `plan.json`; no substitution of main for Preview.
- 46 BYOC tests passed with `python3 -m unittest discover -s tests -p 'test_*.py'`.
- 15 release-tool tests passed with the skill's `test_release_ops.py` suite.
- Anonymous chart downloads/content comparison: `chart-diff.json`.
- No install, upgrade, customer-cluster operation or publication performed.

## Chart assessment

Retain published pins. Gateway source only adds a configurable startup threshold
whose default stays 12. Engine changes are disabled internal Testbox features,
optional operator volumes and OpenSandbox identity configuration. Existing
customer VM-pool and FUSE settings remain supported. No published version was
overwritten. The removed internal `postgresql-external` chart is outside BYOC.

## Tool limitation

The maintained tool's CLI `chart-diff` dispatch raises `KeyError('chart-diff')`
because the function is named `chart_diff`. For this comparison its existing
`chart_diff` function was invoked directly through Python, without modifying
tool code. It verified a clean DevOps checkout at the exact frozen commit.
The tooling bug remains outside this customer delivery.
