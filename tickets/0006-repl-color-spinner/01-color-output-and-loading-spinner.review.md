# Review: ticket 0006-repl-color-spinner/01

status: approved
reviewed_range: 9d533779c4e3f26f3be901040eacab20694660db..fd4fb9d87c79b9460d63347315ba89f97a71e0eb

All 8 acceptance criteria pass. Reviewer verified independently, not on
report alone:

- Byte-identical non-tty output: same scripted REPL session run against
  base and head with `StringIO`, `diff` reports the captures identical.
- Live pty verification (`os.openpty()`, patched `route()` with a
  0.5s sleep): frames update in place with `\r` only; `\r\x1b[K` clears
  the line before the message on all three paths (success, routed
  error, `KeyboardInterrupt`). No stale characters, no newline spam.
- Thread-lifecycle audit (instrumented `Spinner._run` to register every
  spawned thread) across three paths — routed error, `KeyboardInterrupt`,
  and an uncaught `RuntimeError` from `route()` — each started exactly 1
  thread and left 0 alive; the `finally` covers the started thread on
  every path, including the uncaught-exception one.
- ANSI-leak audit by direct inspection of all three escape-emitting
  sites (`colorize()`, `Spinner._run`, `Spinner.stop()`): no escape byte
  can reach a non-tty `output_stream` on any path.
- No dependency added; `tty.py` imports only `os` and `threading`.
  Uses `Event.wait(interval)` instead of `time.sleep` — stops
  immediately on `stop()` rather than after up to a full frame
  interval, better than the ticket's own suggestion.

## Findings (both suggestions, non-blocking)

- `repl.py:73,78,82`: `colorize()` is called on strings ending in `\n`,
  so the SGR reset lands after the line terminator rather than before
  it. Harmless today (only foreground codes used); would bleed color
  across the line break if a background/reverse-video code is ever
  added. Optional: colorize the text and append the newline outside the
  escape.
- The red `[error]` tool_result branch in `_render_message` has no
  automated coverage (verified correct manually by the reviewer);
  only the yellow `[ok]` case is asserted in the new history-color
  test. Optional: add an `is_error=True` case to that test's fixture.

## Residual risks (informational)

- Braille spinner glyphs could raise `UnicodeEncodeError` on a stream
  whose encoding can't represent them (e.g. cp1252); the thread would
  die silently and the main thread still joins/clears, so the outcome
  is a missing spinner, not a hang. Not a concern on this
  Linux-targeted project.
- A second Ctrl-C landing while the main thread is inside
  `spinner.stop()`'s `join()` would leave the spinner line uncleared —
  inherent to any join-then-clear sequence, matches the REPL's
  pre-existing single-Ctrl-C behavior, not a regression.
- `color_enabled()` is evaluated once at REPL start; a `NO_COLOR`
  change mid-session has no effect — conventional behavior, matches the
  ticket's "one `if`" instruction.
