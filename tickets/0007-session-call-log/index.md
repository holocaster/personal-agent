# Tickets: 0007-session-call-log

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | One Call Log file per Session | none | done |
| 02 | Bracket each Session with `session_start` and `session_end` | 01 | done |
| 03 | Record answers, requested Tool calls, and Tool executions | 01 | done |

Spec: `docs/specs/0007-session-call-log.md`
Brief: `docs/briefs/0007-session-call-log.md`
ADRs: `docs/adrs/0003-call-log-per-session.md` (this feature), `docs/adrs/0001-escalate-on-technical-failure-only.md`, `docs/adrs/0002-hand-rolled-provider-contract.md`.

## Coverage

| Spec requirement | Tickets |
|---|---|
| R01 | 01 |
| R02 | 01 |
| R03 | 01 |
| R04 | 01, 02, 03 |
| R05 | 02 |
| R06 | 01, 03 |
| R07 | 03 |
| R08 | 02 |
| R09 | 02 |
| R10 | 03 |
| R11 | 01, 02, 03 |
| R12 | 01, 02, 03 |

R04 (the common envelope) and R12 (README, `.gitignore`, no new dependency) are established in 01 and extended by each ticket that adds a line type. R06 splits: 01 keeps the existing Attempt fields and adds the envelope; 03 adds `answer` and `tool_calls`. R11 (unchanged routing behavior) is a standing constraint each ticket re-proves.

## Shape

Ticket 01 is the load-bearing one. The `ROUTER_LOG_PATH` semantic change fans out across `tests/conftest.py`, `tests/test_call_log.py`, `tests/test_repl.py` and `tests/test_routing.py`, so the migration is folded into 01 rather than given its own ticket: unlike ticket 03 of feature 0005 — which fixed a pre-existing test-isolation defect and could therefore stand alone — this migration exists only because the path scheme changes, so it cannot precede it and cannot land green without it. The blast radius is four test files behind one helper, not thousands of call sites, so expand–contract is not warranted; one ticket keeps the suite green in a single step.

Ticket 02 (REPL brackets the Session) and ticket 03 (Router records answers and Tool executions) both sit on 01 and are independent of each other: 02 touches the REPL's exit paths and the Session lifecycle, 03 touches the Router's exchange and Tool loop. Neither gates the other, so the frontier after 01 is both, in either order. They are kept apart from 01 and from each other because each is separately demoable — "my Session file says why it ended and what it cost" versus "my Session file shows what the model answered and what the Tools returned" — and folding all three into one ticket would put a repo-wide test migration, a REPL control-flow change and the Tool-loop wiring in a single context.

No pre-existing fast-path ticket exists for this feature. Status lives only in this index.
