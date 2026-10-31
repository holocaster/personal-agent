# Review: ticket 0007-session-call-log/01

status: approved
reviewed_range: 5877585f149f1c7fd535f605d133c2577b7fe266..d24ec7a17ac2b0736f4045570eb65f4cae921e54

All 10 acceptance criteria pass. Standards axis: 3 non-blocking
suggestions, worst is a judgement-call duplicated-code smell — no hard
violation. Spec axis: 0 findings, no scope creep into ticket 02/03
territory (`session_start`/`session_end`/`tool_execution` correctly
absent).

Verified independently: Session Id shape/ordering by direct inspection
(not just trusting tests), `ROUTER_LOG_PATH` path resolution against
R02 for all four cases (default, extensionless, dot-containing parent
dir, bare relative), production-code scope containment (`git diff` on
`router.py`/`classifier.py`/`budget.py`/`tools.py`/`tier_config.py` is
empty — only `call_log.py` and one line in `repl.py` changed), a sweep
for surviving exact-path assumptions in the test suite (none found
outside the three naming-scheme tests the spec explicitly permits),
`.gitignore` coverage, and repo hygiene after a full test run (no stray
`logs/` or `router_log.jsonl` in the repo root).

## Findings (all suggestions, non-blocking)

- `tests/test_call_log.py` (10 sites): redundant `monkeypatch.setenv`
  calls that re-set `ROUTER_LOG_PATH` to the exact value the autouse
  `_isolate_router_log` fixture already set — no-ops, propagated from
  a cleanup ticket 0001's review already flagged rather than resolved.
  Optional: drop them except where a test needs a genuinely different
  base path.
- `model_router/call_log.py:41-48` (`session_log_path`): calling it
  with no argument lazily mints a Session Id (spec-mandated, R03), but
  its docstring doesn't say so — a future caller using it to "just
  compute a path" could be surprised. Optional: mention the lazy mint.
- `tests/test_call_log.py:275-293`: the Session Id ordering test adds
  1.1s of real wall time and has a redundant trailing
  `reset_session()` call (the autouse fixture already resets per
  test). Justified and honest about what it buys — cosmetic only.

## Residual risks (informational, not blocking)

- Session Id ordering is second-resolution: ids minted within the same
  second sort by their random suffix, not mint order. Not a defect —
  spec R01 only requires lexicographic order to equal the *timestamp
  component's* chronological order, and the collision-avoidance job
  belongs to the suffix, not ordering. The ticket's shorter restatement
  overclaims slightly relative to the spec it cites; flagged so the
  boundary is known, not because anything needs fixing now.
- `call_log` holds module-level mutable Session state (three `global`
  statements) — the spec's explicit, reasoned trade-off given
  `route()`'s signature is out of scope for this feature. A later
  feature that opens that signature should revisit it.
- `ROUTER_LOG_PATH` is re-read from the environment on every append,
  not captured at `start_session()`; changing it mid-Session would
  split one Session's lines across two files. Matches pre-existing
  `_log_path()` behavior, not a regression, no test or use case
  exercises it.
