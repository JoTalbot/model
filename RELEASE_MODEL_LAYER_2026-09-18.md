# Model Layer Release Gate — 2026-09-18

## Scope

This release batch hardens the LLM model layer represented in this repository. It does not claim that the entire historical host snapshot is a production deployment.

## Included

- Canonical LLM balancer at `octopus-aios-integration/worktree/swarm/llm/balancer.py`.
- Backward-compatible legacy re-export at `code/llm/balancer/llm_balancer.py`.
- No silent prompt truncation in the affected providers.
- No separate 4000-character cloud-only rejection before routing.
- Dynamic router autotuner imports the canonical balancer and tunes weights per tier.
- Strict Arena provider is excluded from generic autotuning.
- Release regression tests for prompt preservation, fallback, emergency fallback, Arena tiering, and legacy import compatibility.

## Acceptance

1. Static source inspection: PASS.
2. Legacy import compatibility: covered by release test.
3. Prompt preservation: covered by release test.
4. Provider fallback: covered by release test.
5. Emergency fallback: covered by release test.
6. Full runtime E2E through `9700 -> shim -> 9600 -> provider`: NOT VERIFIED by this repository-only batch.
7. Live provider credentials / production services: NOT VERIFIED.
8. Full target-runtime pytest suite: NOT VERIFIED in this GitHub-only execution context.

## Release rule

The code changes in this batch are suitable for merging as the model-layer hardening release. Production deployment remains a separate operational verification step because this repository is a host snapshot/inventory and contains references to external runtime paths.
