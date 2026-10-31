# Review: 0039/02 — Persistent session selection

- Status: approved
- Ticket: `tickets/0039-session-tier-selection/02-persistent-session-selection.md`
- Reviewed range: `70d54cdd6a285d3f095e7f82d09e647bef597361..10f7b78f0abdaa24e4930ba5829b7e69df309fc8`
- Spec: approved, AC1–AC9 met.

## Evidence

- `uv run --offline --no-sync pytest -q`: 1665 passed in 80.72s; `tests/test_session_tier.py`: 57 passed.
- Grep of `src/` for classifier, start_tier, pin and budget leftovers: none beyond the evaluator instruction text.
- Verified cancellation propagates from `evaluate_tier` without fallback; AuditError and PersistenceError re-raise; local budget/prepare errors fall back to medium.
- Autouse `evaluate_tier` stub in `tests/conftest.py` does not weaken unrelated tests (stub matches prior easy heuristic; complex cases now pin explicitly).
- `/model` audits record pending as "auto"; acceptable since audits are not a replay source.
- Working tree clean after review.

## Optional suggestions (not required)

- `repl.py:150` fallback warning prints in notice cyan; legacy warning is yellow.
- `repl.py:289,306` rename `old_pin` to `old_tier`.
- `router.py:651` blocked evaluator `context_budget` audit lacks the `tier_selection` purpose marker.
- Document the `REAL_EVALUATOR = True` opt-in in a test-convention note.

## Residual risks

- No static type/lint tooling; required `tier` argument of `route()` is enforced by tests only.
- Live evaluator classification quality is untested by design.
