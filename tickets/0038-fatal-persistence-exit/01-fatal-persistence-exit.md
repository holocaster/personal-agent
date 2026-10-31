# 01: Report fatal Call Log persistence failures without a traceback

**What to build:** When the session ends because the Call Log cannot be written, the user sees one clear `Fatal ...` line on stderr and exit status 1, the same way a fatal audit error is reported today, instead of a Python traceback.

**Blocked by:** None (can start immediately).

**Spec:** none (fast path). **Evidence:** `tickets/0037-context-window/07-fatal-summary-attempt-persistence.review.md` (finding 1).

`src/personal_agent/__main__.py:main()` catches only `call_log.AuditError` around `run_repl`. A `call_log.PersistenceError` (failed Compression record restore, summarization Attempt append since 0037/07) or a raw `OSError` from a Call Log write (ordinary routed Attempt append) escapes as a traceback. `run_repl` already re-raises these without writing a session end, which stays unchanged.

- [x] **AC1** — `main()` handles `call_log.PersistenceError` and `OSError` raised by `run_repl` like `AuditError`: print one `Fatal ...` line naming the failure (exception message only, no traceback) to stderr and `sys.exit(1)`. The existing `Fatal audit error` output is unchanged. No other behavior changes; no new abstraction.
- [x] **AC2** — Tests call `main()` with `run_repl` raising `PersistenceError` and `OSError`, asserting exit status 1, the `Fatal ...` stderr line, and no traceback text; the existing `AuditError` path still passes.
- [x] **AC3** — Run the focused test file and `uv run --offline pytest -q`; record counts.
