# 0018 — Shell tool

## Goal

Give the agent a third Mutating Tool — `shell` — so it can run one command in the Workspace Root, not just read and write named files. This closes the remaining tool-parity gap against the reference project `opencode` (see `docs/research/done/2026-09-23-opencode-feature-comparison.md`), reuses the Tool Confirmation gate built for `write`/`edit` (feature 0016), and is the "commands" part of the future work already anticipated in `docs/CONTEXT.md`'s Tool boundary decision.

## Scope

- **`shell(command)`**: runs `command` as a single string via `bash -c <command>` (falls back to `sh -c` when `bash` is not on `PATH`). Always executes in the Workspace Root — no `cwd` argument. No stdin (`DEVNULL`).
- Returns `{stdout, stderr, exit_code}` on a normal run, including a non-zero `exit_code` — that is a result, not a Tool error.
- `ROUTER_SHELL_TIMEOUT_SECONDS` (default 30): a command that exceeds it is sent SIGTERM, then SIGKILL if still alive; the timeout itself is a Tool error.
- `ROUTER_SHELL_MAX_OUTPUT_BYTES` (default equal to `ROUTER_MAX_READ_BYTES`): stdout/stderr each truncated past this cap with the same `[...truncated]` marker `read_file` already uses.
- `ROUTER_ENABLE_SHELL=1`: gates registration, not just execution. Unset (default) means `shell` is never added to the Tool Registry, so it is never advertised to a Provider and never confirmable. This is the only built-in Tool with a registration toggle.
- New Tool Confirmation variant: shows the exact command string (not a diff) before running.
- Logging: the existing Tool execution Call Log entry (arguments + result) is the audit trail. No new entry type.

## Out of scope

- Command allowlist/blocklist — Tool Confirmation (the human sees the exact command before it runs) is the only gate, same posture as `write`/`edit`'s diff-before-approval.
- A `cwd` argument letting the model pick a subdirectory — always the Workspace Root.
- stdin support — there is no channel for the model to supply input; a command that blocks on stdin simply runs to timeout.
- Environment filtering — the subprocess inherits the parent process's environment unfiltered.
- Registration toggles for any other Tool — `calculator`, `current_time`, the three Workspace Tools, `write`, and `edit` all stay unconditionally registered; `ROUTER_ENABLE_SHELL` is specific to `shell`.
- Everything already out of scope for Tools in general and unaffected by this feature: MCP, patches.

## Settled decisions

1. `shell` is opt-in via `ROUTER_ENABLE_SHELL=1`, default off — the one deliberate exception to "every Tool is always registered." Arbitrary command execution is a materially larger risk step than reading or writing one named file; a user who never opted in should never see a shell-confirmation prompt at all.
2. No allowlist/blocklist of commands — evaluated and rejected as an easy-to-bypass, expensive-to-maintain "protection" on top of the confirmation that already shows the exact command.
3. Environment is inherited unfiltered — filtering would need a maintained list that grows with every new project env var; the command was already visible in Tool Confirmation before running, so this discloses nothing new.
4. Non-zero exit code is a normal result, not a Tool error — `grep` with no match, `test` returning false, etc. are legitimate outcomes the model needs to see, not failures.
5. Execution is a single command string through `bash -c` (fallback `sh -c`), not an argv list without a shell — pipes, redirects, and `&&` composition are the point of a shell Tool; the safety story is Tool Confirmation, not restricting syntax.
6. No stdin, no `cwd` argument — kept out to minimize the parameter surface; both were evaluated and explicitly rejected rather than deferred silently.

## Open questions

None — grilling frontier closed and confirmed by the user on 2026-09-24.

## Known issues

None — the README staleness and both round-2 residual risks were resolved by ticket 03 (see below). No open known issues remain for this feature.

## Follow-up: ticket 03 — always-clean shell (post-approval correction, done)

The round-2 review's two `suggestion`-severity residual risks were initially accepted as out of scope, then the user asked to fix both. This reopened `shell`'s process-lifecycle behavior with two new settled decisions:

7. **`shell` is strictly ephemeral: the whole process group is killed at the end of every call, not just on timeout.** Today only a timed-out call kills the group; a call that returns normally (no timeout) can leave background children alive past the Tool result (e.g. `nohup server >/dev/null 2>&1 &`). Spec user story 24 already said "nothing keeps running in the background after the Tool returned" — the code didn't match it. Chosen over preserving "start a background service and let it survive" as a use case: an agent-facing shell Tool that silently leaves orphaned processes running is a worse default than one that can't background anything, and there is no way to signal "let this survive" without a new parameter (out of scope). Applies after a normal (non-timeout) return too, not only after SIGTERM/SIGKILL escalation.
8. **The final stdout/stderr drain-thread joins get their own bounded timeout**, separate from and in addition to the command timeout. A command that calls `setsid` escapes the process group entirely (a real, if rare, escape hatch — `nohup`+`setsid`, or a self-daemonizing process), so `_kill_process_group`'s SIGKILL cannot reach it and the joins could still block forever waiting for that orphan to close the pipes. This does not kill the escaped process (no sandboxing, unchanged decision) — it only guarantees the Tool call itself always returns, as a Tool error, within a bounded time. The escaped process may keep running as an orphan; that is accepted.

These decisions replace the two "accepted, out of scope" entries from round-2 review. Scope for ticket 03: change `apply_shell` in `src/personal_agent/tools/shell.py` to always kill the process group before returning (on every path, not only timeout), and bound the final drain joins with their own timeout constant; fix the stale README "Tools" line; no other user-visible behavior changes (result shape, Tool Confirmation, opt-in gate, existing settings are all unaffected).

Implemented and approved 2026-09-24 (`tickets/0018-shell-tool/03-always-clean-shell.review.md`). A round-3 review's one `suggestion` finding (ticket-numbered, over-long comments in `shell.py`) was applied directly after approval; the full suite was re-run and stayed green (606 passed).
