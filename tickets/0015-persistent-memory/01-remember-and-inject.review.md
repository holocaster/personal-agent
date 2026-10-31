status: approved
ticket: 0015-persistent-memory/01-remember-and-inject
reviewed_range: 5de2a19bd492025a243852a9ce7ac59aaccdf9a8..bc46242
note: important finding below fixed post-review (no round-2 doc); verified 2026-09-24 - memory.py load() now catches UnicodeDecodeError and raises the malformed-file ValueError naming the path.

## Findings

### important - memory.py load() / __main__.py: configuration error does not name the file on invalid UTF-8

Location: `src/personal_agent/memory.py` `load()` (open/iterate block); `src/personal_agent/__main__.py` lines 44-48.

If the Memory file has invalid UTF-8 on a line (e.g. saved as Latin-1), the
line is not valid JSON either, so it counts as malformed under the ticket's
acceptance criteria. `main` does print "Configuration error: ..." and exit 1,
but the message does not name the file, because `UnicodeDecodeError` (a
`ValueError` subclass) is caught and its own text - which contains no path -
is printed. Ticket criterion and spec user story 32 both require the error to
name the file. No test covers a non-UTF-8 file.

Evidence: `memory.load()` on a file containing `\xff\xfe\n` raised
`UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0:
invalid start byte`.

Required change: when decoding fails in `load()`, raise the same
`"memory file <path> is malformed"` `ValueError` (e.g. catch
`UnicodeDecodeError` around the read and chain it). Add a bad-bytes case to
the malformed-file test.

### suggestion - memory.py load(): unreadable file crashes with raw traceback (not required)

An unreadable Memory file (`PermissionError`, or another `OSError` on read)
is not caught by `main`, so startup dies with a raw traceback instead of a
configuration error. Not covered by the spec; does not affect the verdict.
Optional: convert an `OSError` on read into the same file-naming
configuration error.

### suggestion - repl.py _LINE_BREAK_RUN: also trims adjacent spaces/tabs, lone \r not treated as break (not required)

Reasonable reading of "collapse line breaks", already asserted by a test.
No change required; documenting the choice is optional.

### suggestion - memory.py remember(): partial write on disk-full leaves truncated last line (not required)

Would surface loudly as a malformed-file error on next startup rather than
silently. Spec only asks for atomic writes on `/forget`. No change required
for this ticket.

## Checks

- `uv run pytest -q` at HEAD `0497f4c` (differs from `bc46242` only in
  `.ai/PROJECT_STATE.md`): 471 passed in 9.87s.
- Probe: `memory.load()` on invalid UTF-8 raised `UnicodeDecodeError` with no
  path in the message; on a `chmod 000` file it raised an uncaught
  `PermissionError`.
- Standards: follows `CLAUDE.md` (no emojis, minimal comments). Memory module
  is a leaf at the package root per `docs/CONTEXT.md`. `"Configuration
  error:"` prefix matches the existing workspace error in `main`. No scope
  creep: `/memory` and `/forget` correctly absent (ticket 02), `log_version`
  unchanged, Tool Registry untouched.

## Residual risks (informational, no action required)

- The malformed-memory test in `test_main` calls `main()` without an
  explicit `argv`; works under pytest but depends on `sys.argv`.
- Escalation test relies on 3x503 exhausting local retries before the 4th
  call goes to the next tier; not independently re-verified against
  `MAX_ATTEMPTS`, but the test asserts Memory on every captured call either
  way.
