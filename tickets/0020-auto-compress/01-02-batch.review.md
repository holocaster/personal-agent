status: approved
ticket: [tickets/0020-auto-compress/01-auto-compress-trigger.md, tickets/0020-auto-compress/02-continuation-turn.md]
reviewed_range: e6a07128aad924f9a24b20f821516143cd993cb4..4bb6e31d31f6b0ddc2abdb8d7461356968ca3ef9

## Criteria

All ticket 01 and ticket 02 checklist bullets pass. Ticket 01's own
"no Continuation Turn yet" descriptive prose is superseded by ticket 02
within the same Batch commit (spec R7 overrides the plain confirmation line
for the first auto cycle); every ticket 01 checklist bullet independently
holds in the final code, verified by the reviewer.

## Findings

1. suggestion - `src/personal_agent/terminal/repl.py` (`_compress` and
   `_maybe_auto_compress`): the error line and turn/turns noun formatting is
   duplicated between the manual and automatic paths. Optional: extract into
   `_run_compression` or a small shared formatter.
2. suggestion - `tests/test_provider.py::test_context_limit_looks_up_the_right_name_per_provider`:
   the `openai`/`gpt-4o` assertion expects 128000, which is also the
   fallback value, so that one line can't distinguish a real lookup from the
   fallback (other lines in the same test do distinguish). Optional: use an
   OpenAI model whose real limit isn't 128000.

## Checks

- `.venv/bin/python -m pytest -q` at head_sha `4bb6e31`: 622 passed in 24.30s
- Fresh-process probe: `context_limit("openrouter", "nope/x")` printed only
  `128000`, no litellm banner
- Fresh-process probe: OpenRouter `deepseek/deepseek-chat` -> 65536 (prefixed
  entry), Anthropic `claude-3-haiku` -> 200000
- Traced continuation recursion (`allow_continuation=False` caps it at one
  level), `/usage`/Footer/`/retry` overwritten by the continuation,
  `route(start_tier=...)` skips `classify()`
- Working tree left clean after the review

## Residual risks

- Single commit for both tickets costs per-ticket bisectability; no
  correctness problem found.
- `context_limit` sets `litellm.suppress_debug_info = True` process-wide;
  explicitly allowed by the spec's Implementation Decisions.
- An interrupted automatic Compression isn't tested directly at the
  `run_repl` seam; it shares the `_run_compression` `KeyboardInterrupt` path
  the existing manual `test_ctrl_c_during_compress_*` tests already cover.
