# 02: Bracket each Session with `session_start` and `session_end`

**What to build:** A Session's file now opens with a `session_start` line naming the tier to provider/model configuration that was in force, and closes with a `session_end` line saying why the Session ended and what it spent. A user can tell a completed Session from one whose process was killed mid-write, tell quitting on purpose from an EOF, an idle Ctrl-C or a crash, and read the Session's total spend without summing lines by hand — with or without a Budget Guardrail configured.

**Blocked by:** 01 (one Call Log file per Session) — the Session start/end hooks and the resolved per-Session path come from there.

**Spec:** `docs/specs/0007-session-call-log.md` (R04, R05, R08, R09, R11, R12); **ADRs:** `docs/adrs/0003-call-log-per-session.md`.

- [x] A `session_start` line is written exactly once, as the file's first line, carrying the envelope (`timestamp`, `session_id`, `type`) plus the resolved Tier Config in force as a tier-keyed mapping of provider and model for all three Complexity Tiers. It carries no API key, no environment dump, and no other secret — asserted against an environment that has key values set.
- [x] A `session_end` line is written exactly once, as the file's last line, carrying the envelope plus `reason` and `total_cost`.
- [x] `reason` is one of `exit_command` (bare `exit`/`quit` or `/exit`), `eof` (input stream exhausted), `interrupt` (Ctrl-C at an idle prompt), `error` (the Session ended through an unhandled exception). Each of those four paths is driven through `run_repl` and asserted.
- [x] `session_end` is written from a `finally` in `run_repl`, with the reason initialized to `error` and set to its specific value at each known exit path before leaving the loop. No exception is swallowed — an input stream that raises an unexpected exception still propagates it after the line is written — and the REPL's existing exit handling is not restructured to chase additional reason values.
- [x] `total_cost` is the sum of the non-`null` `cost` values this Session recorded on its `attempt` lines, `0.0` when there were none. It is computed by `call_log` from what it logged, never read from the Budget Guardrail, and is reported correctly with `ROUTER_BUDGET_USD` unset. It includes retried and escalated Attempts, and mixes real and Estimated Cost without distinguishing them (`docs/CONTEXT.md`, Estimated Cost).
- [x] Both new line types follow the common envelope rule: all lines of one type share exactly one key set, including keys whose value is `null`.
- [x] A Session that only ran local commands produces a file containing exactly a `session_start` and a `session_end` line and zero `attempt` lines. `tests/test_repl.py`'s `assert not log_path.exists()` style assertions are replaced by that stronger form — "commands are free" is still proven, just not by the file's absence.
- [x] `/clear` does not start a new Session, rotate the file, or reset spending: Attempts after a `/clear` land in the same file with the same `session_id`, and `total_cost` still includes what was spent before it.
- [x] Ctrl-C during a request keeps its current behavior — the printed notice and a return to the prompt — and does not end the Session or write a `session_end` line.
- [x] The README's Call Log section documents the `session_start` and `session_end` lines, the four `reason` values, and what `total_cost` does and does not include.
