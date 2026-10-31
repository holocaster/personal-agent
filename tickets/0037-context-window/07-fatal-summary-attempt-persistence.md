# 07: Never continue after an unlogged summarization Attempt

**What to build:** A Call Log persistence failure while recording any summarization Attempt stops the session fatally on every Compression caller, so a charged Attempt is never left unlogged while work continues.

**Blocked by:** 06 — Use published input limits as capacity and make soft-trigger Compression optional (`0037/06`).

**Spec:** `docs/specs/0037-context-window.md` (R6 "All summarization Attempts ... remain normally logged and charged"; R9 "stop fatally if recording cannot be made safe"). **Evidence:** `tickets/0037-context-window/feature.review.md` (residual risk, pre-existing); `06-published-capacity-and-optional-soft-compression.review.md` (round 2, finding 2).

`router.compress()` catches every non-`AuditError` exception and turns it into an error string, so an `OSError`/`PersistenceError` from `call_log.append_entry` (or another Call Log write) during a summarization Attempt becomes an ordinary Compression failure on the above-ceiling, recovery and manual `/compress` paths. Ticket 06 made only the soft-only path fatal through a `fatal_persistence` flag. This predates 06 and matches how an ordinary routed Attempt append failure already ends the session.

- [x] **AC1 — One root-cause rule.** In `compress()`, an `OSError` or `call_log.PersistenceError` always propagates as `call_log.PersistenceError` (never an error string) for every caller. Remove the now-redundant `fatal_persistence` parameter and its argument in `_run_exchange`. Other failures (validation, counting, Provider errors) keep their existing error-string behavior. No new abstraction, config or schema.
- [x] **AC2 — Every caller.** Regression tests at the `run_repl` seam with the Call Log append failing only for task `/compress`: manual `/compress`, above-ceiling preventive Compression and overflow-recovery Compression each raise `PersistenceError`, send no pending exchange or recovery retry, write no `conversation_compressed`, and leave `load_conversation` unchanged. Keep the existing soft-only regression passing.
- [x] **AC3 — Verification.** Run `uv run --offline pytest -q tests/test_compression.py tests/test_preventive_compression.py tests/test_context_recovery.py tests/test_call_log.py` and `uv run --offline pytest -q`; record counts.
