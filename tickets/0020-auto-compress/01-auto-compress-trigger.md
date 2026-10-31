# 01: Auto-Compress a turn that nears the Context Limit

**What to build:** After every successful routed turn, the REPL looks up the
answering model's Context Limit and, when the turn's `prompt_tokens` exceeds
80% of it, runs the same Compression `/compress` runs - automatically, with no
command from the user. No Continuation Turn yet: after an automatic
Compression the REPL prints the manual confirmation line and returns to the
prompt.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0020-auto-compress.md` (Requirements R1-R5, R9;
Implementation Decisions: `cost` module, Lookup name per Provider, REPL;
Testing Decisions); **ADRs:** ADR-0002 (Amendment, feature 0020), ADR-0005.

- [x] The `cost` module has a Context Limit lookup taking a Provider name and
  model: `litellm.get_model_info(<lookup name>).get("max_input_tokens")` in
  `try`/`except Exception`, with a fixed 128000 fallback for a missing,
  non-positive or non-integer value, an unrecognised model, or any exception.
  Lookup name: `openrouter/<model>` for `openrouter`, the Gemini adapter's
  existing pricing prefix + model for `gemini`, the bare model for
  `anthropic` and `openai`.
- [x] The lookup prints nothing to stdout or stderr, including for an
  unrecognised model (where `litellm` otherwise prints a "Provider List"
  banner to stdout).
- [x] Right after a successful turn is appended to the Conversation, the REPL
  fires Auto-Compress when `prompt_tokens` is not `None` and
  `prompt_tokens > 0.8 * limit`. `prompt_tokens is None`, a turn at or under
  the threshold, and failed or interrupted turns never fire.
- [x] A fire with two or fewer turns does nothing: no Provider call, no
  output, no error.
- [x] Otherwise the existing Compression runs unchanged (easy tier, two most
  recent turns kept, `conversation_compressed` entry written after the
  crossing turn's Turn End, summary in later System Prompts, `Compressed N
  turn(s).` confirmation). Manual `/compress` and the automatic path share
  one helper; manual `/compress` behavior and output are unchanged, including
  its "nothing to compress" error.
- [x] A failed, empty or interrupted automatic Compression prints the same
  `Error: ...` line manual `/compress` prints and leaves the Conversation,
  summary and Call Log (no `conversation_compressed`) unchanged.
- [x] A turn started by `/retry` is checked the same way as a typed task.
- [x] Auto-Compress is always on (no env var, no command). The README's
  Compression / Context Window section documents the automatic trigger, the
  80% threshold and the 128k fallback.
- [x] Tests: the lookup directly against the real local `litellm` map (known
  bare, OpenRouter-prefixed, Gemini-prefixed, unknown -> 128000 with nothing
  printed, exception -> 128000); and at the `run_repl` seam with the fake
  Provider (fires above threshold, not at/below, not on `None` usage, silent
  skip with two turns, failure shows error and changes nothing, Resume of a
  Run that auto-compressed rebuilds the same Conversation). Full offline
  suite passes.
