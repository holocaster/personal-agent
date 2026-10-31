# 03: Fork the Session into a self-contained child

**What to build:** `/fork` branches the current Session at its latest closed turn. The REPL continues at once in a new child Session that holds a copy of the Conversation, Conversation Summary and Todo List, and that names its parent. The parent stays unchanged and can be resumed with `--resume <id>`. The child resumes on its own, even without the parent's file. Its Run spend, ordinals and report start fresh. The fork stops Background Jobs, runs no Tools, restores no files, and both Sessions share the Workspace Root.

**Blocked by:** 02 - Run and control Background Jobs (the fork stops all jobs through its registry).

**Spec:** `docs/specs/0055-fork-jobs-claude-cache.md`, R4-R11, R16 (Fork trigger), R17 (Fork docs, `.notebook`, research status); Implementation Decisions "Fork: one Call Log operation plus REPL state switch"; Testing Decisions "Fork". **ADRs:** ADR-0013; preserve ADR-0003, ADR-0005, ADR-0008, ADR-0010 and ADR-0011.

- [x] `call_log.fork_session(config, turns, summary, todo_baseline)` does three things:
  - writes the parent `session_end` with reason `fork`, `total_cost` and `child_session_id`;
  - validates project storage as `start_session` does;
  - writes, durably and with append-restore, the child `session_start` (log_version 3, identity, new run id, current Provider/model, `parent_session_id`) and one `conversation_forked` seed line holding the parent id, turns, Summary and Todo baseline.

  It then switches the current Session/run ids and resets Run spend.
- [x] Replay reads `conversation_forked` as the child's initial state in `load_conversation`, and then replays later entries as usual. It strictly refuses, before any append, each of the R8 malformed cases. A child resumes after its parent's file has been deleted.
- [x] `/fork` takes no arguments. It is refused, with outcome `error` and no state or job change, when:
  - a failed or interrupted turn awaits `/retry`, including after Resume;
  - file recovery is blocked;
  - the Conversation has no turns and no Summary.
- [x] A successful `/fork` runs these steps in order:
  1. stops all Background Jobs and writes the implicit-stop Audit Event in the parent;
  2. records the `/fork` command Audit Event in the parent only;
  3. ends detailed-audit coverage;
  4. forks;
  5. starts coverage in the child;
  6. binds a fresh file-recovery checkpoint to the child;
  7. resets the submission counter, `last_routed` and the last assessment.

  Agent Mode, active Skills, Memory, Runtime Configuration and catalog are kept. The REPL prints the parent and child ids, how to resume the parent, and the shared Workspace Root. No Provider call, Tool, file restore or worktree is involved.
- [x] In the child, the footer and `/usage` show `$0` spend, the first task gets ordinal 1, and `/history` and the Todo List match the parent. `/report` shows no inherited execution or Attempt. `--resume last` selects the child under the existing recency rules. The `session_logs` timeline renders the seed without copied bodies, showing the parent id and the number of copied turns.
- [x] A persistence failure while creating the child stays the existing fatal persistence error, and its message names the parent Session Id.
- [x] `/fork` appears in help and completion with the R4 text.
- [x] `run_repl` tests with offline fake Providers cover:
  - fork after turns, Compression and a Todo List;
  - the parent unchanged apart from its `session_end`, and resumable to its exact pre-fork state;
  - child Resume with the parent deleted;
  - each refusal;
  - malformed seed refusals;
  - Agent Mode and Skills kept;
  - jobs stopped by the fork;
  - child report and spend;
  - `session_logs` rendering;
  - the fatal child-creation failure.
- [x] Update the concise README and `.notebook` for `/fork`, the shared Workspace Root and parent resumption. Mark the delivery status of Fork and jobs in the research docs. Do not edit `docs/CONTEXT.md` or `.ai/PROJECT_STATE.md`.
- [x] Focused tests pass, then the complete installed `.venv/bin/pytest` suite passes.
