# 0002 — Router reliability

## Goal

`route()` today makes exactly one Provider call per task and gives up on any error. This feature adds retry on transient failures, Escalation to a higher Complexity Tier when a tier's Attempts are exhausted, and a Budget Guardrail that can block an expensive Escalation — so a single flaky call doesn't fail a task the Router could otherwise have completed.

## Scope

- **Retry**: `provider.call_openrouter()` gets up to 3 Attempts per call, exponential backoff 0.5s / 1s / 2s. Retryable: network timeout, HTTP 429/500/502/503/504. Everything else (4xx other than 429, parse errors) fails on the first Attempt. Applies uniformly at every Complexity Tier, initial and escalated.
- **Escalation**: `router.route()` walks Complexity Tier order upward (easy → medium → complex) when a tier's Attempts are exhausted and it still failed. Trigger is technical failure only (`RouteResult.error is not None`) — never a judgment on the answer's content. See ADR-0001. If complex also fails, same contract as today: `RouteResult(error=...)`, REPL prints `Error: {result.error}` unchanged.
- **Budget Guardrail**: in-memory cost accumulator scoped to one REPL process/session (not the Call Log file — see `docs/CONTEXT.md`). Configured by optional env var `ROUTER_BUDGET_USD`; unset disables it entirely (today's behavior). Only gates Escalation to a more expensive tier — never blocks the Classifier's originally-picked tier. When it blocks, the returned error names the block explicitly (e.g. `"budget exceeded, not escalating to {tier}"`) — no new field on `RouteResult`.
- **Call Log**: one entry per Attempt (every retry, every escalated tier), not one summary entry per `route()` call. Existing schema preserved, gains a field identifying the Attempt within its chain (tier + attempt number).

## Out of scope

- Manual tier override in the REPL — separate feature, planned later.
- Any content-quality/answer-looks-wrong heuristic for triggering Escalation — explicitly rejected, see ADR-0001.
- Multi-provider support, LLM-based Classifier, any agent/tool-calling loop, memory, skills, scheduling.

## Settled decisions

See `docs/CONTEXT.md` (`Attempt`, `Escalation`, `Budget Guardrail`, `Call Log` glossary entries and the two new Decisions bullets) and `docs/adrs/0001-escalate-on-technical-failure-only.md`.

## Open questions

None — grilling frontier closed and confirmed by the user.
