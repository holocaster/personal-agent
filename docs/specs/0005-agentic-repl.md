# 0005 - Agentic REPL

Brief: `docs/briefs/0005-agentic-repl.md`
Vocabulary: `docs/CONTEXT.md`
Constraints: ADR-0001 (technical-failure Escalation), ADR-0002 (hand-rolled REST Provider Contract).

## Problem Statement

The terminal currently answers each line independently. Users cannot ask follow-up questions, inspect or clear their Conversation, discover their configured models locally, or have a model use a calculator or clock. Provider responses are reduced to text, losing the information needed to execute and answer Tool calls.

## Solution

Keep one in-memory Conversation per REPL process, expose local slash commands, and route each new user request with its recent complete turns. Extend the existing Provider Contract to exchange normalized Tool calls and results, then run two bounded, allow-listed local Tools until the selected model provides its final answer. All four Providers remain direct REST integrations.

## User Stories

1. As a terminal user, I want a visible prompt, so that I know when input is expected.
2. As a terminal user, I want compact Complexity Tier, Provider, and model metadata, so that I know who answered.
3. As a terminal user, I want follow-up requests to include Conversation context, so that I need not repeat myself.
4. As a terminal user, I want each new request classified independently, so that follow-ups can select a different Complexity Tier.
5. As a terminal user, I want recent context bounded by complete turns, so that a long session does not send its entire record every time.
6. As a terminal user, I want Tool calls and all their results kept together, so that truncation never creates an invalid exchange.
7. As a terminal user, I want `/history` to display all completed turns, so that I can inspect more than the current Context Window.
8. As a terminal user, I want `/clear` to forget the Conversation, so that I can start a new topic in the same process.
9. As a terminal user, I want `/help` to explain the commands, so that I can discover them without a model call.
10. As a terminal user, I want `/models` to show the configured tier mappings, so that I can inspect my setup locally.
11. As a terminal user, I want `/exit` and existing exit behavior, so that leaving the REPL stays predictable.
12. As a terminal user, I want unknown slash commands reported locally, so that a typo does not spend money.
13. As a terminal user, I want arithmetic delegated to a calculator, so that a model can use an actual numerical result.
14. As a terminal user, I want a model to read the current UTC time, so that it need not guess the clock.
15. As a terminal user, I want the same Tools available through every Provider, so that my tier mappings do not determine feature availability.
16. As a terminal user, I want all calls in a requested Tool batch answered, so that a model can combine multiple results.
17. As a terminal user, I want invalid Tool arguments returned as errors, so that the model can correct them within bounded work.
18. As a terminal user, I want models unable to use Tools to fail explicitly, so that capability limitations are visible.
19. As a terminal user, I want Tool follow-ups to stay with the selected Provider and model, so that one request has a coherent execution context.
20. As a terminal user, I want transient failures retried without repeating Tool execution, so that recovery is safe and predictable.
21. As a terminal user, I want failed and interrupted requests to leave earlier Conversation turns intact, so that I can continue using the REPL.
22. As a terminal user, I want Tool-related Provider calls included in Call Log and Budget Guardrail accounting, so that spending is not hidden.
23. As a terminal user, I want `/clear` to retain session spending, so that clearing context does not bypass the Budget Guardrail.
24. As a terminal user, I want bounded Tool execution with no shell, files, or network access, so that model requests remain within the advertised capabilities.
25. As a maintainer, I want the existing HTTP test seam to prove the whole interaction, so that no paid calls are needed for acceptance tests.

## Implementation Decisions

The numbered requirements below are normative. Data class names and internal helpers are implementation choices; prefer small additions to the existing REPL, Router, and Provider modules.

### Session interface

- **R01 — Prompt and output.** Print and flush `user> ` before awaiting input on an interactive terminal. Preserve iterable input and captured output for piped use and tests; redirected input need not receive prompts. Successful requests display one compact routing line naming the effective Complexity Tier, Provider, and model, then prefix the final model answer with `llm> `. Keep metadata separate from answer text. Do not stream intermediate model output.
- **R02 — Local commands.** After trimming surrounding whitespace, handle `/help`, `/clear`, `/history`, `/models`, and `/exit` locally. `/help` describes all five commands; `/models` lists all three tier mappings from loaded Tier Config without listing remote models or secrets; `/history` renders completed turns in order with distinguishable user, assistant, Tool request, and Tool result entries, including full arguments/results. Empty history has a readable empty-state message. `/clear` acknowledges clearing. Unsupported slash commands or arguments to these argument-free commands produce a local error/help hint. None call the Classifier or Provider, append an Attempt, or add Conversation messages.
- **R03 — Existing terminal behavior.** Ignore blank input; retain bare `exit` and `quit`, EOF, and idle Ctrl-C as exits. Ctrl-C during a request or retry wait prints the existing interruption notice and returns to input. An ordinary routed error prints one readable `Error:` line and leaves the REPL usable.

### Conversation and Context Window

- **R04 — Ownership and commit.** The REPL owns one Conversation, initially empty. A complete turn begins with one user request, includes every intermediate assistant Tool request and corresponding Tool result, and ends with a final assistant response. Build the pending turn separately and append it only on successful completion. Failure or interruption discards the entire pending turn, preserving previous completed turns and any costs/Attempts already recorded. No Conversation is saved to disk. Existing Call Log task text remains unchanged in purpose; do not extend it into a transcript store.
- **R05 — Window selection.** For a new request, send the most recent 20 completed prior turns, oldest to newest, followed by that new user request. The pending request is not one of those 20 completed turns. Keep the entire completed Conversation in memory for `/history`; window selection does not delete it. During Tool follow-ups retain the same selected prior turns plus the entire pending turn. Never select individual messages, prune Tool results, or summarize content. `/clear` removes all completed turns, but does not reset Tier Config or the Budget Guardrail.
- **R06 — Routing with context.** Classify only the new request text once, using existing Classifier rules. Forward the selected history through the Router to any Provider. A later user request can change Provider/model and must still receive the complete normalized history. Keep system instructions separate from stored turns. Extend `route` with optional history and its result with the completed turn needed by the REPL; existing standalone `route(task, config, budget)` callers still work.

### Provider Contract and translation

- **R07 — Normalized exchange.** Extend `call(model, system, messages, tools=...)` to return a structured assistant message plus the existing normalized usage. An assistant message retains text, ordered Tool calls, and optional Provider-owned replay data. Each Tool call carries a stable ID, name, and arguments; malformed arguments must remain representable so the Tool boundary can reject them. A Tool result carries the matching ID and name, JSON-serializable result/error data, and an error indicator. Tool definitions carry a name, description, and object parameter schema. The Router handles this common shape without inspecting vendor fields. A successful text-only answer remains valid when Tools are offered. Never equate “no Tool calls” with unsupported Tools.
- **R08 — REST formats and replay.** Keep the current endpoints, auth, timeout, error taxonomy, and cost normalization. OpenRouter and OpenAI use Chat Completions `tools` entries with nested `function`; assistant `tool_calls` contain IDs and JSON-string arguments, followed by `role: tool` messages with `tool_call_id`. Anthropic uses `tools[].input_schema`, assistant `tool_use` blocks, and one following user message containing all matching `tool_result` blocks; error results set `is_error`. Gemini keeps `generateContent`, translating definitions to `functionDeclarations`, requests to model `functionCall` parts, and results to user `functionResponse` parts. Match each result's name and any returned call ID. Where an older Gemini response omits an ID, generate a stable internal ID for correlation without changing the original replay payload. Preserve original assistant blocks/parts and required metadata for same-Provider/model replay, including Gemini `thoughtSignature` in its exact original part and order. Do not expose opaque replay data in `/history`, send it to another Provider/model, or replace signatures with invented values. Translate cross-Provider completed turns from normalized messages, preserving text, calls, results, and correlation. Gemini's current-turn signature requirement is satisfied by pinning the active loop and replaying its original parts.
- **R09 — Capability failures.** Every agentic Provider request advertises both Tools, including follow-ups. Never catch a tools-not-supported error and repeat the request without definitions. Return a readable non-retryable error identifying the selected Provider/model when its API rejects Tool support; do not Escalate that failure. OpenRouter requests set `provider.require_parameters: true` so unsupported tool parameters cannot be silently dropped by upstream routing. Do not add speculative model-name capability heuristics or paid startup probes.

### Built-in Tools and execution

- **R10 — Calculator.** Expose `calculator` with exactly one required string argument, `expression`. Support numeric literals, parentheses, binary `+`, `-`, `*`, `/`, and unary `+`/`-`. Evaluate a restricted arithmetic syntax tree; never use `eval`, `exec`, imports, callable lookup, or subprocesses. Reject names, attributes, function calls, indexing, collections, booleans, and all other operators. Bound expressions to 256 characters and 64 syntax-tree nodes; reject non-finite or excessively large values (absolute value above `1e100`) at literals and intermediate/results. Return a JSON object containing `result`, or a bounded readable error for invalid syntax, limits, or division by zero. This intentionally small grammar requires no dependency or extensible evaluator framework.
- **R11 — Clock.** Expose `current_time` with an empty object schema and no arguments. Return a JSON object containing `utc_time`, an ISO-8601 UTC timestamp with an explicit UTC suffix/offset from the local system clock. No remote service or timezone-selection feature is needed.
- **R12 — Tool boundary.** Use a fixed mapping containing only these two built-ins. Validate argument JSON, object shape, required keys, exact types, and unexpected keys locally; Provider schema enforcement is insufficient. Unknown names and malformed arguments produce one correlated error result without invoking a Tool. Execute valid calls serially in response order, returning one result per requested call before asking the model again. Multiple calls to the same Tool are allowed when their IDs differ. Missing/duplicate IDs or another unusable call envelope are protocol failures: fail the pending turn before executing any part of that malformed batch, except for Gemini's documented optional ID normalization. Never treat model text as executable code.
- **R13 — Bounded loop.** A response containing Tool calls starts a Tool round; retain any accompanying assistant text in that turn, execute the batch, append all results, and call the same Provider/model with the updated messages and definitions. Finish when a valid assistant response contains no Tool calls. Allow at most 8 executed Tool rounds and 16 Tool calls per response. A ninth requested round or oversized batch ends the request with a readable limit error before executing that batch; after the eighth round the model still gets one opportunity to return a final answer. Keep the REPL usable and discard the unsuccessful pending turn. These fixed safety limits are implementation bounds, not new configuration or token compaction.

### Reliability and accounting

- **R14 — Pinning and retries.** On the first Provider exchange, retain existing transient retry/backoff and technical-failure Escalation, subject to the Budget Guardrail. The Provider/model producing the first successful Tool request becomes pinned for the rest of that user request. Each subsequent exchange gets the existing transient Attempt budget on that same Provider/model; exhaustion ends the request without Escalation. Permanent errors fail immediately. Retry the Provider exchange with identical messages and previously computed Tool results; never restart the turn or re-execute Tools because the HTTP follow-up failed. Tool validation/execution errors are results for the model, not triggers for retry or Escalation. This is a narrowing of permitted Escalation during an active Tool loop, as required by the brief; ADR-0001's technical-failure-only condition remains intact.
- **R15 — Attempts and cost.** Log every Provider Attempt, including Tool-request and final-answer exchanges, with existing keys and cost provenance. Keep `task` equal to the original user request. Continue 1-based `attempt` numbering within the selected tier across its exchanges (reset on Escalation); use a separate local retry counter for each exchange's retry allowance. Record each returned usage cost exactly once in the session Budget Guardrail, even if a later Tool limit, validation failure, or interruption aborts the turn. Tool execution itself is not a Provider Attempt. Preserve existing no-entry behavior for an interrupted in-flight Attempt. `/clear` must not erase Call Log entries or session spending. The Budget Guardrail still gates only Escalation, not originally selected calls or pinned follow-ups.
- **R16 — Documentation and constraints.** Update concise usage documentation for commands, history lifetime, the 20-prior-turn window, both Tools and their bounds, Tool-capable model requirements, and pinned follow-up behavior. Retain the dependency-free REST calling layer and LiteLLM pricing-only boundary. Do not introduce vendor SDKs, a general Tool framework, or persistent Conversation storage.

## Testing Decisions

Use externally observable behavior at the existing `run_repl`/`route` entry points and shared `model_router.providers.http.urlopen` boundary. Script complete vendor-shaped JSON responses and capture actual requests; do not replace Providers with mocks that hide serialization. Prior art is `tests/test_repl.py`, `tests/test_routing.py`, `tests/test_provider.py`, `tests/test_call_log.py`, `tests/test_budget.py`, and the shared fake fixtures. Use deterministic clock injection/patching only to check clock output; a small direct calculator test set is appropriate for its security boundary.

- Prove zero Provider calls and zero log entries for each command, blank input, and invalid commands. Prove exact `user> ` and `llm> ` labels, separate routing metadata, TTY prompt flush and clean piped behavior, plus existing interrupt/exit semantics.
- Drive at least 21 successful turns; inspect request payloads at the 20/21 boundary and full `/history`; exercise `/clear` after costs accrue and verify both empty context and unchanged spending.
- Script calculator -> result -> final answer and clock -> result -> final answer through each of the four Providers, asserting exact vendor request structure and final Conversation/history. Cover plain text and mixed text/Tool responses.
- Cover a multi-call batch, consecutive Tool rounds, subsequent user requests selecting a different Provider, and a full Tool turn exactly at the Context Window boundary. Assert no partial Tool turn is sent.
- For Gemini, cover IDs present/absent and signed multi-part responses over more than one Tool round. For Anthropic, assert all result blocks immediately follow the matching assistant batch.
- Demonstrate unknown Tools, malformed argument JSON, wrong argument types, extra keys, calculator code-like inputs, division by zero, expression limits, malformed correlation, and round/batch limits without executing unauthorized actions or leaving poisoned history.
- Script initial retry/Escalation, retry of a pinned follow-up, pinned exhaustion, capability rejection, and interrupt after a successful Tool request. Assert fixed Provider/model, Tool execution once per call, one log entry per completed Attempt, cumulative costs, and preserved earlier history.
- Run the existing full offline suite after each ticket. No live credentials, paid requests, or unrequested smoke calls are needed for acceptance. Fake HTTP tests prove wire behavior and control flow; they do not certify every arbitrary model's Tool capability.

## Out of Scope

Conversation persistence/resume; cross-session memory; shell, filesystem, network, user-defined or remote Tools; streaming; token-budget compaction, summaries or pruning Tool outputs; remote model catalogs; new Providers; new API families; a model-based Classifier; parallel Tool execution; advanced calculator functions or configurable timezones.

## Further Notes

Provider schemas were researched with Context7 on 2026-09-22 before defining this contract. The repository currently uses Chat Completions, Messages, and `generateContent`; newer API families appearing in documentation do not authorize an endpoint migration in this feature.

- [OpenRouter Tool calling](https://github.com/openrouterteam/docs/blob/main/guides/features/tool-calling.mdx) and [Provider routing schema](https://github.com/openrouterteam/docs/blob/main/openapi/openapi.yaml): Tool messages and mandatory parameter support.
- [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create): function definitions, arguments, and correlation IDs.
- [Anthropic tool parameter definitions](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/tool_param.py) and [official Tool runner](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/lib/tools/_beta_runner.py): inspected as schema references only; no SDK dependency is planned.
- [Gemini generateContent migration comparison](https://ai.google.dev/gemini-api/docs/migrate-to-interactions) and [generateContent thought signatures](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures): retain the current API's parts and signatures. Google's reference limits strict signature validation to the current turn, allowing normalized older turns from another Provider without fabricating signatures.

No new ADR is required: this feature implements the brief's settled Conversation/Tool decisions and extends the existing Provider Contract within ADR-0002. The orchestrator owns any glossary update to the expanded contract after implementation.
