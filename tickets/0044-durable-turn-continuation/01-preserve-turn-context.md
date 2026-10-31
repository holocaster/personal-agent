# 01: Continue failed turns with durable context

**What to build:** Make `/retry` continue a failed or interrupted routed turn with its collected questions, answers and Tool results, including after `--resume`, instead of silently restarting the work. The user explicitly chose durability across restarts.

**Blocked by:** Feature 0043 schema/error correction (implemented locally; focused checks passed).

**Spec:** none (single-slice ticket; acceptance criteria are normative)

## Acceptance criteria

- [x] A round-limit failure or failed Tool-follow-up returns an explicit continuation snapshot of the pending task and completed message prefix. `/retry` includes the exact completed questions/answers/results once and does not automatically re-execute Tools already represented by results.
- [x] The retry uses current tier/model/Provider/configuration, mode, available Tools and confirmation policy. A fresh round allowance uses `PA_MAX_TOOL_ROUNDS`; retry does not increment routed task ordinal, duplicate evaluator input or restart checkpoint progress.
- [x] A completed retry commits one combined complete turn; repeated failures replace the pending snapshot without duplicating prior messages. Successful-turn retry retains existing intentional rerun/Undo behavior.
- [x] Persist the pending state explicitly in the existing Call Log on error/interruption, with task attribution and original ordinal. `--resume` restores it and makes `/retry` available for that pending turn. Preserve `load_conversation` compatibility and keep incomplete turns out of completed Conversation/history/Compression.
- [x] Clear discards continuation context, a new routed user task supersedes the pending task, and a successful Undo cannot revive discarded pending state. Model/config/Agent Mode commands and manual Compression do not discard valid pending state. No attempt-log heuristic reconstructs old unrecorded partial turns.
- [x] Preserve Todo state and fetched-URL tracking from retained Tool results. Continuation rebases to current older-history/summary after Compression, protecting the complete pending prefix under existing context budgeting.
- [x] Same-route Gemini continuation preserves exact original parts/thought signatures and generated-id behavior, including after restart; route changes use existing normalized cross-Provider translation and never reuse another route's raw replay.
- [x] Interruption after completed Tools preserves those results. If a batch is interrupted, retain actual completed results and represent unfinished calls clearly as not completed; never silently claim an unfinished operation executed or replay a completed operation. Requests sent to Providers keep correctly correlated Tool calls/results.
- [x] New persisted state is validated before dispatch; malformed versions/types/message graphs/replay fail visibly. Existing v2 logs without continuation keep their existing completed history and load normally. New writes follow existing persistence-failure handling; no silent fallback after a failed state write.
- [x] Retain existing credential redaction for any new persistent messages/replay. No new file/database/dependency, automatic escalation, automatic background retry, or changes to generated ERP code.
- [x] Help/README/current behavior docs explain continuing failed turns, successful reruns, Clear/new-task behavior and restart compatibility. Tests cover real REPL/Call Log/Provider seams and all four Providers; combined full suite passes.

## Execution guidance

Reuse RouteResult, the Router's existing pending message prefix and Provider replay, REPL last-task state, and Call Log. A small continuation value/helper is appropriate only where needed to share validated state without import cycles; avoid another conversation store or broad refactoring.

At a limit boundary, preserve the last completed prefix. Unexecuted Tool intentions may be requested again from that prefix; do not store/send an unmatched assistant Tool batch as if it had results. Gemini replay includes the latest raw response, so an unexecuted response must not contaminate a completed-prefix continuation. Partial batches must retain actual completed results with explicit unfinished outcomes and correct correlation.

The original problem was proved in session `20261005T092917Z-p6b4c8`: error Turn End omitted pending context, and subsequent OpenAI/GLM requests had only the original completed turn plus `go for option B`, losing all six co-design answers and Tool work. Build a focused failing end-to-end continuation regression before fixing, then implement in increments. Use actual temp Call Logs and mocked HTTP, never real Provider calls.

Preserve all earlier local changes and do not commit or push. The schema fix has 257 focused passing tests; feature 0042 has 1851 passing tests before schema additions. Run the combined full suite once after continuation focused checks pass, with approved local-socket test access if needed. Independent reviewer creation is limited by this session's agent capacity; report coverage accurately.
