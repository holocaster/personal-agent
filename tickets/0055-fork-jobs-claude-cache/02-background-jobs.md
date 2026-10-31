# 02: Run and control Background Jobs

**What to build:** The model can start a long-running `shell` command in the background after the usual confirmation. It gets a job id back and keeps working. The model checks the job with `job_status` and ends it with `job_stop`. The user lists and stops jobs with `/jobs` and `/jobs stop <id>`. Jobs are bounded, kept across `/clear`, never persisted, and every live job's process group is stopped when the Run ends.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0055-fork-jobs-claude-cache.md`, R12-R16 (except the Fork trigger, which is ticket 03), R17 (job docs and fixture regeneration); Implementation Decisions "Background Jobs: one registry module"; Testing Decisions "Background Jobs".

- [x] A new Tools-area `jobs` module owns the current Run's jobs behind `start`, `status`, `stop`, `listing`, `stop_all` and a test-only `reset`. It reuses `shell`'s environment (no `TAVILY_API_KEY`), Workspace Root cwd, DEVNULL stdin, own process group and group-kill rules. stdout and stderr are merged into a 64 KiB latest-bytes ring. No timeout applies. Ids increase and are never reused. At most four jobs may run at once, and at most the 16 most recently finished jobs are retained.
- [x] `shell` accepts optional `background` (boolean, default false). Background calls use the same prepare step, Dangerous Command rules, Tool Confirmation, Strong Confirmation, `auto` behavior and `plan` refusal; the preview marks the command as background. The live limit is checked before confirmation and again at start. The call returns `{"job_id", "state": "running"}`. Foreground `shell` behavior and its tests are unchanged.
- [x] Two new Tools, `job_status(id)` and `job_stop(id)`, return `job_id`, `command`, `state` (`running`/`exited`/`stopped`), `exit_code` and `output`:
  - `output` is the latest retained bytes capped by `PA_SHELL_MAX_OUTPUT_BYTES`, decoded as UTF-8 with replacement, and starts with a discard marker when older output was dropped;
  - stopping a finished job returns its status unchanged;
  - an unknown id is a Tool error.

  Neither Tool needs confirmation. `job_status` is allowed in `plan`; `job_stop` is refused in `plan`. Both are registered and removed together with `shell`, so `PA_ENABLE_SHELL=0` offers none of them.
- [x] `/jobs` lists id, state, exit code and the sanitized, truncated command, or says there are no jobs. `/jobs stop <id>` stops one job, or reports an unknown id. Both work in every Agent Mode, appear in help and completion, and record their arguments in the command Audit Event. The `/clear` help text says jobs are kept.
- [x] Every exit path that `run_repl` handles stops all live jobs before returning or re-raising. These paths are `/exit`, `exit`/`quit`, EOF, Ctrl-C at the prompt, an unhandled exception, and fatal audit/persistence errors. Stopping signals all groups first, then waits one shared grace period before SIGKILL. While the Call Log is writable, one `background_jobs_stopped` Audit Event (with trigger and job ids) is written before `session_end`. Starts and stops through Tools appear as ordinary `tool_execution` entries. Resume never restores jobs.
- [x] Tests use real short `bash` commands through `execute_batch` and `run_repl`, with bounded polling. They cover:
  - immediate return while the command runs;
  - running, then exited with exit code and tail;
  - stopping a TERM-ignoring group;
  - the fifth start refused before confirmation;
  - ring retention, the status cap and the discard marker;
  - unknown id;
  - the `plan` rules for all three Tools;
  - Dangerous Command Strong Confirmation, and rejection running nothing;
  - `PA_ENABLE_SHELL=0`;
  - `/jobs` and `/jobs stop`;
  - `/clear` keeping jobs;
  - `/exit`, EOF and an injected exception leaving no live group;
  - the implicit-stop Audit Event.

  Every test cleans up its jobs.
- [x] Regenerate the three prompt surface fixtures with `.venv/bin/python -m tests.prompt_surface tests/fixtures/prompt-surface` and review the diff:
  - the `shell` schema and description gain `background`;
  - `job_status` and `job_stop` appear in `build`/`auto`;
  - only `job_status` appears in `plan`;
  - nothing else changes.
- [x] Update the concise README (`shell` section) and the `.notebook` contracts for Background Jobs, including the limits and the no-persistence/no-escape-guarantee caveats. Do not edit `docs/CONTEXT.md` or `.ai/PROJECT_STATE.md`.
- [x] Focused tests pass, then the complete installed `.venv/bin/pytest` suite passes.
