# 01: Color output and a loading spinner for the REPL

**What to build:** The interactive REPL gets ANSI color accents for its
different message kinds (prompt, routing metadata, answer, error, Tool
calls/results in `/history`), and shows an animated loading spinner while
a Provider call (`route()`) is in flight, so the terminal is not silent
during a multi-second network wait. Piped/non-interactive use (tests,
`cmd | python -m model_router`) stays byte-identical to today: no ANSI
codes, no spinner.

**Blocked by:** None (can start immediately).

**Spec:** none (fast path). The checklist below is normative.

- [x] Colors and the spinner are gated on `output_stream.isatty()`
  (mirror the existing `is_tty` gate already used for the `user> `
  prompt) **and** absent when the `NO_COLOR` environment variable is
  set to any non-empty value (respect https://no-color.org, one `if`).
  When either condition disables color, output is byte-identical to the
  current plain text — this must not change any existing `test_repl.py`
  assertion, since those tests use non-tty `StringIO` streams.
- [x] Use raw ANSI SGR escape codes from the standard library only — no
  new dependency (`colorama`, `rich`, etc.). Wrap each color in a small
  local helper (e.g. a `_color(text, code)` function or a tiny
  name-to-code mapping) so codes are not repeated as magic strings.
- [x] Color assignment (exact codes are the implementer's call, keep it
  readable on both light and dark terminal backgrounds — avoid pure
  black/white foreground colors):
  - the `[tier] provider model` routing metadata line: one distinct
    accent (e.g. dim/cyan) from the answer line.
  - the `llm> ` prefix: a distinct accent (e.g. green); the answer text
    itself stays uncolored.
  - `Error: ...` lines (routed errors and local command errors): red.
  - `/history` output: `tool_call:` and `tool_result:` lines get a
    distinct accent (e.g. yellow) from plain `user:`/`assistant:`
    lines; an `[error]` tool result stays red or a visibly distinct
    shade from an `[ok]` one.
  - `user> ` prompt: may stay uncolored or get a subtle accent — not
    load-bearing, implementer's call.
- [x] While `route()` is running for a non-command task, and only when
  `output_stream.isatty()` (never in piped/test mode), show an animated
  spinner (e.g. rotating braille frames) on the current line, updated in
  place (`\r`, no newline spam), until `route()` returns. The spinner
  must not appear in captured output for any existing or new
  non-interactive test.
- [x] The spinner runs in a background thread so the main thread can
  block on the synchronous `route()` call; use only `threading`/`time`
  from the standard library. On `route()` returning (success, routed
  error, or `KeyboardInterrupt`), stop the thread, join it, and clear
  the spinner line before writing the routing metadata / error /
  interruption message, so nothing overwrites or trails stale spinner
  characters.
- [x] Separate the spinner's pure frame-cycling logic (which frame comes
  next) from its threaded timing loop, so the frame sequence itself is
  unit-testable without real sleeps or a real thread.
- [x] `uv run pytest` passes unchanged — no existing assertion in
  `tests/test_repl.py` needs updating because of this ticket (non-tty
  output is unaffected). Add focused new tests: color codes present in
  `/history`, the routing line, `llm>`, and an `Error:` line when
  `output_stream.isatty()` is monkeypatched/faked to `True` (and absent
  when `False`, and absent when `NO_COLOR` is set even if `isatty()` is
  `True`); the spinner's frame-cycling function produces a stable,
  deterministic sequence.
- [x] Concise README note: colors and the spinner are automatic on an
  interactive terminal, off when piped or when `NO_COLOR` is set.

**Implementation guidance:** Keep this inside `model_router/repl.py` (plus
a small new module if that reads cleaner, e.g. `model_router/tty.py` for
the color/spinner helpers) — do not introduce a CLI/output framework or a
themeing system. This is cosmetic terminal output only; it must not change
`route()`'s signature, the Router, or any Provider.

**Validation:** `uv run pytest`. Also run the REPL interactively
(`uv run python -m model_router`) once and confirm colors render and the
spinner animates and clears cleanly, since a live terminal's animation
can't be fully proven by an automated test.
