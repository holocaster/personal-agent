# 0055: Fork, Background Jobs and Claude prompt caching

## Problem Statement

Three gaps remain from the research the user selected on 2026-10-17:

- Claude routes never ask the Provider to cache the reusable prompt prefix. Every exchange pays full input price, even when the prefix has not changed.
- The user cannot branch a conversation to try an alternative, such as another approach or another model, while keeping the original intact.
- `shell` kills its whole process group before returning. The agent therefore cannot keep a development server or a long test run going while it continues working.

## Solution

- **Prompt cache activation:** every request on a Claude route carries one request-level cache marker with the default five-minute lifetime. Claude routes are the direct Anthropic Provider, and OpenRouter when the model id starts with `anthropic/`. There is no setting and there are no manual breakpoints.
- **`/fork`:** creates a child Session from the latest closed turn. The REPL continues in the child immediately. The parent stays unchanged and can be resumed with `--resume <id>`. The child's Call Log is self-contained, so it resumes without reading the parent.
- **Background Jobs:** `shell` gains `background: true`, which returns a job id instead of waiting. New Tools `job_status` and `job_stop`, plus the REPL commands `/jobs` and `/jobs stop <id>`, inspect and end jobs. Jobs live only in the current Run. A Fork, `/exit` and the end of the Run stop them.

## User Stories

1. As a user on a Claude model, I want the reusable prompt prefix cached automatically, so that repeated exchanges cost less without any configuration.
2. As a user, I want caching to stay on through Tool follow-ups, retries, streaming and Compression on the same Claude route, so that every exchange in a task can reuse the prefix.
3. As a user on a non-Claude route, I want requests unchanged, so that caching for one Provider cannot break another.
4. As a user, I want existing cache read/write accounting and `/report` coverage to keep working, so that I can see whether caching happened instead of assuming savings.
5. As a user, I want `/fork` to branch the current conversation into a new Session, so that I can try an alternative without losing the original.
6. As a user, I want the child to carry the Conversation, Conversation Summary and Todo List exactly as they were after the latest closed turn, so that it continues from the same point.
7. As a user, I want the parent left unchanged and resumable with `--resume <parent id>`, so that I can go back to it later.
8. As a user, I want the child to resume even if the parent's Call Log is later deleted, so that each branch stands on its own.
9. As a user, I want the child's Run spend to start at zero and inherited history never counted as new Attempts or cost, so that spend and `/report` describe only the child's own work.
10. As a user, I want `/fork` refused while a failed or interrupted turn awaits `/retry`, so that pending work is not silently split or lost.
11. As a user, I want `/fork` refused while file recovery is unresolved or the Conversation is empty, so that a fork never starts from an unsafe or meaningless state.
12. As a user, I want Agent Mode and active Skills kept after a fork, so that the child behaves like the Run I was already in.
13. As a user, I want a fork to run no Tools, restore no files and create no worktree, and to be told that both Sessions share the Workspace Root, so that I understand file changes affect both branches.
14. As a user, I want the agent to start a long-running command in the background after the usual Tool Confirmation, so that it can keep working while a server or test suite runs.
15. As a user, I want background `shell` refused in `plan` and Dangerous Commands to still need Strong Confirmation, so that background mode never weakens existing gates.
16. As a user, I want the agent to check a job's state, exit code and recent output, so that it can react to a server failing or tests finishing.
17. As a user, I want the agent and me to be able to stop a job, so that nothing keeps running longer than needed.
18. As a user, I want `/jobs` to list this Run's jobs and `/jobs stop <id>` to stop one, so that I keep control without asking the model.
19. As a user, I want at most four live jobs and bounded retained output, so that a runaway command cannot exhaust memory or processes.
20. As a user, I want every job stopped when I fork, exit or the Run ends, including error paths the REPL handles, so that no orphaned process survives me.
21. As a user, I want `/clear` to keep jobs running, so that clearing the Conversation does not kill my dev server.
22. As a user, I want job start and stop visible in the Call Log, so that the recorded history shows what ran.
23. As a user who disabled `shell`, I want no job Tools offered, so that `PA_ENABLE_SHELL=0` still removes all shell capability.
24. As a maintainer, I want the production prompt fixtures updated through the regeneration script and reviewed, so that the new Tool surface is explicit.

## Requirements

### Prompt cache activation

- **R1 - Claude routes send one marker:** Every request from the direct Anthropic adapter includes a top-level `"cache_control": {"type": "ephemeral"}`, streaming and non-streaming alike. The same applies to the OpenRouter adapter when the exact model id starts with `anthropic/`. No `ttl`, no block-level `cache_control` and no breakpoint placement is added. This covers every exchange that goes through those adapters: ordinary tasks, Tool follow-ups, transient retries, explicit Retry and every Compression path.
- **R2 - Other routes unchanged:** OpenRouter requests for any other model id, and all OpenAI and Gemini requests, are byte-for-byte unchanged in payload keys. There is no setting, environment variable or command for caching.
- **R3 - Budgets, fixtures and accounting unaffected:** The marker lives in the adapter's request payload and stays outside prepared input, like the OpenRouter `session_id`. So prepared-input token counting, context budgets, the detailed audit's presented request and the prompt surface fixtures do not change because of it. Existing 0053 ticket 04 cache accounting keeps working unchanged, as does OpenRouter's reported cost. That accounting covers the disjoint Anthropic input/read/write categories, the `cache_creation` 5m/1h breakdown, OpenRouter `cached_tokens`/`cache_write_tokens`, estimated cost and `/report` cache coverage. The marker guarantees no cache hit or saving, and docs say so. Below the model's minimum cacheable length, the request is simply processed uncached.

### Fork

- **R4 - Command:** `/fork` takes no arguments. It appears in `/help` and completion. The help text says it continues in a new child Session copied from the latest closed turn, that it stops Background Jobs, that the parent stays resumable with `--resume <id>`, and that both Sessions share the Workspace Root.
- **R5 - Refusals:** `/fork` is refused with a clear message, records its command Audit Event with outcome `error`, and changes nothing in these cases:
  - a failed or interrupted turn awaits `/retry`, including one restored by Resume;
  - file recovery is unresolved, meaning the Session's file checkpoint is blocked;
  - the Conversation is empty, with no turns and no Conversation Summary.

  No Background Job is stopped by a refused fork.
- **R6 - Parent unchanged:** A successful fork first stops all Background Jobs (R14). It then records the `/fork` command Audit Event, ends detailed-audit coverage, and closes the parent's Run with `session_end` reason `fork`, its `total_cost` and the new `child_session_id`. The parent's Conversation, Conversation Summary, Todo List, submission count, pending state and file checkpoint are not modified. Resuming the parent later restores exactly the state it had at the fork.
- **R7 - Self-contained child Call Log:** The child gets a newly minted Session Id and run id in the same project storage. Its Call Log v3 starts with:
  1. a `session_start` carrying the usual identity and the current Provider/model, plus `parent_session_id`;
  2. one `conversation_forked` entry carrying `parent_session_id` and a copy of the parent's turns, Conversation Summary and Todo baseline, as they were in the REPL at the fork.

  Both lines are appended durably. Nothing in the child refers back to the parent's file for its content.
- **R8 - Strict replay:** Resume of the child rebuilds the copied state from the `conversation_forked` entry, then replays later child entries as usual (Clear, Undo, Compression, Turn End). Replay refuses the log, before any append, in these cases:
  - `session_start` has a `parent_session_id` that is not a valid Session Id or equals the child's own id;
  - line 2 is not a matching, well-formed `conversation_forked`;
  - a `conversation_forked` appears anywhere else, or without `parent_session_id`.

  A child resumes even when the parent's file no longer exists.
- **R9 - Fresh child progress:** In the child, Run spend starts at zero. Submission ordinals start at 1. There is no pending turn and no file checkpoint. The copied history adds no Attempt, execution, Tool execution or cost to the child's records, so `/report` and `/usage` in the child cover only the child's own activity. `--resume last` follows existing recency rules; after a fork that is the child.
- **R10 - Run state kept:** After a fork, the REPL keeps the current Agent Mode, active Skills, Memory Notes, Runtime Configuration and catalog. A new file-recovery checkpoint bound to the child Session replaces the parent's. Detailed-audit coverage, when enabled, restarts in the child. The REPL prints the parent and child Session Ids, how to resume the parent, and that both Sessions share the Workspace Root. Forking runs no Tools, restores no files, creates no worktree and makes no Provider call.
- **R11 - Discovery and reports:** The `session_logs` Tool timeline renders `conversation_forked` without the copied message, summary or Todo bodies. It shows the parent id and the number of copied turns, the same way Turn End omits its messages. `/report` treats the entry as non-execution metadata. A persistence failure while creating the child is the existing fatal persistence error. Its message names the parent Session Id so the user can resume it.

### Background Jobs

- **R12 - Starting:** The `shell` schema gains an optional boolean `background` (default false). `background: true` uses the same prepare step, Dangerous Command rules, Tool Confirmation, Strong Confirmation, `auto` behavior and `plan` refusal as `shell`. The confirmation preview marks the command as background. On approval, the command starts in the following environment:
  - `bash -c`, falling back to `sh -c`, in the Workspace Root;
  - stdin set to DEVNULL;
  - the same inherited environment minus `TAVILY_API_KEY`;
  - its own process group/session, with stdout and stderr merged.

  The call then returns at once with `{"job_id": <positive integer>, "state": "running"}`. `PA_SHELL_TIMEOUT_SECONDS` does not apply to background jobs. A failed start is a Tool error. Foreground `shell` is unchanged.
- **R13 - Limits:** At most four jobs may be running at once. A fifth start is a Tool error naming the limit and `job_stop`. It is checked before Tool Confirmation, so the user is not asked for an impossible start, and checked again at start. Each job keeps only its latest 64 KiB of combined output, discarding older bytes as they arrive. Finished jobs stay queryable; the registry keeps at most the 16 most recently finished ones and drops the oldest. Job ids increase within the process and are never reused.
- **R14 - Inspecting and stopping:**
  - `job_status(id)` returns `job_id`, `command`, `state` (`running`, `exited` or `stopped`), `exit_code` (null while running) and `output`. `output` is the latest retained bytes, capped by `PA_SHELL_MAX_OUTPUT_BYTES` and decoded as UTF-8 with replacement. It starts with a discard marker when older output was dropped.
  - `job_stop(id)` sends SIGTERM to the job's process group, then SIGKILL after the existing grace period, and returns the same status shape. Stopping an already finished job returns its status unchanged.
  - An unknown id is a Tool error for both.
  - Neither Tool needs Tool Confirmation. `job_status` is available in `plan`; `job_stop` is refused in `plan` like `shell`.
  - Both Tools are registered only when `shell` is, so `PA_ENABLE_SHELL=0` removes all three.
- **R15 - REPL commands:** `/jobs` lists this Run's jobs, one line each, with id, state, exit code and the sanitized and truncated command. With no jobs it says so. `/jobs stop <id>` stops one job, or reports an unknown id. Both work in every Agent Mode and appear in help and completion. Their command Audit Event records the arguments.
- **R16 - Lifecycle:** Jobs belong to the Session in the current Run and are never persisted, so a Resume never restores them. `/clear`, `/undo`, `/retry`, Compression and Agent Mode changes keep them. A Fork stops all of them (R6). So does every exit path that `run_repl` handles: `/exit`, `exit`/`quit`, EOF, Ctrl-C at the prompt, an unhandled exception, and fatal audit/persistence errors. Stopping all jobs signals every live group first, then waits one shared grace period before SIGKILL. When jobs were stopped implicitly by Fork or Run end and the Call Log is still writable, one Audit Event (`background_jobs_stopped`, with trigger and job ids) is written before `session_end`. Starts and stops made through Tools appear as ordinary `tool_execution` entries. Processes that leave the process group (for example via `setsid`), and termination of the agent itself by a signal the REPL cannot handle, are outside this guarantee.

### Documentation and fixtures

- **R17 - Docs and fixtures:**
  - Update the concise README for `/fork`, Background Jobs and Claude caching, including the shared Workspace Root and the no-guaranteed-saving caveat.
  - Update the REPL help, including the `/clear` text saying jobs are kept, and the `.notebook` contracts.
  - Regenerate the three production prompt surface fixtures with the documented script and review the diff. The shell schema and description change, `job_status`/`job_stop` appear in `build`/`auto`, and only `job_status` appears in `plan`.
  - Main owns `docs/CONTEXT.md` and `.ai/PROJECT_STATE.md`; coordinate with Main rather than editing them. Mark delivery status in the source research documents.

## Implementation Decisions

### Prompt cache activation

- The marker is added inside each adapter's `call` when the payload is built, after prepared input is merged and next to `max_tokens`. The Router, prepared input, token estimates and the Provider Contract do not change. This mirrors the existing OpenRouter `session_id` keyword, which also stays out of prepared input.
- Anthropic direct: always. OpenRouter: `model.startswith("anthropic/")` on the exact id. No other Provider learns about caching.
- Official syntax checked 2026-10-17:
  - [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching): automatic caching is a top-level `cache_control: {"type": "ephemeral"}` with a five-minute default lifetime and no beta header. The breakpoint moves to the last cacheable block and uses one of the four breakpoint slots. Usage reports `cache_creation_input_tokens`, `cache_read_input_tokens` and the `cache_creation` TTL split.
  - [OpenRouter prompt caching](https://openrouter.ai/docs/guides/best-practices/prompt-caching): OpenRouter accepts the same top-level field on Chat Completions for Anthropic models, across Anthropic, Vertex, Azure and Bedrock hosts; Bedrock converts it to a trailing breakpoint. It reports `prompt_tokens_details.cached_tokens` and `cache_write_tokens`, which the existing normalizer already reads.
- Known risk: the OpenRouter payload keeps `provider.require_parameters: true`. The documentation lists top-level caching for every Anthropic host, so no host should be filtered out, but this cannot be proven offline. No live call is part of this feature.

### Background Jobs: one registry module

- A new Tools-area module, `jobs`, owns process-global job state for the current Run. Its small interface:
  - `start(shell_path, command)` returns the job id;
  - `status(job_id)` and `stop(job_id)` return the status dict;
  - `listing()` returns rows for `/jobs`;
  - `stop_all()` returns the stopped ids;
  - `reset()` is for tests only.

  It hides Popen setup, the merged-output drain thread and 64 KiB ring buffer, state transitions, the live and finished bounds, and group termination. It reuses `shell`'s group-kill and environment rules rather than duplicating them; small shared helpers may move or be exposed. The deletion test justifies a separate module: without it, the Tools, the REPL commands and three lifecycle call sites would each need to know about process groups and buffers.
- `shell`'s prepare step reads `background` and checks the live limit. Its apply step dispatches to `jobs.start` when `background` is true. `job_status` and `job_stop` are plain-function registry entries with `requires_confirmation=False`. `enable_shell_tool` and `reset_registry` add and remove them with `shell`. `job_status` joins the plan Tool names; `job_stop` joins the plan-denied names.
- The REPL calls `jobs.stop_all()` at Fork (before the parent `session_end`) and from `run_repl`'s exit handling. On the normal path that happens before `end_coverage`/`session_end`; on exception paths it happens before `session_end(error)` or re-raise. `/jobs` is handled in the REPL command handler and added to the commands that accept arguments.
- Job output is Tool result content. It goes through the existing result redaction and logging path like `shell` output.

### Fork: one Call Log operation plus REPL state switch

- New `call_log.fork_session(config, turns, summary, todo_baseline) -> child_session_id` hides:
  1. minting the child id and run id;
  2. writing the parent `session_end` (reason `fork`, `total_cost`, `child_session_id`);
  3. validating project storage as `start_session` already does;
  4. writing the child `session_start` (with `parent_session_id`) and the `conversation_forked` seed, both durably with append-restore on failure;
  5. switching the module's current Session/run ids and resetting Run spend.

  `SESSION_END_FORK = "fork"` joins the existing end reasons. Replay validation and `load_conversation` handle `conversation_forked` as the initial state, using strict rules (R8).
- Seed shape: `{"type": "conversation_forked", "session_id", "timestamp", "parent_session_id", "turns": [[message, ...], ...], "summary": str | null, "todo_baseline": [todo item, ...]}`. Turns are the exact normalized messages already held by the REPL, which are the same messages an `ok` Turn End records. Rebuilding the current Todo List from baseline plus turns therefore matches the parent exactly.
- Why a separate seed line rather than putting the seed inside `session_start`: line 1 is read by project-wide validation, `--resume last` selection and `/report`, all under the 256 KiB per-record bound in `session_logs`. A large seed on line 1 would make the whole child unreadable to those readers. On a separate line it degrades at worst to the existing oversized-record notice, which large Turn Ends can already produce. Resume replay has no per-line bound.
- The REPL `/fork` handler runs these steps in order:
  1. check refusals (R5);
  2. stop jobs and write the implicit-stop Audit Event;
  3. write the `/fork` command Audit Event in the parent;
  4. close the detailed-audit action and coverage;
  5. call `fork_session` with the active Runtime Configuration;
  6. start coverage in the child;
  7. replace the file-recovery checkpoint with one for the child;
  8. reset the submission counter to 0, `last_routed` to none and the last assessment to none.

  Turns, summary and Todo baseline remain the same Python state. They are now owned by the child, since they were copied to its log. The main loop must not write a second command Audit Event for a successful `/fork` into the child.
- [ADR-0013](../adrs/0013-fork-copies-into-a-new-session.md) records why Fork copies history into a new self-contained Session. ADR-0005 rejected exactly that design for Resume; Fork is a different operation.

## Testing Decisions

- Test observable behavior at the highest existing seams. Assert outputs, Call Log entries, resumed state and process liveness, not private registry fields.
- **Caching:** use the existing offline Provider tests, which patch the `http` transport, and assert the captured payload for:
  - direct Anthropic, streaming and non-streaming;
  - OpenRouter with an `anthropic/` id, streaming and non-streaming;
  - OpenRouter with a non-Anthropic id, plus OpenAI and Gemini, where the marker is absent;
  - a Compression request on a Claude route.

  The existing `test_cache_accounting`, `test_session_affinity` and `test_prompt_surface` suites must stay green. The prompt surface fixtures should not change for this part.
- **Fork:** drive `run_repl` with an input stream and offline fake Providers, as `test_repl`/`test_continuation` already do. Cover:
  - fork after turns, Compression and a Todo List: the child continues with the same `/history` and Todo List, ordinal 1, `$0` spend, and Agent Mode and Skills kept;
  - the parent file ends with `session_end` reason `fork` and is otherwise unchanged; resuming the parent restores its pre-fork state and pending-free status;
  - resuming the child after deleting the parent file;
  - each refusal (pending failed turn, interrupted turn after Resume, blocked recovery, empty Conversation) leaves both state and jobs untouched;
  - strict replay refusals for malformed seeds;
  - a child `/report` showing zero inherited executions;
  - `session_logs` rendering without copied bodies;
  - child-creation persistence failure stays fatal and names the parent.

  Prior art: `test_call_log`, `test_continuation`, `test_session_storage`, `test_session_report`, `test_session_logs`.
- **Background Jobs:** use real short `bash` commands through `registry.execute_batch` and `run_repl`, as `test_shell_tool` already does. Cover:
  - start returns immediately while the command runs;
  - status shows running, then exited with exit code and output tail;
  - `job_stop` kills a TERM-ignoring group;
  - the fifth start is refused before confirmation;
  - the 64 KiB retention, the `PA_SHELL_MAX_OUTPUT_BYTES` status cap and the discard marker;
  - unknown id, plan refusal of background `shell` and `job_stop`, and `job_status` allowed in plan;
  - Dangerous Command Strong Confirmation and rejection run nothing;
  - `PA_ENABLE_SHELL=0` removes all three Tools;
  - `/jobs` and `/jobs stop`;
  - `/clear` keeping jobs;
  - Fork, `/exit`, EOF and an injected unhandled exception all leaving no live group;
  - the Audit Event for implicit stops.

  Use bounded polling with short deadlines, not long sleeps. Each test resets the registry and stops leftover jobs.
- Run focused tests for each increment, then the complete installed `.venv/bin/pytest` suite at the end of each ticket. Localhost/MCP tests need sandbox escalation. No install, no paid or model call, no live cache-hit or savings measurement.

## Out of Scope

- MCP Tools, entry-point plugins and `/report` model-switch diagnostics.
- Job persistence, job stdin, job timeouts, and surviving Resume or agent termination by unhandled signals.
- Forking from an arbitrary earlier turn, concurrent Sessions and worktrees.
- Copying file checkpoints into the child.
- Cache TTL settings, one-hour cache, manual breakpoints, cache prewarming and live cache measurement.
- Caching on non-Claude routes, and inferring Claude from OpenRouter aliases that do not start with `anthropic/`.

## Further Notes

- Scope comes from the [brief](../briefs/0055-fork-jobs-claude-cache.md). Sources: [cache research](../research/done/2026-10-14-cache-and-session-routing.md), [reference opportunities section 4](../research/done/2026-10-14-reference-opportunities.md) and [feature opportunities (jobs)](../research/done/2026-10-09-feature-opportunities.md).
- The brief leaves several points open. These are planner decisions:
  - which job Tools are available in `plan` and need no confirmation;
  - the finished-job retention bound (16);
  - the `PA_SHELL_MAX_OUTPUT_BYTES` cap on `job_status` output;
  - refusing Fork on blocked recovery or an empty Conversation;
  - child ordinals starting at 1.

  Main may revisit them with the user without changing the slice structure.
- The three capabilities are independent, except that Fork stops Background Jobs. The cache ticket stands alone; the Fork ticket builds on the jobs registry.
