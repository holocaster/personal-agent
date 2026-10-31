# 0041 — Periodic session-tier re-evaluation

Implemented, independently approved and merged to `main` on 2026-10-03. See [spec 0041](../specs/0041-periodic-tier-reevaluation.md), [ADR-0007](../adrs/0007-periodic-session-tier-reevaluation.md) and the [approved review](../../tickets/0041-periodic-tier-reevaluation/01-durable-periodic-session-tier.review.md). The brief preserves the discovery confirmed by the user on that date.

## Goal

Allow automatic Session tier selection to recover from an unrepresentative first task using accumulated user requests.

## Scope and settled decisions

- Evaluate before routed tasks 1, 5 and 15; there are no further automatic checkpoints after task 15.
- Each checkpoint receives all accumulated routed user messages: normally message 1, messages 1–5, then messages 1–15. This is cumulative input, not only checkpoint messages or a rolling five-message window; Clear explicitly discards prior evaluator input.
- Exclude assistant responses, Tools and their results, Question Tool answers, Skills, Memory and Conversation summaries from evaluator input.
- Count each new routed user task at submission, including tasks that fail or are cancelled. Local commands, `/retry`, Provider retries and Tool follow-ups do not advance the count; `/retry` reuses its task's position.
- Automatic re-evaluation may raise the Session tier, never lower it. Manual `/model <tier>` may lower it.
- Manual selection suspends automatic evaluation until `/model auto`, which requests evaluation on the next routed task and re-enables automatic checkpoints.
- `/model auto` preserves checkpoint progress and uses accumulated user messages. At task 8 the next scheduled checkpoint remains 15; after task 15 it requests one evaluation without restarting the schedule. An explicit evaluation coinciding with a scheduled checkpoint runs only once.
- Undo preserves evaluator input and checkpoint progress. Clear discards accumulated evaluator messages but preserves the Session tier and checkpoint progress.
- Resume restores checkpoint progress, accumulated evaluator messages and automatic/manual selection state through the existing Call Log, independently of retained Conversation history.
- Existing Session logs retain their saved tier without scheduled re-evaluation. `/model auto` explicitly activates the new automatic behavior; do not silently infer an automatic policy for old logs.
- Initial evaluation failure selects medium with a visible warning. Later evaluation failure preserves the current tier with a visible warning. A completed failed evaluation consumes its checkpoint; cancellation leaves evaluation due until it completes and prevents ordinary dispatch for the cancelled task.
- Send every accumulated evaluator message in full when it fits the easy-route input budget. Oversized input uses the same visible failure policy; no silent truncation or summarization.

## Out of scope

- Continuous evaluation after task 15, automatic tier downgrades, answer-quality judging or technical-failure Escalation.

## Open questions

None outstanding; discovery, planning, implementation and independent review are complete.

## Planning notes (historical discovery baseline)

The original discovery request excluded spec, tickets and implementation; those stages were subsequently authorized and completed.

Reuse the configured easy-route Evaluator, Call Log and existing retry, cost, visible tier notices and persistence guarantees. Evaluator exchanges stay outside the Conversation and count toward Run spend. Persistence failures remain fatal, not evaluation fallbacks. Before this feature, replay restored the tier but not its origin, and no dedicated task ordinal existed; retained Conversation length was not a reliable cumulative counter. The resulting spec defines durable representation, evaluator input formatting and compatibility details.

ADR-0007 amends ADR-0006's one-time evaluation policy. CONTEXT.md now describes the implemented behavior.

Research: [Session tier selection](../research/done/2026-10-02-session-tier-selection.md).
