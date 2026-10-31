status: approved
ticket: 0019-review-polish/01
reviewed_range: 72acb3e23b6d8f32fe10aaae20250fcb8bd14bff..8e2ab5b2f43530cc6a98c7127bcd334942d3c0df

## Criteria

All 4 checklist items pass, verified directly against the diff.

1. `tty.py` `colorize()` now splits off a single trailing `\n` before wrapping in ANSI codes and appends it after `RESET`. New test `test_colorize_puts_reset_before_a_trailing_newline` confirms the ordering; existing `repl.py` color tests updated to match, no caller regresses.
2. `call_log.py` defines `SESSION_END_ERROR`/`EOF`/`INTERRUPT`/`EXIT_COMMAND`; all five `repl.py` assignment sites use them. No raw session-end-reason literal remains.
3. `render_usage()` renders `"unknown"` instead of `None` for missing token counts, with a new covering test.
4. `uv run pytest -q`: 608 passed (re-run by reviewer).

## Findings

None.

## Checks

- `uv run pytest -q`: 608 passed in 23.06s (run by reviewer)
- `git diff 72acb3e..8e2ab5b -- src/personal_agent tests`: reviewed in full
- grep for residual raw session-end-reason string literals in `src/`: none found
- No scope creep: diff touches only the three named items plus their tests

## Residual risks

None.
