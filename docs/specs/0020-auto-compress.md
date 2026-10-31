# 0020 - Auto-Compress

Brief: `docs/briefs/0020-auto-compress.md`. Extends `docs/specs/0014-turn-controls.md`
(Compression, `/compress`). ADRs: ADR-0002 (Amendment, feature 0020: Context
Limit lookup), ADR-0005 (the Call Log is the Conversation's durable record).
Vocabulary (Auto-Compress, Context Limit, Continuation Turn, Compression,
Conversation Summary, Tier Pin) is in `docs/CONTEXT.md`.

## Problem Statement

A long Conversation grows until a request exceeds the answering model's
Context Limit and the Provider rejects it. The only protection today is manual
`/compress`, which the user has to remember to run before that happens, with
no signal of how close the Conversation is to the limit.

## Solution

After every successful routed turn, the REPL compares that turn's
`prompt_tokens` with 80% of the answering model's Context Limit. When the turn
crosses it, the REPL runs the same Compression `/compress` runs, prints one
notice line, and sends one Continuation Turn - a short synthetic message
asking the model to continue or ask if anything is unclear - at the tier that
answered the crossing turn (a Tier Pin still wins). At most one
Auto-Compress-and-continue cycle runs per user-typed task. It is always on.

## User Stories

1. As a REPL user, I want the Conversation compressed automatically when it nears the model's Context Limit, so that I do not hit a Provider error for an oversized request.
2. As a REPL user, I want the trigger based on the real token count of the last request, so that it fires when the Conversation is actually large, not after an arbitrary number of turns.
3. As a REPL user, I want the limit taken from the model that actually answered, so that a large-context model is not compressed too early and a small one not too late.
4. As a REPL user using OpenRouter or Gemini, I want the limit looked up under the name `litellm` knows that model by, so that my Provider's real limit is used rather than the fallback.
5. As a REPL user, I want a fixed 128k fallback for a model `litellm` does not recognise, so that I stay protected even with an unknown model.
6. As a REPL user, I want the lookup to never print anything, so that `litellm` diagnostics do not leak into my REPL output after every turn.
7. As a REPL user, I want the trigger at 80% of the limit, so that there is room for the next request to fit.
8. As a REPL user, I want a turn with no reported usage to never trigger Auto-Compress, so that missing data never causes a surprise Compression.
9. As a REPL user, I want no error when the threshold is crossed but there are too few turns to compress, so that a single huge turn does not produce noise I cannot act on.
10. As a REPL user, I want Auto-Compress to use exactly the same Compression as `/compress` (easy tier, two most recent turns kept), so that its behavior and cost are what I already know.
11. As a Call Log reader, I want an automatic Compression recorded as the same `conversation_compressed` entry, so that Resume rebuilds the Conversation the same way.
12. As a REPL user, I want the summary Attempt of an automatic Compression logged and counted toward spend and the Budget Guardrail, so that nothing I pay for is hidden.
13. As a REPL user, I want a failed or interrupted automatic Compression to show the same error `/compress` shows and leave the Conversation unchanged, so that I know it did not happen.
14. As a REPL user, I want no Continuation Turn after a failed automatic Compression, so that nothing runs on a Conversation that was not compressed.
15. As a REPL user, I want one Continuation Turn after a successful automatic Compression, so that the model picks the work back up without me retyping anything.
16. As a REPL user, I want the Continuation Turn to be a synthetic message, not a re-send of my task, so that a task already answered is not answered twice.
17. As a REPL user, I want the Continuation Turn to start at the tier that answered the crossing turn, so that the short synthetic text is not misrouted to the easy tier.
18. As a REPL user, I want my Tier Pin to still decide the Continuation Turn's starting tier, so that a pin is always honored.
19. As a REPL user, I want Escalation and the Budget Guardrail to apply to the Continuation Turn as to any turn, so that it gets no special treatment.
20. As a REPL user, I want a one-line notice before the Continuation Turn's output, so that an answer I did not ask for does not look like a bug.
21. As a REPL user, I want the notice to say how many turns were compressed, so that I know what happened to my Conversation.
22. As a REPL user, I want the Continuation Turn in `/history`, so that the Conversation shows what the model saw.
23. As a REPL user, I want to `/undo` the Continuation Turn, so that I can drop it like any other turn.
24. As a Call Log reader, I want the Continuation Turn logged like any other turn, so that the log stays the full record.
25. As a REPL user, I want at most one Auto-Compress-and-continue cycle per task I type, so that a model answering near the limit cannot loop.
26. As a REPL user, I want a Continuation Turn that crosses the threshold again to still be compressed, but without another continuation, so that I stay protected and get control back.
27. As a REPL user, I want Auto-Compress to also protect a turn started by `/retry`, so that re-sending a task is no different from typing it.
28. As a REPL user, I want Auto-Compress on by default with no setting, so that I get protection without configuring anything.
29. As a REPL user, I want `/usage` and the Status Footer to reflect the Continuation Turn when one ran, so that they show the last answer I actually saw.
30. As a REPL user, I want manual `/compress` unchanged, so that existing habits keep working.

## Requirements

- **R1 Context Limit lookup.** A new function in the `cost` module returns the
  Context Limit for a Provider name and model: `litellm.get_model_info(<lookup
  name>).get("max_input_tokens")` inside `try`/`except Exception`; a missing,
  non-positive or non-integer value, an unrecognised model, or any exception
  returns the fixed fallback `128_000`. The lookup name is the model id as the
  Provider knows it with the same kind of prefix `litellm` needs for that
  Provider: `openrouter/` for the `openrouter` Provider, `gemini/` for the
  `gemini` Provider (reuse the Gemini adapter's existing pricing prefix),
  the bare model id for `anthropic` and `openai`. The lookup never writes to
  stdout or stderr (`litellm` prints a "Provider List" banner to stdout on an
  unknown model unless silenced).
- **R2 Trigger.** Right after a routed turn succeeds and is appended to the
  Conversation, Auto-Compress fires when the turn's `prompt_tokens` is not
  `None` and `prompt_tokens > 0.8 * context_limit(result.provider,
  result.model)`. `prompt_tokens is None` never fires. Failed or interrupted
  turns are never checked.
- **R3 Too few turns.** A firing trigger with `len(turns) <= KEPT_TURNS` does
  nothing: no Provider call, no output, no error.
- **R4 Compression reuse.** Otherwise the REPL runs the existing Compression
  path unchanged (same `compress()` call, easy tier, `KEPT_TURNS = 2`, same
  spinner, same `conversation_compressed` Call Log entry, same summary
  handling). Manual `/compress` and the automatic path share one helper; the
  manual "nothing to compress" error stays manual-only.
- **R5 Compression failure.** A failed, empty or interrupted automatic
  Compression prints the same `Error: ...` line manual `/compress` prints,
  leaves the Conversation and summary unchanged, writes no
  `conversation_compressed` entry, and sends no Continuation Turn.
- **R6 Continuation Turn.** After a successful automatic Compression (and only
  if the cap in R8 allows), the REPL sends the fixed synthetic task
  `CONTINUATION_TASK` through the normal turn path. Text:
  `"Continue with the task if there are next steps. If anything is unclear, ask me instead of guessing."`
  Its start tier is the Tier Pin if set, else the tier that answered the
  crossing turn (`result.tier`); it is not classified. Otherwise it is a
  normal turn: spinner, Tool output, Escalation, Budget Guardrail, Call Log
  Attempts and Turn End, tier line and `llm>` answer, appended to the
  Conversation, shown by `/history`, removable by `/undo`, and it becomes the
  most recent routed task for `/retry` and the last answer for `/usage` and
  the Status Footer.
- **R7 Notice.** When a Continuation Turn follows, the Compression's
  confirmation line is `Compressed N turn(s); continuing automatically.`
  (singular/plural as manual `/compress`) instead of `Compressed N turn(s).`,
  printed once before the Continuation Turn's own output. When an automatic
  Compression is not followed by a Continuation Turn (cap reached), it prints
  the manual confirmation `Compressed N turn(s).`
- **R8 Cap.** At most one Auto-Compress-and-continue cycle per user-initiated
  turn (a typed task or `/retry`). If the Continuation Turn itself crosses the
  threshold, R2-R5 still apply (it is compressed), but no further
  Continuation Turn is sent and control returns to the prompt.
- **R9 Always on, docs.** No environment variable or command toggles
  Auto-Compress. The README's Compression/Context Window section documents
  Auto-Compress, the 80%/128k constants, the notice, and the Continuation
  Turn.

## Implementation Decisions

- **`cost` module** gains the Context Limit lookup (R1) next to `estimate()`,
  with module constants for the 128k fallback. It stays a read-only metadata
  lookup (ADR-0002 Amendment). Silencing `litellm`'s banner is done inside the
  lookup (for example `litellm.suppress_debug_info = True` before the call, or
  redirecting stdout for the call's duration); either is acceptable as long as
  nothing is printed.
- **Lookup name per Provider** (R1) was decided during planning by probing the
  project's `.venv` `litellm` with its local cost map: `anthropic/claude-3.5-sonnet`
  and `meta-llama/llama-3.1-8b-instruct` are unknown bare but known under
  `openrouter/` (200000, 131072), and `openrouter/deepseek/deepseek-chat`
  (65536) differs from `deepseek/deepseek-chat` (131072) - the prefixed entry
  is the limit OpenRouter actually serves. The Gemini adapter already prefixes
  `gemini/` for pricing for the same reason. This is a lookup-name mapping,
  not new configuration.
- **REPL (`terminal/repl.py`)**: `_execute_task` gains an optional start-tier
  override and a flag saying whether a Continuation Turn may follow. After a
  successful turn it runs the threshold check; on a fire it calls a shared
  Compression helper (extracted from `_compress`, which keeps its "nothing to
  compress" check and output) that returns the compressed count or failure;
  on success and when allowed, it prints the notice and calls `_execute_task`
  again with `CONTINUATION_TASK`, the start tier from R6, and continuation
  disallowed. The typed-task path and `/retry` call `_execute_task` with
  continuation allowed. New constants in the REPL module:
  `AUTO_COMPRESS_THRESHOLD = 0.8`, `CONTINUATION_TASK`.
- **Router** is unchanged: `route(..., start_tier=...)` already skips the
  Classifier, and `RouteResult` already carries `tier`, `provider`, `model`,
  and `prompt_tokens` (the last Attempt's, i.e. the full resent history plus
  any Tool follow-up content).
- **Call Log**: no schema change, no new entry type, `log_version` unchanged.
  The automatic `conversation_compressed` entry is written after the crossing
  turn's Turn End and before the Continuation Turn's Attempts, so Resume
  replays it in the right order with no change.

## Testing Decisions

- Good tests assert external behavior only: REPL output text, the fake
  Provider request bodies (which task, which tier's model, which System
  Prompt summary), Call Log lines, and `/history` output - not internal
  helper calls.
- **Seam 1 - `run_repl`** (existing, highest seam), with the existing fake
  Provider (`install_fake_urlopen`, `tests/fakes.py`) returning scripted usage
  so `prompt_tokens` crosses or stays under the threshold. The Context Limit
  is controlled in these tests by using a tier model the local `litellm` map
  knows (deterministic via `conftest.py`'s local cost map) or by
  monkeypatching the `cost` module's lookup - either keeps the suite offline.
  Prior art: the `test_compress_*` tests in `tests/test_repl.py` (Compression
  output, failure, Call Log entry) and the Resume tests that do a real first
  Run.
- **Seam 2 - the `cost` lookup function** directly, against the real local
  `litellm` map: known bare model, known OpenRouter-prefixed model, Gemini
  prefix, unknown model returns 128000 and prints nothing (`capsys`), an
  exception from `get_model_info` returns 128000. Prior art:
  `test_estimate_uses_real_litellm_pricing_and_tolerates_unknown_models` in
  `tests/test_provider.py`.
- The full offline suite must pass.

## Out of Scope

As the brief: configurable threshold or per-tier limit override; turn-count
triggering; a cumulative token counter; a Call Log entry type distinguishing
automatic from manual Compression; Auto-Compress on Resume before the first
new task; any opt-out. Also out of scope: changing manual `/compress`
behavior or output, and changing the Classifier.

## Further Notes

- `/retry` right after a Continuation Turn re-sends `CONTINUATION_TASK`
  (it is the most recent routed task) and, with no Tier Pin, classifies it
  like any retried task. This follows directly from "a normal turn in every
  other respect" and needs no special case.
- For a model `litellm` does not know whose real limit is below 128k, the
  threshold is above the real limit and the Provider may reject a request
  before Auto-Compress fires; the brief accepted this risk (settled decision 3).
