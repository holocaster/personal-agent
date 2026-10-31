# 0018 - shell Tool

Brief: `docs/briefs/0018-shell-tool.md`. Vocabulary (shell Tool, Mutating
Tools, Tool Confirmation, Tool Registry, Workspace Root, Call Log, Terminal,
Input Box) is in `docs/CONTEXT.md`; scope is recorded there under "Tool
boundary" and "shell Tool scope and opt-in (feature 0018)". The two-phase
Mutating Tool mechanism and the `confirm` seam come from
`docs/specs/0016-write-tools.md` and are reused, not redesigned. No ADR:
every decision here is either settled in the brief and `docs/CONTEXT.md` or a
local mechanism choice.

## Problem Statement

The agent can read the Workspace Root and, since feature 0016, write and edit
named files in it, but it cannot run anything. When the user asks it to run
the tests, check `git status`, count lines, or grep with a pipe, the model
can only tell the user which command to type and wait for the output to be
pasted back. At the same time, arbitrary command execution is a much larger
risk than changing one named file, so a user who never asked for it must
never be offered it, and a user who did must see and approve every command
before it runs.

## Solution

A third Mutating Tool, `shell(command)`, runs one command string through
`bash -c` (or `sh -c` when `bash` is not on `PATH`) in the Workspace Root,
with no stdin, and returns `{stdout, stderr, exit_code}`. A non-zero exit
code is a normal result the model sees, not a Tool error.

`shell` exists only when the user opts in with `ROUTER_ENABLE_SHELL=1`.
Without it, `shell` is never added to the Tool Registry, so no Provider is
ever offered it and no shell confirmation can ever appear.

Before every command, the REPL shows a Tool Confirmation with the exact
command string (not a diff) and asks `Run this command? [y/N] `. Only an
explicit yes runs it. `ROUTER_SHELL_TIMEOUT_SECONDS` (default 30) bounds how
long a command may run: on expiry it is sent SIGTERM, then SIGKILL, and the
call is a Tool error. `ROUTER_SHELL_MAX_OUTPUT_BYTES` (default: the effective
`ROUTER_MAX_READ_BYTES`) caps stdout and stderr, each truncated with a
`[...truncated]` marker. The existing Tool execution Call Log entry is the
audit trail.

`shell` is strictly ephemeral (ticket 03, brief decisions 7 and 8): the
command's whole process group is killed at the end of every call, not only on
timeout, so nothing it started in the background survives the Tool result.
The only process that can escape is one that leaves the process group (for
example via `setsid`); it is not killed, but it can no longer hang the call:
waiting for the output to close is itself bounded, and on expiry the call
returns a Tool error.

## User Stories

1. As a REPL user, I want the model to run a shell command in my Workspace Root, so that it can run tests, inspect Git state, or query files without me copying output back and forth.
2. As a REPL user, I want `shell` unavailable unless I set `ROUTER_ENABLE_SHELL=1`, so that I never get arbitrary command execution I did not ask for.
3. As a REPL user who did not opt in, I want no Provider ever to be offered `shell`, so that the model cannot even try to request it.
4. As a REPL user who did not opt in, I want never to see a shell confirmation prompt, so that the feature is fully invisible until I enable it.
5. As a user, I want an unrecognized `ROUTER_ENABLE_SHELL` value (for example `true` or `yes`) to stop startup with a configuration error, so that a typo neither silently enables nor silently disables the Tool.
6. As a user, I want `ROUTER_ENABLE_SHELL` set to `1` in my `.env` file to work the same as in the environment, so that it follows every other setting.
7. As a REPL user, I want to see the exact command string before it runs, so that I know precisely what will execute.
8. As a REPL user, I want control characters in the displayed command sanitized, so that a malicious command cannot hide itself or hijack my terminal.
9. As a REPL user, I want the shell confirmation header to name the Tool and the Workspace Root it will run in, so that I know where the command runs.
10. As a REPL user, I want the question to read `Run this command? [y/N]`, so that it is clear I am approving an execution, not a file change.
11. As a REPL user, I want anything other than an explicit `y`/`yes` (including an empty line) to reject the command, so that a stray Enter never runs anything.
12. As a REPL user, I want the model told that I rejected the command, so that it can adjust instead of assuming it ran.
13. As a REPL user, I want Ctrl-C at the confirmation question to interrupt the turn without running the command, so that I can abort the whole request.
14. As a user piping input into the REPL, I want the confirmation answer read from the next input line and end of input treated as rejection, so that scripted runs stay explicit and fail closed.
15. As a REPL user, I want pipes, redirects, and `&&` to work, so that the model can compose commands the way a person would.
16. As a REPL user, I want `bash` used when available and `sh` otherwise, so that the Tool works on minimal systems.
17. As a REPL user, I want a missing shell binary reported as a Tool error before I am asked to confirm, so that I never approve a command that cannot run.
18. As a REPL user, I want every command to run in the Workspace Root, so that relative paths in the command mean the same as for the file Tools.
19. As a REPL user, I want commands to get no stdin, so that a command waiting for input cannot read from my terminal or steal my next REPL line.
20. As a REPL user, I want stdout, stderr, and the exit code returned to the model, so that it can reason about what happened.
21. As a REPL user, I want a non-zero exit code returned as a normal result, so that `grep` with no match or a failing test run is information, not a Tool failure.
22. As a REPL user, I want a command that runs longer than `ROUTER_SHELL_TIMEOUT_SECONDS` (default 30) stopped, so that a hung command cannot block my turn forever.
23. As a REPL user, I want a timed-out command sent SIGTERM first and SIGKILL only if it is still alive, so that well-behaved programs can clean up.
24. As a REPL user, I want child processes a command started killed with it on timeout and, since ticket 03, at the end of every call, so that nothing keeps running in the background after the Tool returned.
25. As a REPL user, I want a timeout reported as a Tool error naming the limit, so that the model knows the command did not complete.
26. As a REPL user, I want stdout and stderr each capped at `ROUTER_SHELL_MAX_OUTPUT_BYTES`, so that a noisy command cannot flood the Conversation or the Call Log.
27. As a REPL user, I want truncated output to end with `[...truncated]`, so that the model knows it did not see everything.
28. As a REPL user, I want output past the cap discarded as it arrives rather than held in memory, so that a command like `yes` cannot exhaust memory before the timeout.
29. As a user, I want `ROUTER_SHELL_MAX_OUTPUT_BYTES` to default to my effective `ROUTER_MAX_READ_BYTES`, so that one setting governs how much text the model sees.
30. As a user, I want invalid `ROUTER_SHELL_TIMEOUT_SECONDS` or `ROUTER_SHELL_MAX_OUTPUT_BYTES` to stop startup with a configuration error when shell is enabled, so that a typo is not silently ignored.
31. As a user who did not enable shell, I want the two shell settings ignored, so that a stale value cannot break startup for a Tool I do not use.
32. As a REPL user, I want output that is not valid UTF-8 shown with replacement characters rather than failing the call, so that binary noise does not hide the rest of the result.
33. As a REPL user, I want the command to inherit my environment, so that it sees the same `PATH`, virtualenv, and tool settings I have.
34. As a Call Log reader, I want each `shell` call (run, rejected, timed out, or failed) recorded as a normal Tool execution entry with its command and result, so that the Call Log is the audit trail of every command.
35. As a Call Log reader, I want no new Call Log entry type, so that Resume and existing readers keep working unchanged.
36. As a REPL user, I want the live `tool>` line printed for `shell` like any other Tool, so that I see the outcome after confirming.
37. As a developer calling `route()` without a confirmation callback, I want `shell` rejected, so that no code path can run a command without a gate.
38. As a REPL user, I want every other built-in Tool registered exactly as before regardless of `ROUTER_ENABLE_SHELL`, so that enabling or disabling shell changes nothing else.
39. As a README reader, I want `shell`, its opt-in, confirmation, timeout, output cap, inherited environment, and lack of sandboxing documented, so that I understand the risk before enabling it.
40. As a REPL user, I want every process a command left running in its process group killed when the call ends, even when the command itself exited normally, so that a `shell` call never leaves an orphaned background process behind (ticket 03).
41. As a REPL user, I want a command that neither backgrounds anything nor times out to return exactly the same result, as fast as before, so that the always-clean rule costs nothing for ordinary commands.
42. As a REPL user, I want a `shell` call to return within a bounded time even when a process that escaped the process group (for example via `setsid`) keeps the command's output open, so that no command can hang my turn forever.
43. As a REPL user, I want that bounded-wait case reported as a Tool error that says a detached process may still be running, so that the model and I know something escaped cleanup.
44. As a README reader, I want the always-clean behavior and the `setsid` escape documented, and the "## Tools" section to stop claiming there are only two built-in Tools, so that the README matches what the model is actually offered.

## Implementation Decisions

- **Tools module.** `shell` lives in a new module in the tools package (a
  sibling of the workspace module), not inside the workspace module: it
  resolves no paths. It reads the Workspace Root from the existing workspace
  configuration.
- **Two-phase Mutating Tool, reused.** `shell` is a Mutating Tool in the
  existing Tool Registry shape: prepare, then Tool Confirmation, then apply.
  Prepare resolves the shell binary (`bash` via `PATH`, else `sh`; neither is
  a Tool error) and builds the confirmation preview; it runs nothing. Apply
  executes. The prepared value only needs what the existing `confirm` call
  and apply step consume (a display label, a preview, and what apply needs);
  the implementer may generalize the prepared type or add a shell-specific
  one, but must not change behavior for `write`/`edit`.
- **Execution.** `[<shell>, "-c", command]` as an argv list (no second
  shell layer), cwd the Workspace Root, stdin `DEVNULL`, environment
  inherited unfiltered, started in its own process group/session so the
  whole group can be signalled.
- **Result.** A completed command returns `{"stdout": str, "stderr": str,
  "exit_code": int}` as a normal (non-error) Tool result, whatever the exit
  code. Output bytes are decoded as UTF-8 with replacement characters. Only
  a timeout, a missing shell binary, or an internal/OS failure to start the
  process is a `ToolExecutionError`.
- **Timeout.** `ROUTER_SHELL_TIMEOUT_SECONDS`: unset or empty means 30;
  otherwise a positive whole number of seconds. On expiry the process group
  receives SIGTERM; if it is still alive after a short fixed grace period
  (a few seconds, not configurable) it receives SIGKILL. The call is then a
  Tool error naming the timeout (`command timed out after N seconds`).
  Partial output is not returned on timeout.
- **Always-clean process lifecycle (ticket 03, brief decision 7).** Once
  the apply step has its outcome (a normal completion whose output pipes
  both reached EOF, or a timeout), it kills the command's process group on
  every path before returning: SIGTERM, the same fixed grace period, then
  SIGKILL, exactly as the timeout path already does. A normal completion
  still returns `{stdout, stderr, exit_code}` with the leader's exit code;
  the kill does not change the result. The cleanup must tolerate a group
  that is already empty (the common case: nothing was backgrounded) without
  raising and without waiting out the grace period, so an ordinary
  command's result and timing are unchanged. The existing rule that a
  leader exit with pipes still held open by a group member at the deadline
  is a timeout (ticket 02) is kept; ticket 03 does not turn that case into
  a normal result.
- **Bounded final drain (ticket 03, brief decision 8).** After the group has
  been killed, waiting for the stdout/stderr drain threads to finish is
  bounded by its own fixed, non-configurable constant (a couple of seconds,
  separate from and in addition to `ROUTER_SHELL_TIMEOUT_SECONDS` and the
  kill grace period). If either drain is still running when it expires, a
  process outside the group is holding the pipes: the call returns a Tool
  error `command timed out after N seconds; a process that left the process
  group may still be running`. Nothing further is done to that process (no
  sandbox). The abandoned drain threads must not keep the interpreter alive
  on exit, and the pipe objects they are reading must not be closed from the
  calling thread while they are still reading (closing a buffered pipe
  blocks on the reader's lock until the read returns, which would reintroduce
  the hang); they are released when the escaped process closes them.
- **Output cap.** `ROUTER_SHELL_MAX_OUTPUT_BYTES`: unset or empty means the
  effective `ROUTER_MAX_READ_BYTES` value (after its own default); otherwise a
  positive whole-byte count, parsed the same way as the existing byte limits.
  stdout and stderr are capped independently. Capture is bounded: both pipes
  are drained concurrently, the first cap bytes of each are kept, and the rest
  is read and discarded (never buffered whole). A stream that exceeded the
  cap has the literal `[...truncated]` marker appended after decoding.
- **Opt-in registration.** `ROUTER_ENABLE_SHELL`: exactly `1` enables; unset,
  empty, or `0` disables; any other value is a configuration error. The Tool
  Registry exposes one explicit startup function (called by `main` after
  `.env` loading and workspace configuration, never at import time, because
  `.env` is loaded after imports) that, when enabled, adds the `shell` entry
  and rebuilds `TOOL_DEFS`. When disabled, the Tool Registry and `TOOL_DEFS`
  are exactly as today. The Router already reads `TOOL_DEFS` at call time.
  Tests must be able to enable it and restore the default registry.
- **Configuration errors.** Invalid `ROUTER_ENABLE_SHELL`, and (only when
  shell is enabled) invalid `ROUTER_SHELL_TIMEOUT_SECONDS` or
  `ROUTER_SHELL_MAX_OUTPUT_BYTES`, are printed by `main` as `Configuration
  error: ...` on stderr with exit status 1, like the existing workspace
  settings.
- **Tool Registry entry.** `shell` requires `command` (string, `minLength:
  1`), `additionalProperties: false`. Its description states it runs one
  command via bash in the Workspace Root, with no stdin, returns stdout,
  stderr and exit code, and requires the user's explicit confirmation.
- **Tool Confirmation variant.** The `confirm` seam and its callback
  signature are unchanged. For `shell` the label passed as "path" is the
  Workspace Root (so the header reads `shell: <workspace root>`) and the
  preview is the exact command string. The Terminal's confirm callback
  sanitizes it exactly as today and, for `shell` only, asks `Run this
  command? [y/N] `; `write`/`edit` keep `Apply this change? [y/N] `. Approval
  rules, piped behavior, EOF, spinner handling and `KeyboardInterrupt` are
  unchanged. Rejection and missing callback produce the existing rejection
  error result; nothing runs.
- **Call Log.** No new entry type. The existing Tool execution entry records
  the command and the result for run, rejected, timed-out and failed calls.
  `log_version` is unchanged; Resume is unaffected.
- **System Prompt.** Unchanged; the Tool description carries the contract.
- **README.** A `shell` subsection under Mutating Tools documents
  `ROUTER_ENABLE_SHELL` (default off, registration gate), the command
  confirmation, bash/sh, Workspace Root cwd, no stdin, inherited environment,
  no allowlist and no sandbox, non-zero exit as a normal result,
  `ROUTER_SHELL_TIMEOUT_SECONDS`, and `ROUTER_SHELL_MAX_OUTPUT_BYTES`.
  Ticket 03 adds: every call kills the command's process group when it
  ends, so background processes do not survive; a process that leaves the
  group (e.g. `setsid`) is not killed and, if it holds the output open, the
  call ends in a Tool error after a short bounded wait. Ticket 03 also fixes
  the pre-existing stale sentence in the README "## Tools" section ("two
  built-in Tools"; brief, Known issues) so it no longer states a fixed count
  that `write`, `edit`, the Workspace Tools and opt-in `shell` contradict.

## Testing Decisions

- Good tests assert external behavior only: Tool results, the tool results
  sent to the fake Provider, what the REPL prints, `TOOL_DEFS`, the Session's
  Call Log lines, files a command created in a temporary Workspace Root, and
  `main`'s exit status and stderr. No assertions on private helpers.
- Seams (existing; no new seam):
  - `execute_batch` with `ToolCall`s against a configured temporary workspace
    and a stub `confirm` callback, after the shell registration function has
    enabled `shell`: result shape, non-zero exit as a normal result, cwd is
    the Workspace Root, no stdin (a reading command gets EOF), pipes work,
    rejection/missing callback runs nothing (checked by a marker file not
    being created), missing shell binary fails before `confirm` (via a `PATH`
    without `bash`/`sh`), timeout error and that a background child is gone
    afterwards (use a small timeout), truncation marker, non-UTF-8 output.
  - `TOOL_DEFS` with and without enablement: `shell` present only when
    enabled, every other Tool unchanged.
  - `run_repl` with the Provider faked at `urlopen` via
    `install_fake_urlopen`, returning a `shell` Tool call: command shown and
    sanitized, `Run this command? [y/N]` asked, `y` runs, other answers and
    EOF reject, Call Log entry written.
  - `main` for `ROUTER_ENABLE_SHELL`, `ROUTER_SHELL_TIMEOUT_SECONDS` and
    `ROUTER_SHELL_MAX_OUTPUT_BYTES` configuration errors, and that the shell
    settings are ignored when shell is disabled.
- Ticket 03 uses the same `execute_batch` seam (no new seam): a command
  that backgrounds a child with its output redirected away from the pipes
  (e.g. `sleep 30 >/dev/null 2>&1 &`, recording `$!`) and exits 0 returns
  its normal result and the child is gone afterwards, including a
  SIGTERM-ignoring child; an ordinary command's result is unchanged and it
  returns well under the kill grace period; a command that starts a
  `setsid` process holding stdout open returns a Tool error within roughly
  timeout + grace + drain bound (the test must kill that escaped process
  itself in teardown, since the Tool deliberately does not). Existing
  ticket 02 timeout tests keep passing unchanged. `setsid` is from
  util-linux; a test depending on it may skip when it is not on `PATH`.
- Tests are offline and POSIX-only (they run real `bash`/`sh`), which
  matches the project's existing Linux test environment. Keep timeouts in
  tests to one or two seconds.
- Prior art: `tests/test_tools.py` (`execute_batch`, registry iteration),
  `tests/test_workspace_tools.py` (write/edit confirmation, `TOOL_DEFS`),
  `tests/test_repl.py` (Tool Confirmation, `tool>` lines, Call Log),
  `tests/test_main.py`, `tests/conftest.py`.

## Out of Scope

- Command allowlist or blocklist; sandboxing.
- A `cwd` argument; stdin support.
- Environment filtering.
- Registration toggles for any other Tool.
- A persistent "always allow" or per-session approval for commands.
- Returning partial output on timeout.
- Letting a backgrounded process deliberately survive a call (no parameter
  for it; brief decision 7).
- Killing or containing a process that left the process group (`setsid`,
  self-daemonizing); only the wait for it is bounded (brief decision 8).
- A new Call Log entry type.
- MCP; patches.

## Further Notes

- The brief says truncation uses "the same `[...truncated]` marker
  `read_file` already uses". In the current code `read_file` does not
  truncate: an over-limit file is a Tool error, and `list_files` /
  `search_text` signal truncation with a boolean `truncated` field. There is
  no existing marker to reuse, so this spec adopts the literal
  `[...truncated]` string the brief names, appended to the truncated text.
  `read_file` is not changed.
- "Default equal to `ROUTER_MAX_READ_BYTES`" is read as the effective value
  (the user's setting, or its 64 KiB default), not the constant.
- The strict `ROUTER_ENABLE_SHELL` parsing (`1`/`0`/empty only) is a planner
  mechanism choice: it fails closed on typos rather than guessing intent.
- Bounded capture (drain and discard past the cap) is a planner mechanism
  choice required so the cap protects memory, not only the Conversation.
- Ticket 03 is a post-approval correction: user story 24 already promised
  "nothing keeps running in the background after the Tool returned", but
  tickets 01-02 only killed the group on timeout. The round-2 review's
  `setsid` residual risk is resolved by decision 8's bound, not by
  containment.
- `docs/CONTEXT.md`'s glossary entry **Tool** still says Tools "neither
  execute arbitrary shell commands"; that line predates this feature and is
  the orchestrator's to update.
