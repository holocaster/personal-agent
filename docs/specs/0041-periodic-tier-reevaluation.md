# 0041 — Periodic Session-tier re-evaluation

Implemented, independently approved and merged to `main` on 2026-10-03. All R1–R16 passed the [ticket and whole-feature review](../../tickets/0041-periodic-tier-reevaluation/01-durable-periodic-session-tier.review.md); [ticket 01](../../tickets/0041-periodic-tier-reevaluation/01-durable-periodic-session-tier.md) is complete.

## Problem Statement

A Session's first request may be unrepresentative: a greeting can select easy before the user starts substantial work. Before this feature that choice lasted until a manual change. Users need a small, predictable number of opportunities for automatic selection to learn from their actual requests without judging answers or switching routes on technical failure.

## Solution

For a fresh Session, evaluate before routed tasks 1, 5 and 15 using all accumulated routed user messages. Automatic selection can raise the Session tier, never lower it. Manual selection suspends evaluation; `/model auto` requests one evaluation and resumes the remaining checkpoints without restarting them. Resume retains this policy and its input independently of the Conversation.

The confirmed [brief](../briefs/0041-periodic-tier-reevaluation.md) defines product scope. [ADR-0007](../adrs/0007-periodic-session-tier-reevaluation.md) amends ADR-0006's one-time evaluation policy; its single-route failure, Provider and spend decisions remain unchanged.

## User Stories

1. As a user, I want later requests to correct an unrepresentative initial choice, so that substantial work gets an appropriate tier.
2. As a user, I want evaluation before tasks 1, 5 and 15 only, so that its automatic cost and timing are predictable.
3. As a user, I want each evaluation to see all my accumulated routed requests, so that short follow-ups retain the context of what I requested.
4. As a user, I want answers, Tools, Question Tool answers, Memory and Skills excluded, so that selection reflects my tasks rather than generated or injected material.
5. As a user, I want failed and cancelled submissions to count, so that progress does not depend on successful answers.
6. As a user, I want retries and Tool follow-ups not to count as new tasks, so that repeated execution does not distort checkpoint timing or duplicate evaluator input.
7. As a user, I want automatic decisions never to lower a selected tier, so that easier follow-ups do not downgrade an ongoing Session.
8. As a user, I want manual selection to take effect immediately and suspend evaluation, so that my explicit choice is respected.
9. As a user, I want `/model auto` to use accumulated messages while preserving checkpoint progress, so that I can restore automation without starting over.
10. As a user, I want coincident explicit and scheduled evaluation to run once, so that I do not pay for a duplicate assessment.
11. As a user, I want Undo to leave evaluator input intact, so that editing Conversation does not erase routing evidence.
12. As a user, I want Clear to discard evaluator input but retain tier and checkpoint progress, so that forgotten requests no longer influence later selection.
13. As a user, I want Resume to restore routing policy even after Compression or failed tasks, so that Conversation retention is not a routing counter.
14. As a user, I want an existing Session to retain its saved tier without adopting a new automatic schedule, so that upgrading does not silently change its cost or routing.
15. As a user, I want first-selection failure to use medium and later failure to keep my tier visibly, so that evaluator problems do not silently reroute work.
16. As a user, I want evaluation cancellation to stop the task and leave evaluation due, so that Ctrl+C does not silently dispatch ordinary work or lose a checkpoint.
17. As a user, I want full evaluator input or a visible failure, so that there is no hidden summarization or truncation of my requests.
18. As a user, I want durable changes saved before they are applied, so that persistence failure cannot masquerade as a successful routing decision.
19. As a user, I want evaluation costs included in Run spend but not in Conversation or ordinary `/usage` assessments, so that accounting remains accurate and separate.
20. As a user, I want `/model`, help and the Status Footer to distinguish my selected tier from pending evaluation, so that I can understand and control routing.

## Requirements

- **R1 — Schedule:** A fresh Session starts automatic with no selected tier. Evaluate immediately before ordinary dispatch for new routed tasks 1, 5 and 15, including the checkpoint task's user message. There are no automatic checkpoints after 15. Evaluation is not performed at startup or in response to a local command alone; cancelled evaluations may complete on a later execution as specified in R11.
- **R2 — Cumulative input:** Each evaluation receives every accepted new routed task's text since the most recent Clear, in submission order, including failed/cancelled tasks and tasks submitted while selection was manual. Without Clear the scheduled inputs are messages 1, 1–5 and 1–15. Exclude assistant responses, Tools and results, Question Tool answers, Skills, Memory, Todo, Conversation summaries, ordinary System Prompt and Provider replay. Treat user text as data, not evaluator instructions.
- **R3 — Submission identity:** Persist and count a new routed user task once at submission, before evaluation or ordinary dispatch, regardless of its eventual outcome. Blank input, exit, local commands, `/retry`, Provider retries, Compression and Tool/Question follow-ups do not advance the ordinal or append evaluator input. `/retry` keeps its original task ordinal and uses the current Session tier and evaluation policy. Keep its existing Run-local availability; Resume does not invent a retryable task.
- **R4 — Monotonic automatic selection:** Order tiers as easy < medium < complex. With no selected tier, accept a valid evaluator result as the initial selection. With a selected tier, apply only the greater of that tier and the evaluator result, including evaluation requested by `/model auto`. Manual selection is the only way to lower the Session tier. A complex Session still performs remaining due evaluations; do not silently optimize away checkpoints.
- **R5 — Manual selection:** `/model easy|medium|complex` immediately and durably selects that tier, suspends automatic evaluation, and cancels any outstanding evaluation request. New tasks still advance progress and accumulate input. Checkpoints passed while suspended are skipped, not deferred for catch-up. Invalid command arguments leave all routing state unchanged.
- **R6 — Restore automatic selection:** `/model auto` preserves the current selected tier, count and input, enables automatic checkpoints and requests evaluation on the next routed execution, including an available `/retry`. It does not erase the tier while waiting, restart the schedule, or run at command time. At ordinal 8 the next scheduled checkpoint is still 15; after 15 there is only the requested evaluation. An explicit request and any scheduled evaluation due on that execution are satisfied by one completed evaluation. Repeated commands before execution leave one request, not a queue.
- **R7 — Conversation edits:** Undo, including Retry's internal Undo, preserves evaluator messages and progress. Clear discards evaluator messages, but preserves selected tier, ordinal, selection mode, remaining checkpoints and any evaluation request. Compression preserves evaluator input and routing progress. A Retry after Clear does not reinsert the old task into the discarded input. Agent Mode and Runtime Configuration edits do not reset routing policy.
- **R8 — Resume:** Resume restores tier, automatic/manual/legacy mode, submitted-task count, remaining checkpoint, accumulated evaluator messages and outstanding evaluation request through the existing Call Log. This works independently of successful Turn Ends, retained Conversation length, Undo, Clear and Compression, including an accepted submission with no Turn End because the process stopped. Restore state without an evaluator call at startup.
- **R9 — Existing logs:** A valid version-2 log without the new policy retains its saved selected tier and has no scheduled re-evaluation until `/model auto`. A saved pending state retains its already-requested one-time evaluation, not a newly inferred schedule. A log with no saved tier retains ADR-0006's visible medium compatibility fallback. Do not infer old ordinals, input or automatic/manual origin from Attempts, command audits or Conversation. Start durable counting/input collection at policy initialization on the first Run under this feature; `/model auto` activates the new schedule using that tracked progress/input. Malformed present new state fails Resume rather than falling back to compatibility mode.
- **R10 — Completed evaluation failure:** Keep same-easy-route transient retries and exact tier-label validation. An invalid/truncated/Tool-bearing answer, exhausted or non-retryable Provider error, or local preparation/counting/budget failure completes evaluation with a visible warning. With no selected tier choose medium; otherwise preserve the selected tier, even easy or complex. Consume the due checkpoint and explicit request on completed failure as on success; then attempt the ordinary task under its own Context Budget checks. Ordinary failure after completed evaluation does not restore the consumed checkpoint.
- **R11 — Evaluation cancellation:** Ctrl+C during preparation, dispatch or backoff records the existing interrupted Turn End, makes no ordinary dispatch for that execution, and leaves evaluation due without removing its submitted message or count. Retry or the next new task completes the outstanding evaluation with the then-current accumulated input; a new task still advances the count. A pending checkpoint is not replayed as multiple calls if another checkpoint has also become due: one completion satisfies due checkpoints through the current count. Manual selection can suspend/replace the pending decision under R5.
- **R12 — Full bounded request:** Send all accumulated evaluator messages in full if the complete easy-route request fits its effective input ceiling. Measure the fixed instruction and serialization overhead too. Oversized input follows R10 without an evaluator Provider call; do not truncate, summarize, window, recursively Compress or split it across paid evaluations. Reuse the existing output reserve and route-capacity rules rather than imposing a tiny one-word token cap. Ordinary Conversation budgeting and recovery remain separate.
- **R13 — Durable ordering and validation:** Persist initial policy, accepted submissions, command changes, Clear and completed evaluation state before corresponding live mutations or dependent dispatch. Even an unchanged tier after a completed evaluation must persist consumed progress. Observable partial appends restore the prior prefix; failed append or restoration stops further actions. Evaluator Attempt/detail, policy, submission and Clear persistence failures remain fatal with the existing CLI error/status-1 behavior, never evaluator fallback. Replay rejects malformed policy or submission records and preserves existing supported-version checks.
- **R14 — Accounting and separation:** Reuse normal Evaluator Attempt, retry, cost, redaction and optional Detailed Audit Payload paths, marked `purpose: "tier_selection"`. The Attempt's task remains the current executed task, not the serialized corpus. Every reported evaluator cost contributes to Run spend once, including failed Attempts; missing usage remains unknown and Estimated Cost provenance survives. Resume still resets spend. Evaluation adds no Conversation turn and does not replace the latest ordinary `/usage` assessment.
- **R15 — Existing routing guarantees:** Evaluation and ordinary execution share the task's immutable Runtime Configuration snapshot. Later configuration changes use current tier mappings without triggering evaluation themselves. Preserve same-route ordinary retries, Tool follow-ups, Context Overflow Recovery, Compression on easy, Tool Confirmation and Agent Mode boundaries; introduce no Escalation or new Provider path.
- **R16 — Presentation and documentation:** In interactive and piped modes show each completed evaluation's resulting Session tier, whether it was kept or raised, any failure reason, and `/model` guidance. `/model` reports selected/pending-initial tier, mode, next remaining checkpoint (or none) and outstanding evaluation when present. The Status Footer keeps the selected tier visible while re-evaluation is pending, separately from the last answer's model. Help explains tasks 1/5/15, suspension and `/model auto`; Clear's notice/help explains discarded evaluator input with preserved progress. Update concise user-facing identity/help and implemented-behavior documentation when this ticket lands, not during planning.

## Implementation Decisions

### Ownership and interfaces

The REPL remains the Session-lifetime owner; the ordinary Router still receives an explicit Tier. Use one small Session routing state value in the routing area to represent tier, mode, count, accumulated texts, next checkpoint and an explicit evaluation-request flag. Keep pure policy transitions together if needed for locality, without a policy framework, persistence adapter, Provider implementation or new dependency.

Extend the existing Call Log Conversation loader's routing return component to carry this state instead of only a tier string, and update the CLI, REPL and internal test callers together. Keep one ordered replay pass and the existing Conversation/Todo return components. No compatibility shim is needed for internal pre-1.0 Python imports; compatibility applies to stored logs.

Change the existing Evaluator interface to accept the ordered user-text collection plus the current executed task for Attempt attribution, the Runtime Configuration snapshot and protected keys. Return a valid candidate Tier or an explicit evaluation failure with a diagnostic, not an unconditional medium choice on failure. The REPL applies R4/R10, persists completion, displays the notice and dispatches. Propagate interruption and fatal persistence/audit errors. This keeps selection lifetime out of the Provider exchange path.

### Call Log contract

Extend version 2 additively. Keep `session_start.session_tier` and `session_tier_changed.tier/source` from ADR-0006. Add a `routing_policy` object to the start and each new tier-state record after initialization:

| Field | Values / meaning |
|---|---|
| `version` | Integer `1`; identifies this policy contract, not the outer Call Log version. |
| `mode` | `automatic`, `manual`, or `legacy` (no scheduled evaluation). |
| `next_checkpoint` | Integer `1`, `5`, `15`, or `null` after all checkpoints have passed/completed. |
| `evaluation_requested` | Boolean for an explicit one-time request; scheduled due state is derived from count and next checkpoint. |

| Record | Added durable data / replay effect |
|---|---|
| New `session_start` | Existing `session_tier: "pending"` plus policy version 1, automatic, next checkpoint 1, request false; count zero, corpus empty. |
| Existing `session_tier_changed` | Existing tier and source plus full policy fields. Writes command/evaluation completion even if tier unchanged; no repeated corpus snapshot. |
| New `routed_task_submitted` | Positive integer `ordinal` and string `task`: the exact accepted task text. Increment count and append once to corpus. |
| Existing `conversation_cleared` | Clear corpus as well as Conversation; no routing count/tier/policy reset. |
| Existing Undo/Compression/Turn End | No effect on routing corpus or progress. |

Every new record keeps the usual Session Id and timestamp. At submission, `ordinal` must equal prior count + 1; reject booleans as integers, gaps, repeats, missing/non-string/empty task text and submissions preceding policy initialization. When manual/legacy, submission advances `next_checkpoint` past checkpoints at or below that ordinal without evaluating. When automatic, submission preserves a due checkpoint until completion. Successful/failed completion advances past all checkpoints at or below current count and clears `evaluation_requested`; an earlier off-schedule evaluation must not skip a future checkpoint. `/model <tier>` skips already-due checkpoints as it suspends evaluation. `/model auto` preserves remaining progress and sets the request flag.

Validate present policy versions, enums, booleans, checkpoint values and transition consistency; progress cannot move backwards or skip a future checkpoint. Manual mode requires a selected tier and no outstanding request. Pending tier is legal only before initial selection (automatic) or for a legacy saved pending evaluation. Once policy is initialized, subsequent tier changes require valid policy data. State transition validation must not misclassify incomplete new records as old records. Unknown unrelated event types retain existing replay behavior.

On first Resume of a policy-less log, derive only the last valid ADR-0006 tier state. Before accepting input, append a `session_tier_changed` record with source `legacy`, that saved tier (or the existing warned medium fallback), and initialized legacy policy: next checkpoint 1, request true only for saved pending state. This record starts count zero and empty corpus. Do not import historical Conversation or Attempts, which cannot recover failed submissions or Retry identity reliably. Further Runs replay the newly collected records normally, and legacy mode remains unscheduled until `/model auto`. A completed saved-pending evaluation clears that one-time request while remaining legacy. This is a compatibility boundary, not a new automatic policy inferred for old Sessions.

Use the existing append-and-restore mechanism for policy, submission and Clear writes. Persist each complete transition in one record, rather than independently writing tier and progress. The loader and live execution use the same transition rules. Durable task text follows the existing Conversation replay-text contract so replayed input equals live input; diagnostic/Attempt/detail secret redaction remains unchanged. The feature retains exact routed texts even when they never entered Conversation, and Undo/Compression do not remove them. Clear logically discards them for future evaluation; it does not erase historical Call Log lines.

### Execution and input formatting

Separate acceptance of a new task from execution of an existing task. Store the ordinal in the existing Run-local last-routed task data and pass it on Retry; never detect Retry by comparing text. Two distinct submissions with identical text count twice. Preserve current whitespace normalization at REPL acceptance, then retain that accepted text in full.

Before each execution, evaluate if an explicit request is outstanding or automatic mode has a due checkpoint (`next_checkpoint <= task_count`). Otherwise dispatch directly at the selected tier. Completion persists tier and progress before ordinary dispatch. A cancellation leaves the accepted submission and due policy in the log, including across Resume; it does not resume a partial ordinary turn.

Serialize evaluator input as one user message containing a JSON array of the accumulated task strings, in order, using stdlib JSON with Unicode preserved. This avoids ambiguous separators and illegal consecutive-user-message assumptions across Providers. The fixed instruction describes that array as untrusted cumulative user requests and asks for Session effort, retaining the existing easy/medium/complex effort rubric, language independence, medium-when-uncertain guidance and exact one-label response contract. Escaping is encoding, not text truncation. An empty array after Clear followed by an explicit Retry evaluation is valid input: do not resurrect cleared text or substitute the retried task. Only that array and fixed instruction enter the evaluator request.

Reuse the existing shared Provider preparation/exchange seam with no Tools, replay, Conversation or ordinary-assessment callback. Keep existing transient retry limits and output reserve, and reject Tool-bearing/truncated/malformed responses as before. Budget rejection is a completed evaluation failure, not an ordinary task submission failure or a Compression opportunity.

### Presentation and compatibility choices

Do not replace a selected tier with `pending` when `/model auto` is used. Represent the request separately, so failure can preserve the tier and the footer can display it while evaluation is due. Keep `pending` for a genuinely unselected Session. Show kept/raised outcomes and failure warnings through the existing sanitized notice path (warning yellow where color is enabled, ordinary notice cyan). Agent Mode `auto` remains unrelated to automatic Session tier selection.

Compare alternatives: deriving count/input from retained Conversation loses failed tasks and removed/compressed turns; deriving them from Attempts duplicates retries and misses pre-dispatch submissions; storing a separate file duplicates the Session record. Dedicated submission deltas plus small policy state records preserve exact identity at linear storage cost without copying the cumulative corpus at every change. Reusing the HTTP fake and real temporary Call Log avoids a new high-level test or persistence seam.

## Testing Decisions

Use `run_repl` and CLI `main` as the primary public seams, scripted input/Input Box, the existing shared fake HTTP transport and real temporary Call Logs. Assert request sequences, decoded JSON evaluator arrays, visible notices/footer, resumed routing and spend, not private state-helper layout. Direct Call Log replay and append-failure tests cover malformed/partial records; narrower existing Router tests retain Provider/retry/budget/Tool guarantees. No paid API calls, judgment-quality benchmark, new framework or test-only production adapter.

Prior art: `tests/test_session_tier.py`, `test_repl`, `test_main`, `test_call_log`, `test_detailed_audit`, `test_audit_local`, `test_runtime_config`, `test_question_tool`, `test_preventive_compression` and `test_context_recovery`. Update the shared evaluator stub and resumed-state fixtures for the changed interface; preserve unrelated tests' isolation instead of adding compatibility plumbing for test-only old tuples.

Required observable matrix:

| Case | Proof / requirements |
|---|---|
| Fresh tasks 1–16 (and beyond), candidates easy → complex → medium | Exactly three evaluations, before 1/5/15; candidate 15 cannot lower complex; arrays contain exact prefixes; no later scheduled call (R1, R2, R4). |
| All initial labels; later higher/equal/lower labels; already complex | Correct dispatched tiers, including checkpoint calls despite no possible raise (R4). |
| Identical new submissions; failed/interrupted tasks; Retry; Tool/Question follow-ups; local commands | One ordinal/text per new submission only, no duplicate Retry text, failed/cancelled text included at later checkpoints (R2, R3). |
| Populated Memory/Skills/Todo, Tool results, Question answers, summary and assistant content | None appear in evaluator request; accepted multiline/Unicode/JSON-like task text round-trips in full (R2, R12). |
| Manual before first task and across tasks 5/15; explicit downgrade; invalid commands | No automatic calls while suspended, input/count retained and invalid args unchanged (R3, R5). |
| `/model auto` at count 8, at count 4 followed by task 5, after 15, repeated before execution, and with Retry | One next-execution evaluation, no restarted checkpoints or duplicate calls; selected tier retained until result, manual baseline never automatically lowered (R4, R6). |
| Undo; Clear before 5/15; Clear then auto + Retry; manual/preventive Compression | Counts/progress retained; Undo/Compression retain input, Clear removes it, Retry does not restore it (R3, R7). |
| Resume before 5/15; after failed/cancelled evaluation; manual/auto followed by exit; empty new Session; accepted submission without Turn End | Restored routing matches live state and full corpus, regardless of Conversation; no startup evaluation or invented Retry (R8, R11). |
| Policy-less selected/pending/no-tier logs, including misleading Attempt/audit history; opt-in then another Resume | Saved tier or old pending one-off retained without schedule; no-tier warning once; tracking starts at initialization; `/model auto` enables only remaining tracked checkpoints (R9). |
| Invalid label/case/text, empty/non-string, Tool call, truncated output; transient success/exhaustion; permanent/preparation/counting errors | Initial medium versus later preserved easy/complex, visible warning, consumed progress; ordinary failures do not repeat evaluation (R10). |
| Input exactly within versus beyond measured easy-route ceiling, including serialization overhead | Full fit request sent; overflow never sent, truncated or summarized; failure checkpoint consumed and ordinary route assessed separately (R12). |
| Cancellation at initial/later preparation, Provider dispatch and backoff; completion via Retry/next task; cancellation spanning another checkpoint | No ordinary dispatch on cancelled execution, due state survives, one completion covers due checkpoints with current cumulative input (R11). |
| Invalid policy types/version/fields, invalid ordinal sequence, incomplete new tier record | Resume rejects, not legacy fallback; valid old v2 logs still load (R9, R13). |
| Partial submission/policy/completion/Clear append; failed prefix restoration; evaluator Attempt/detail failure | CLI fatal path, no subsequent dependent dispatch or fallback; recovered prefix replays pre-transition state (R13). |
| Evaluator retry/failure costs, missing usage, detail purpose, Resume spend and ordinary `/usage` after evaluation-only cancellation | Charged once, purpose attribution/current task correct, no Conversation insertion or last-assessment replacement (R14). |
| Current mapping changes and shared snapshot; ordinary retry/recovery and Tools | Existing same-route/configuration/confirmation behavior retained (R15). |
| Interactive/piped notices, `/model`, help, pending footer and concise docs | No claims of one-time-only fresh selection or reset-on-auto; selected tier visible while pending, mode/checkpoint clear (R16). |

Validate incrementally with focused existing pytest suites, then run `uv run --offline pytest -q` for the completed ticket. Record actual results and counts; planning validation is not implementation verification.

## Out of Scope

Continuous automatic evaluation after task 15, automatic downgrades, answer-quality judging, technical-failure Escalation, schedule configuration, new Providers/dependencies, corpus summarization/truncation, importing inferred old task history, durable Retry availability, partial-turn execution recovery, cross-Run spend, concurrent Runs, crash-proof storage and unrelated refactoring. Do not modify model configuration for this feature.

## Further Notes

One end-to-end ticket is sufficient: all policy, input, commands and replay changes share the same small execution path, and splitting schema from its users would leave no independent feature. There is no existing 0041 fast-path ticket to fold in. Ordinary evaluator exchanges number at most three in a fresh uninterrupted automatic Session, but explicit `/model auto`, cancelled evaluation re-execution and transient Attempts can add calls; do not advertise an absolute three-call cost cap.

Planning preserved the implemented-behavior references until the implementation landed. README, CLAUDE.md, CONTEXT.md and the routing research now describe the delivered feature; `.ai/PROJECT_STATE.md` records completion and merge.
