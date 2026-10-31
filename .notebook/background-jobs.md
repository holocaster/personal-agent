# Background Jobs
> `shell` background mode, job Tools and lifecycle (feature 0055)

Module: `src/personal_agent/tools/jobs.py` owns process-global job state for the current Run: `start`, `status`, `stop`, `listing`, `stop_all`, `check_capacity`, test-only `reset` (called by the autouse `tests/conftest.py:_reset_shell_tool_registry`).

Contracts:
- `registry._prepare_shell_call()` runs `shell.prepare_shell()` (preview prefixed `[background job]`) then `jobs.check_capacity()` before Tool Confirmation; `jobs.start()` checks again under the lock.
- Popen mirrors foreground `shell`: `[shell, "-c", command]`, Workspace Root cwd, DEVNULL stdin, `shell.shell_environment()` (no `TAVILY_API_KEY`), `start_new_session=True`, stderr merged into stdout. No timeout.
- One drain thread fills a 64 KiB ring (`RING_BYTES`); one watcher thread waits for the leader, marks `exited`, then kills the rest of the group with `shell.kill_process_groups()` (TERM all, one shared `KILL_GRACE_SECONDS`, KILL).
- Limits: `MAX_RUNNING = 4`; `MAX_FINISHED = 16` finished jobs retained, oldest dropped; ids increase per process and are never reused (only `reset` restarts them).
- `status()` output = last `PA_SHELL_MAX_OUTPUT_BYTES` bytes, UTF-8 with replacement, `DISCARD_MARKER` prefix when bytes were dropped.
- `job_status` is in `PLAN_TOOL_NAMES`; `job_stop` in `PLAN_DENIED_NAMES`; both are added/removed with `shell` (`SHELL_TOOL_NAMES`).
- `run_repl()` calls `jobs.stop_all()` before `end_coverage` on every normal exit, and in the exception path before `session_end(error)` or re-raise. A non-empty result writes `audit_event` `action=background_jobs_stopped` with `trigger` (the session end reason, or `fork`) and `job_ids`, skipped after `AuditError`/`PersistenceError`.

Caveats: never persisted; no guarantee for processes that leave the group (`setsid`) or for an agent killed by an unhandled signal.

Tests: `tests/test_background_jobs.py` (real short `bash` commands, bounded polling).

Updated: 2026-10-17
