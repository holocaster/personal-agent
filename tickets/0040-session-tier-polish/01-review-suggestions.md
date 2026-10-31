# 01: Apply 0039/02 review suggestions

**What to build:** Polish left over from the 0039/02 review (`tickets/0039-session-tier-selection/02-persistent-session-selection.review.md`): a failed tier evaluation reads as a warning, Tier Pin naming is gone, a locally blocked evaluator exchange is identifiable in the Call Log, and the evaluator test opt-in is discoverable.

**Blocked by:** None (can start immediately).

**Spec:** none (fast path).

- [x] When tier evaluation falls back to medium, the REPL prints the fallback warning in the same warning color (yellow) as the legacy-Resume warning, in both interactive and piped output. The successful-selection announcement and its `/model` guidance keep their current notice styling. Existing output assertions stay intact except where they check that color.
- [x] The `/model` handler in `src/personal_agent/terminal/repl.py` no longer uses the Tier Pin name `old_pin`; rename it to `old_tier`. Behavior and audit fields stay the same.
- [x] When the evaluator's input is blocked locally by the context budget, the resulting `context_budget` audit event in the Call Log carries `purpose: "tier_selection"`, as evaluator Attempts and detail records already do. Ordinary exchanges' `context_budget` events stay without a purpose field.
- [x] `.notebook/routing-and-repl.md` notes, in one sentence, that `tests/conftest.py` stubs `evaluate_tier` to easy for every module unless the module sets `REAL_EVALUATOR = True`.
- [x] Tests cover the warning color and the blocked-evaluator audit purpose through existing REPL/Call Log seams. `uv run --offline --no-sync pytest -q` passes; record counts. No new dependencies, no live calls, do not edit `pyproject.toml`.
