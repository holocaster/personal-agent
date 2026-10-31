# 0007 - Session-scoped Call Log

## Goal

Give the Call Log a Session identity: each Session (one `run_repl`
process) gets its own Session Id and its own JSONL file, instead of
every Session appending to one shared, unbounded `router_log.jsonl`.
Each Session's file becomes a complete, self-contained record of that
Session's flow: every Provider Attempt (now including the assistant's
answer text and any Tool calls it requested), every locally-executed
Tool call and its result (not logged at all today), and explicit
`session_start`/`session_end` entries bracketing the file.

## Scope

- New `Session` / `Session Id` concept (see `docs/CONTEXT.md`): the
  Session Id is generated once at `run_repl` start — a sortable UTC
  timestamp plus a short random suffix, so a directory listing already
  shows Session order.
- One Call Log JSONL file per Session, named after its Session Id,
  under a new `logs/` directory (gitignored). The default path pattern
  derives from the existing `ROUTER_LOG_PATH` env var (same role as
  today: an override), with the Session Id inserted before the file
  extension.
- The old single-file, all-Sessions-forever `router_log.jsonl` is fully
  replaced, not kept alongside the new per-Session files. No migration
  path for old log content is needed (it's local, disposable output,
  not a system of record).
- Three entry kinds in one Session's file, in the order they occur:
  - `session_start`: Session Id, start timestamp, the resolved tier ->
    provider/model config in use.
  - one entry per Attempt (existing fields — task, tier, provider,
    model, latency, cost, tokens, ok/error, attempt number,
    cost_estimated — plus the assistant's answer text for that
    exchange and any Tool calls it requested: id/name/arguments).
  - one entry per locally-executed Tool call (name, arguments, result
    or error, the Tool call's correlation id) — new, does not exist
    today.
  - `session_end`: end timestamp, exit reason (e.g. exit command, EOF,
    idle interrupt, unhandled exception), total spend for the Session.
- One JSON line per Attempt stays the unit for Provider exchanges (not
  one line per completed Conversation turn) — already confirmed by the
  user, matches today's Call Log granularity.
- Every entry line carries its own `session_id` and a `type`
  discriminator (`session_start` / `attempt` / `tool_execution` /
  `session_end`), even though the file itself is already scoped to one
  Session by its filename — makes each line independently meaningful
  (concatenating or grepping across multiple Session files stays
  correct) and the stream self-describing without inferring the kind
  from which fields are present.

## Out of scope

- No log rotation, retention policy, or archival — `logs/` can grow
  unbounded across Sessions, same posture as the old single file just
  spread across more files; not this feature's problem to solve.
- No change to the Budget Guardrail (stays a separate in-memory
  counter, not derived from the Call Log file — this was already true
  and stays true; see `docs/CONTEXT.md`'s updated Decisions section for
  why they stay separate even though both are now Session-scoped).
- No querying/analysis tool over the Session files — this feature only
  produces the files; reading them is left to the user's own tools
  (`jq`, grep, etc.) for now.
- `route()`'s public signature, the Router's tier-ladder/Escalation
  logic, and every Provider are untouched — this is purely how and
  where the Call Log writes, not what triggers a call.

## Settled decisions (from discovery)

- Session Id format: sortable UTC timestamp + short random suffix
  (not a bare UUID4, not a bare short random id) — see rationale above.
- Old aggregate `router_log.jsonl` is removed entirely, not kept
  alongside per-Session files.
- `session_start`/`session_end` entries are in scope, not deferred.
- Per-Session files live under a new `logs/` directory by default
  (gitignored), not the repo root.

## Known impact (for the planner, not a product question)

- `ROUTER_LOG_PATH` env var semantics change from "the exact file
  path" to "the base path a Session Id is inserted into" — every test
  across `tests/test_call_log.py`, `tests/test_repl.py`,
  `tests/test_routing.py`, and the `_isolate_router_log` /
  `install_fake_urlopen` fixtures in `tests/conftest.py` that currently
  sets `ROUTER_LOG_PATH` to an exact file and reads that exact path
  needs to resolve the actual per-Session file instead (e.g. via a
  `call_log` helper that computes the path for a given Session Id, or
  by globbing the target directory). This is a real, repo-wide test
  migration, not a one-file change — flag it for ticket sizing.
- README's Call Log section (and its `ROUTER_LOG_PATH` example) needs
  updating for the new default path and per-Session behavior.
- Whether this decision (Call Log becomes per-Session instead of one
  shared unbounded file) earns its own ADR is the planner's call per
  the `domain-modeling` skill's three-part test — it is hard to
  reverse and a real trade-off (per-Session boundedness vs. easy
  single-file grep across all history), so it's a plausible candidate,
  but not decided here.

## Open questions

None — discovery settled all product-level decisions above.
