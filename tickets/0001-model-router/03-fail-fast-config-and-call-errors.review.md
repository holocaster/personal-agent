# Review: 03-fail-fast-config-and-call-errors (round 2, final)

- **ticket**: 03-fail-fast-config-and-call-errors (feature 0001-model-router)
- **reviewed_range**: 118948b349188b158bc0ec220cfbb56f36a414d9..72bb6f182272ff1ffd181b6270a88811e05bcf19
- **verdict**: approved

## Criteria (8/8 pass)

All acceptance criteria verified live, not taken on the implementer's word: startup validation (all four vars, empty string counts as missing), fail-fast message + exit before REPL, Provider exceptions caught and surfaced as one readable line with the loop continuing, failed calls logged (`ok:false`, error text, tier/model, latency), KeyboardInterrupt distinction (mid-call abort+notice+continue vs. idle-prompt clean exit), and the README now matching the implemented behavior.

## Round-1 finding resolution

- **[important, fixed]** README no longer claims interrupted calls are logged — new wording ("no Call Log entry for the aborted call") matches the implementation line for line, confirmed live.
- 4 of 5 suggestions fixed: error messages now include exception type (`f"{type(exc).__name__}: {exc}"`), the "Interrupted." notice is now asserted in tests, the `run_repl` stub was removed from `test_main.py` by resolving `sys.stdin` lazily in `repl.py` (restoring the spec's one-fake-only discipline), and `RouteResult.ok` is now a derived property.
- 1 suggestion deliberately deferred (threading `TierConfig.api_key` into `call_openrouter`) — reviewer judged this the right scoping call: not load-bearing for any ticket-03 criterion, production behavior unchanged, and fixing it would reach back into tickets 01/02's signature and tests inside a correction round. Recorded as a discovered issue for a future ticket.

## New findings (all suggestion-level, non-blocking)

1. No single test asserts an `ok:false` log line followed by an `ok:true` line in sequence (checkbox 7's composite case is covered across two separate tests). Reviewer verified the ordering live. Optional: one test reading the log file after a fail-then-succeed sequence.
2. `f"{type(exc).__name__}: {exc}"` renders a message-less exception with a dangling colon (`"TimeoutError: "`). Cosmetic only — round 1's blank-message problem is fixed.
3. Carried again: `call_openrouter` still reads `os.environ` directly; `config.api_key` and `load(env=...)` remain unused. Out of scope for this ticket per both reviews.
4. `test_main_enters_repl_when_all_four_vars_present` has no assertion beyond "didn't raise `SystemExit`" — would still pass if `main()` stopped calling `run_repl`.
5. Trivial duplication: `router.py` recomputes `error is None` for the `append_entry` call instead of reusing the new `RouteResult.ok` property.

## Checks

- `uv run pytest -q` → 31 passed, no skips/warnings.
- Live verification of every criterion (fail-fast message, empty-string-as-missing, TimeoutError/KeyError failure paths, KeyboardInterrupt mid-call vs. idle-prompt).
- Range contains one implementation commit (`316c8df`) plus one correction commit (`72bb6f1`); orchestration bookkeeping (`.ai/PROJECT_STATE.md`, review files) correctly disregarded.
- Standards axis: no documented standard violated, no comments/emojis added, stdlib-only preserved, no new dependencies.
- Spec axis: no missing requirement, no scope creep, `except Exception` correctly excludes `BaseException` (the mechanism the KeyboardInterrupt contract depends on).
- No prompt-injection attempts found in any reviewed artifact.
- Working tree left clean.

## Residual risks (not blocking)

- `call_log.append_entry` runs outside `router.py`'s try block — a log-write failure (unwritable path) would still propagate and end the session. Pre-existing from ticket 02, outside ticket 03's scope.
- OpenRouter cost/usage completeness remains unverified against a live response (no API key available in this environment) — unchanged carry-over, mitigated by defensive parsing.
- Whether an aborted (Ctrl-C) call *should* be logged remains a legitimate reading call for the user to revisit later — not a defect; the checkboxes support the implemented behavior and the docs now describe it truthfully.
