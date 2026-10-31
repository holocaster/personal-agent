# 04: Fork seed-failure cleanup and honest `/jobs stop` message

**What to build:** Two follow-ups from the Batch 02-03 review (`02-03-batch.review.md`). A Fork that fails after the child Session file exists leaves no unresumable child behind, and `/jobs stop <id>` reports what actually happened to the job.

**Blocked by:** 02, 03 (done).

**Spec:** none (fast path). Context: `docs/specs/0055-fork-jobs-claude-cache.md` R11 and the Background Jobs REPL commands; ADR-0013.

- [x] In `call_log.fork_session`, when any write to the child fails after the child Session file was created (including the `conversation_forked` seed write after a durable child `session_start`), the child file is removed before the existing fatal PersistenceError is raised. The error still names the parent Session Id and the `--resume <parent>` command. The parent file is left as it is today.
- [x] After such a failure, `--resume last` (and `session_logs` last-session selection) never selects a broken child, because no child file remains.
- [x] A test injects a failure on the seed write after the child `session_start` succeeded and asserts: the error is fatal and names the parent, no child file exists, and resuming the parent works.
- [x] `/jobs stop <id>` on a running job keeps printing that the job was stopped. On a job that had already exited or been stopped, it prints the job's unchanged final state (state and exit code when known) instead of "Stopped job". Unknown ids keep their current error. The `job_stop` Tool is unchanged.
- [x] A REPL test covers `/jobs stop` on a running job and on an already finished job.
- [x] No code comments unless really necessary; `docs/CONTEXT.md` and `.ai/PROJECT_STATE.md` are not edited.
- [x] Focused tests pass, then the full installed `.venv/bin/pytest` suite passes, with no leftover job processes.
