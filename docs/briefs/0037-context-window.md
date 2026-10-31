# 0037 — Context Window

## Goal

Replace the fixed 20-turn Context Window with a configurable total token budget, respecting smaller known route limits and preserving recent conversation through preventive Compression.

## Scope

- A global, user-persistent Context Budget defaults to 250000 tokens and is editable through `/config`. Changes apply to subsequent tasks; a task retains the configuration it started with.
- Account for history, the current task, System Prompt, Memory, skills, Tool definitions/results and reserved output within the total budget.
- Use the smaller of the configured budget and the known route capacity, with manual capacity overrides. Distinguish an unknown capacity from a verified limit or an assumed fallback.
- Compress older turns preventively, preserving the two most recent complete turns and the in-progress turn. Surface Compression and its failures; never silently discard content on failure.
- Reserve up to 16000 output tokens per exchange, bounded by route output capability and explicitly enforced by each Provider, including reasoning where it shares that allowance. Keep a 10000-token estimation/overhead margin; respect any separate input ceiling. For a 250000-token total capacity without a tighter input limit, the input ceiling is 224000 tokens.
- Trigger preventive Compression at 80% of the effective total budget and aim for 60% input occupancy, subject to the input ceiling and preserved content. Check before Provider exchanges, including Tool follow-ups and Escalation.
- Without valid metadata or a manual capacity override, assume 128000 tokens and visibly label the capacity unknown and the value assumed. This is not a verified capacity; the configured Context Budget remains unchanged.
- If preserved input cannot fit after eligible older turns are compressed, stop visibly without silently cutting the task, instructions or Tool results. Preserve the record of already executed Tools and their outcomes; never automatically re-execute them.
- Use bounded, budget-fitting blocks for Compression through the easy route and combine their summaries within the same constraints. Replace the Conversation only after the complete Compression succeeds; failures retain the prior Conversation. Multiple summarization exchanges are allowed and contribute to normal cost accounting.
- For a Provider rejection specifically caused by context overflow, permit one recovery retry of that rejected exchange after a safe reduction of older context. If no safe reduction is possible or the retry fails, surface the error. Never repeat already executed Tools as part of recovery.
- Preventive Compression proceeds with the pending task/exchange instead of launching a synthetic Continuation Turn. Manual `/compress` summarizes without starting another task.
- Estimate the complete model-facing input locally with LiteLLM's token-counting utility, without additional paid token-counting requests. Do not substitute byte count for token count. `/usage` distinguishes configured/effective budget, known/assumed capacity, input ceiling, output reserve, last-request estimated input and Provider-reported input usage when available. Cached tokens still occupy context and are not deducted.

## Out of scope

- Semantic relevance ranking of history, silent truncation of tasks or Tool results, automatic replay of executed Tools, and a new partial-turn Resume mechanism.
- A new metadata service, paid token-counting requests, or a new context-monitoring UI beyond the existing configuration, usage and compression notices.

## Settled decisions

1. The default 250000 tokens represent a total budget, including reserved output, rather than an input-only allowance or a claim about model capacity.
2. Configuration is global and persistent, using the existing `/config` entry point and applying between tasks.
3. Smaller known route capacities reduce the effective budget; reuse current metadata with manual overrides and explicit unknown-capacity reporting.
4. Prefer preventive Compression to silently omitting older turns; preserve complete recent turns and the current turn.
5. Reserve up to 16000 output tokens with explicit Provider caps and a 10000-token estimation margin; the effective input ceiling must account for route-specific input/output restrictions.
6. Trigger at estimated input reaching 80% of the effective total budget and aim for input at 60%, checking before every exchange rather than only after a completed turn. At an effective total of 250000, the trigger is 200000, the target is 150000 and the independent mandatory input ceiling is 224000 without tighter route restrictions.
7. Unknown capacity uses a visibly assumed 128000-token fallback unless overridden manually.
8. Preserved-content overflow stops visibly and retains Tool execution evidence without silently truncating content or repeating Tools.
9. Keep the easy route for Compression, splitting older turns into fitting blocks and committing the replacement only after all summarization succeeds.
10. Permit one context-overflow recovery retry per rejected Provider exchange, only after safe older-context reduction and without repeating Tools.
11. Remove synthetic post-Compression Continuation Turns; continue only the already pending task/exchange.
12. Use LiteLLM for local token-count estimates and expose their distinction from Provider-reported usage through `/usage`; cached tokens count toward occupancy. The user explicitly rejected one-byte-per-token estimation and approved extending LiteLLM beyond metadata to token counting, while keeping Provider calls and routing hand-rolled.

## Open questions

None for product scope; the user confirmed the discovery. The planner owns configuration names and capacity-override representation, the local estimator and its failure behavior, metadata normalization without confusing input versus total/output limits, bounded summary construction, Provider-specific overflow classification, Provider replay state with intact Tool call/result pairs and atomic Compression/Call Log updates. The 60% target is best-effort under preserved-content constraints; the input ceiling remains mandatory.

Research: [Context Window and route capacity](../research/done/2026-09-29-context-window-routing.md).

## Review-discovered correction

Independent review of 0037/04 reproduced a pre-existing violation of R6: an Anthropic summary stopped with `model_context_window_exceeded` was accepted and committed as complete. The correction is planned in `tickets/0037-context-window/05-reject-context-truncated-summaries.md` (`0037/05`), blocked only by 04 and outside ticket 04's accounting correction. Preserve the approved 01-03 checkpoints and existing product scope; the correction must reject unfinished summaries and prove original live/replayed Conversation remains intact.

## Whole-feature review correction (0037/06)

A post-approval review proved two defects. (1) LiteLLM publishes only `max_input_tokens`/`max_output_tokens`, and the former rule forbade using either as total, so every route without a manual override resolved to `unknown; assumed 128000` and the 250000 default never took effect (Claude 200000, gpt-5 272000 and Gemini 1048576 input all got a 102000 input ceiling). (2) A failed soft-trigger Compression stopped a task whose estimate (210000) fit the mandatory ceiling (224000), and a summary-only Conversation was re-summarized, paid, on every exchange above 80%.

Settled with the user (2026-10-02), superseding the earlier R2 prohibition on `max_input_tokens` as total:

13. When no total is published or overridden, a valid published `max_input_tokens` is the route's known total capacity: a conservative lower bound, since the real window is never smaller than the input limit. It applies to every Provider, including OpenRouter, labeled at its actual scope (`published model-wide` there); overflow recovery covers a smaller unpinned upstream. The assumed 128000 remains only when neither metadata nor an override supplies a total. Never sum input and output maxima.
14. The 80% soft trigger fires only when older complete turns are eligible. Reducing a previous summary alone happens only when input exceeds the mandatory ceiling or during overflow recovery.
15. If Compression started by the soft trigger alone fails and the unchanged input fits the mandatory ceiling, show a visible failure notice, commit nothing, and send the pending exchange. Failure still stops the exchange when input exceeds the ceiling or during recovery.

## Known issue outside this feature

Gemini's existing cost estimate uses `candidatesTokenCount` without `thoughtsTokenCount`; this predates feature 0037 (`52b4583`). Google documents both as billed generated output in its [thinking pricing guide](https://ai.google.dev/gemini-api/docs/generate-content/thinking#pricing). Record this for a separate accounting correction; ticket 0037/01 preserves existing completion/cost semantics while preventing capped empty responses from losing their returned usage.
