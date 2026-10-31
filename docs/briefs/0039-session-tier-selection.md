# 0039 — Session tier selection

Implemented and merged to `main`; review polish landed in feature 0040. The original discovery decisions below are historical. Feature [0041](../specs/0041-periodic-tier-reevaluation.md) and [ADR-0007](../adrs/0007-periodic-session-tier-reevaluation.md) amend one-time evaluation, evaluator input and `/model auto`; single-route execution and removal of the monetary cap remain in force.

## Goal

Replace per-task heuristic classification with an LLM-selected Session tier and remove automatic Escalation.

## Scope and settled decisions

- The first routed task is evaluated through the configured easy route. The evaluator returns exactly `easy`, `medium` or `complex`; the selected tier handles the task and subsequent tasks.
- Show the selected tier and how to change it through `/model`. Technical evaluator failures use the existing same-route transient retry policy on easy; exhaustion selects medium with a visible warning. An invalid response selects medium immediately, without another evaluation.
- `/model <tier>` selects the Session tier directly. Before the first task it bypasses evaluation.
- Resume restores the latest selected tier, including a manual change immediately followed by exit. It does not automatically re-evaluate an already selected tier.
- `/clear`, `/undo`, `/retry` and Agent Mode changes preserve the current tier.
- `/model auto` requests one new evaluation on the next routed task, then fixes its result again. Local commands do not trigger evaluation.
- Pending evaluation survives Resume, both after `/model auto` and when a new session ends before its first task. The next routed task, including an available `/retry`, performs the evaluation. `/clear` preserves the pending state; `/model <tier>` replaces it with an explicit selection.
- Ctrl+C during evaluation cancels the task without dispatching it and leaves evaluation pending for the next task. Cancellation is not an evaluator failure that selects medium.
- The evaluator receives only the routed task and a fixed classification instruction, without Conversation history, Memory, Skills or Tools. This also applies to explicit re-evaluation after `/model auto`.
- The classification rubric selects easy for simple questions and localized changes, medium for bounded work with several steps, and complex for architecture, difficult investigation or broad system construction. Prefer medium when uncertain. Judge requested effort independently of language; text length is not a classification rule.
- Older resumable sessions without the new Session tier state start at medium with a visible warning and permit manual selection through `/model`; do not automatically evaluate them on Resume.
- Remove the heuristic Classifier and Escalation. Keep same-route transient retries; exhausted retries surface an error for the user to handle with `/model` and `/retry`.
- Remove `PA_BUDGET_USD`, its escalation gate and limit display. Retain accumulated Run spend in the Status Footer and `/usage`, including evaluator, ordinary-task and Compression costs. Do not introduce a replacement monetary cap; spend still resets on Resume.
- Tiers remain configurable model slots through `/config`. Compression continues using easy independently of the Session tier.
- Update README, CLAUDE.md and CONTEXT.md to describe the new identity and behavior when implemented.

## Out of scope

- Continuous automatic reclassification, answer-quality judging, and automatic switching to another tier after technical failure.

## Open questions

None for product scope. The user confirmed all discovery decisions.

## Planning notes

Reuse the existing Call Log for durable tier state. Successful manual tier changes already have audit records; do not infer them exclusively from Provider Attempts, which miss changes followed immediately by exit. The planner owns the exact representation and compatibility handling after product decisions settle.

The planner also owns the evaluator prompt wording, bounded output allowance, reuse of Provider retry/accounting/audit paths, and replacement of obsolete Budget Guardrail terminology while retaining spend tracking. Keep evaluator exchanges separate from Conversation turns and the ordinary-exchange context information displayed by `/usage`; retain the existing persistence-failure guarantees.

Removing Escalation supersedes ADR-0001. Session tier persistence extends the record described by ADR-0005. Keep CONTEXT.md's implemented behavior accurate until implementation updates it.

Research: [Session tier selection](../research/done/2026-10-02-session-tier-selection.md).
