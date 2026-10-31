# 01: Address the cheapest still-open non-blocking review suggestions

**What to build:** across ~90 `suggestion`-severity findings logged in earlier
tickets' reviews, most are deliberately left as-is (explicitly "not
required"/"out of scope") or already fixed by later refactors. Re-verified
against current code on 2026-09-24: the three below are still genuinely open,
cheap, and worth fixing. Everything else checked (TierConfig api_key
threading, `RouteResult.messages` naming, tier/provider projection,
`log_tool_execution`'s error typing, the shell/setsid README note, the
litellm-internals docstring citation, "Compressed 1 turns." pluralization,
`format_tool_line` escaping) was confirmed already fixed or correctly
deferred - do not reopen those.

**Blocked by:** None (can start immediately).

**Spec:** none (fast path). The checklist below is normative.

- [x] `src/personal_agent/terminal/tty.py` `colorize()`: wraps the whole
  string including a trailing `\n` in the escape codes, so `RESET` lands
  after the newline instead of before it. Harmless with plain foreground
  colors today, but would bleed color into the next line if a background or
  reverse-video code is ever added. Split off a single trailing `\n` before
  wrapping, append it after `RESET`. (From ticket 0006's review.)
- [x] `src/personal_agent/terminal/repl.py` `run_repl()`: the end-of-session
  `reason` values (`"error"`, `"eof"`, `"interrupt"`, `"exit_command"`) are
  raw string literals repeated across five call sites feeding
  `call_log.end_session(reason)`. Define them once as module-level constants
  (e.g. in `call_log.py`, imported by `repl.py`) so a typo in one spot can't
  silently diverge from what `call_log.end_session` or its readers expect.
  (From ticket 0007's review.)
- [x] `src/personal_agent/terminal/repl.py` `render_usage()`: when the last
  Attempt's Provider response carried no `usage` block, `prompt_tokens`/
  `completion_tokens` are `None` and the `tokens:` line prints literally
  `"tokens: None prompt, None completion"`. Render `"unknown"` in place of a
  `None` count instead. Extend `test_render_usage_after_a_successful_turn`
  (or add a sibling test) covering the missing-usage case. (From ticket
  0017's review.)
- [x] `uv run pytest -q` passes, full suite.
