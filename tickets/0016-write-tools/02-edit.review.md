# Review: 02-edit

status: approved
ticket: 0016-write-tools/02-edit
reviewed_range: 60b2f6218d3235b6da5d02f3e1bafd76fec361bb..157ed3e1af7457b6b7a599aa8e26966760011a29
review_round: 1

## Criteria

All 9 criteria pass: file-target validation reuse, bounded read with binary/oversized errors, exact case-sensitive match semantics (0 matches error, >1 without replace_all error naming the count, new_string==old_string error), ROUTER_MAX_WRITE_BYTES check on result, schema/registration, Tool Confirmation reuse (diff preview, approve/reject/no-callback), Call Log entry + tool> line for applied/rejected/failed, README, and full offline suite (552 passed).

Reuse claim verified against the actual diff: only README.md, registry.py (one import + one new `_ToolEntry`), workspace.py (`prepare_edit` added, nothing existing changed), and two test files changed. `execute_batch`/`_execute_mutating`, `PreparedChange`, `apply_change`, and `terminal/repl.py` are untouched.

Exact-match semantics confirmed: `prepare_edit` uses only `str.count`/`str.replace`, no normalization/casefolding/similarity logic - matches the CONTEXT.md decision to not replicate opencode's fuzzy matcher.

## Findings
- suggestion (optional, not required): `test_repl_writes_the_call_log_entry_and_live_tool_line_for_an_applied_rejected_and_failed_edit` only asserts the live `tool>` line for the applied case, not rejected/failed. No real gap today (shared printer path), but a future edit-specific regression in the error lines wouldn't be caught. Left as-is.

## Checks
- `uv run pytest -q`: 552 passed in 8.45s.
- Ad-hoc probes (CRLF preservation, replace_all count, empty old_string rejected by schema, invalid UTF-8 new_string) all behaved correctly.
- Standards: no violations; minor duplication (prepare_edit repeats prepare_write's encode/size-limit block, ~5 lines) not worth a helper.

## Residual risks
- Order of checks (new_string==old_string before match-count) means an identical-string edit against a missing old_string reports "identical" rather than "not found" - both are pre-confirm errors, acceptable.
