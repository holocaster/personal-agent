# 0052: Session report and terminal streaming

## Goal

Deliver one feature that makes model activity visible while it runs and provides a local report of recorded latency, cost, cache and failures. The user selected opportunities 1 and 2 from `docs/research/done/2026-10-09-feature-opportunities.md` as one feature.

## Confirmed scope

- Add `/report` for the current Session across all its Runs, including prior Runs after Resume, computed from the existing Call Log without a model call.
- Show ordinary assistant text incrementally for every existing Provider: OpenRouter, OpenAI, Anthropic and Gemini. This is the user's explicit amendment to the original OpenRouter-first proposal. Streaming is the normal ordinary-task behavior, not an additional opt-in configuration.
- Preserve completed AssistantMessage, Tool validation/execution, Call Log accounting, Resume, continuation, Agent Mode switching and known-secret/control-character protections.
- Add recorded first-text timing for streamed exchanges so the report can distinguish first visible content from completion latency. Missing measurements remain unknown.
- Keep evaluator and Compression content out of ordinary streamed terminal output.
- No new dependencies, dashboard, MCP Tools, file checkpoints, background jobs, monetary cap or tier-policy changes.

## Evidence and implementation reach

- `providers/http.py:13-22` buffers the full JSON response; OpenRouter currently calls it without streaming (`providers/openrouter.py:25-56`). Shared Chat Completions parsing expects a completed message (`providers/chat_completions.py:55-70`).
- `terminal/repl.py:192-220,258-268` waits for routing before displaying the final answer. Streaming must coordinate with Spinner, busy input ownership, Tool confirmations/results and piped output without duplicating the final text.
- `routing/router.py:756-843` owns dispatch, timing, retries and Attempt logging. Its cumulative Attempt counter also advances for Tool follow-ups; it is not a technical retry count. Explicit `/retry` already records `routed_task_retried` separately.
- `call_log.py:562-610` records latency, cost, tokens, cache and optional purpose. Evaluator purpose is `tier_selection`; Compression currently uses task `/compress`. Make purpose/timing/retry attribution explicit where necessary, without treating legacy absent fields as zero or counting Conversation snapshots twice.
- `session_logs.py:126` provides a bounded record reader. Reuse existing safe storage and record-reading boundaries. Report unavailable, incomplete or malformed evidence honestly.
- Touch shared HTTP and all four Providers, Provider dispatch, REPL/terminal output, Attempt records/report aggregation, relevant tests and concise user documentation. Preserve current REST endpoints/API families rather than migrating vendors or adding SDK dependencies.
- Official streaming facts and sources were checked in the research note: SSE comments and split events, interleaved Tool arguments, terminal usage, and errors under HTTP 200 all require handling.

## Proposed minimal behavior

- `/report` groups Provider time and recorded spend by ordinary execution, tier evaluation and Compression; includes attempts, failures, technical retries and explicit user Retry separately, tokens/cache and first-text timing where available.
- Costs distinguish reported/estimated/missing coverage. Provider duration does not identify network, queue or generation causes. Human waiting and Tool durations are excluded unless existing audit evidence supports an explicitly labeled measurement.
- Stream text only; retain complete Tool calls for existing validation before execution. Never execute partial Tool arguments or accept an interrupted response as a completed turn.
- Treat first text, termination and usage as separate events. Continue to account for reported usage on failures; missing usage is unknown.
- Before any text is displayed, retain existing transient-retry policy. After visible partial output, stop with an incomplete-response notice and allow explicit `/retry` rather than silently replaying output.

## Settled decisions and documentation

- Commit and push of the completed feature are authorized. No paid live API verification is authorized. Tests use isolated fixtures and simulated responses.
- Current-Session report and explicit Retry after partial output remain the recommended defaults communicated to the user; the user's requested change is streaming for all current Providers. Historical Session selection and additional report modes are outside this delivery.
- OpenAI stays on Chat Completions: `stream: true`, optional final usage via `stream_options.include_usage`, indexed Tool deltas and `[DONE]`. The final usage choice array can be empty and interrupted usage may be absent. Sources: https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create and https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events (official page and Context7 checked).
- Anthropic keeps Messages API version `2023-06-01`. Accumulate indexed content blocks/partial Tool JSON and cumulative usage, recognize `message_stop` and stream error events, and keep thinking/signature deltas out of displayed text. Source: https://platform.claude.com/docs/en/build-with-claude/streaming (official page and Context7 SDK source checked; no SDK is being installed).
- Gemini stays on GenerateContent `v1beta`, using `streamGenerateContent?alt=sse`. Preserve native response parts, functionCall IDs, thoughtSignature and active replay across Tool follow-ups/Resume; omit thought parts from displayed text. Do not substitute the newer Interactions API. Sources: https://ai.google.dev/api/generate-content and https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures (official pages and Context7 checked).
- OpenRouter-specific usage/termination/error behavior is sourced in the research note. Current host preference remains `sort: price` plus `preferred_min_throughput: 85`.

No open product questions remain. Exact field names, terminal presentation, output bounds, implementation seams and ticket slicing belong to the planner.

## Execution state

Implementation and independent review complete for all three tickets and R01–R17. The exact reviewed snapshot, including the final filtered-completion correction, is recorded in `tickets/0052-session-report-streaming/feature.review.md`. Full installed suite: 2441 passed.
