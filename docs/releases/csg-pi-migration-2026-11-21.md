# CSG release candidate: Pi migration (2026-11-21 IST)

**Preparation draft. Not for installation or publication.** This note records the
intended scope and the evidence still needed. It does not change `release.yaml`
or claim that Preview or CSG has been upgraded.

## Planned changes

- Move the Agents runtime to Pi for portable versioned bundles
  ([Agents #397](https://github.com/canonix-engineering/phoenix-agents/pull/397)).
  The last published BYOC release, v0.2.6, deliberately excluded this migration.
- Review the thin-provider path as a coordinated change: BYOC passes operator
  configuration to the DevOps chart, Engine supplies it to the sandbox, and
  Agents initializes Pi in memory. Customer subscriptions are out of scope.
  [Agents #506](https://github.com/canonix-engineering/phoenix-agents/pull/506),
  [Engine #320](https://github.com/canonix-engineering/phoenix-workflow-engine/pull/320),
  [DevOps #264](https://github.com/canonix-engineering/phoenix-devops/pull/264),
  [BYOC #20](https://github.com/canonix-engineering/phoenix-byoc/pull/20).
- Review Web/frontend and Gateway compatibility against the selected Engine
  and Agents builds rather than assuming that each green service is enough.

## Internal Preview promotions

- [Gateway #105](https://github.com/canonix-engineering/phoenix-gateway/pull/105)
- [Agents #516](https://github.com/canonix-engineering/phoenix-agents/pull/516)
- [Web #926](https://github.com/canonix-engineering/phoenix-web/pull/926)
- [Engine #321](https://github.com/canonix-engineering/phoenix-workflow-engine/pull/321)
- [DevOps #266](https://github.com/canonix-engineering/phoenix-devops/pull/266)

BYOC has no Preview branch. The versioned release candidate is prepared here
after the selected service promotions and their Preview checks are complete.

## Before pinning or publishing

- [ ] Resolve promotion conflicts without dropping Preview-only changes;
  obtain review and passing CI on the exact promoted source.
- [ ] Verify the resulting Preview rollouts. Record source commits, existing
  immutable image digests and rollout evidence for Gateway, Agents, Web/frontend
  and Engine/OpenSandbox. Confirm the Engine selects the verified Agents image.
- [ ] Verify the reviewed public Engine chart artifact that renders
  `agentSecrets.llmEnv`. The existing BYOC pin, 0.2.8, ignores this input.
  DevOps defines 0.2.9 in source; do not pin it until it is published and checked.
- [ ] If the deployment model catalog is included, qualify the published Web chart
  and configuration support independently.
- [ ] Confirm CSG model routes in scope. For each selected route, record one
  receipt identifying the deployed build, requested model and actual upstream.
  Do not count a loopback or subscription test as CSG acceptance.
- [ ] Update the release manifest and upgrade guide from verified artifacts,
  preserve customer values and credentials, and complete the release review
  and fixture/upgrade validation. No publication or customer deployment is
  part of this draft.
