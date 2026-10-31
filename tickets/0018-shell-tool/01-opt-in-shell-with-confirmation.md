# 01: Opt-in `shell` Mutating Tool behind command Tool Confirmation

**What to build:** With `ROUTER_ENABLE_SHELL=1`, the model can call
`shell(command)`; the REPL shows the exact command in a Tool Confirmation
(`Run this command? [y/N] `), and on approval the command runs through
`bash -c` (`sh -c` fallback) in the Workspace Root with no stdin and the
inherited environment, returning `{stdout, stderr, exit_code}` - a non-zero
exit code is a normal result. Without the opt-in, `shell` is never in the
Tool Registry or `TOOL_DEFS`, and nothing else about the Tools changes.
Timeout and output capping come in ticket 02.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0018-shell-tool.md` (Implementation Decisions: Tools
module, Two-phase Mutating Tool reused, Execution, Result, Opt-in
registration, Configuration errors, Tool Registry entry, Tool Confirmation
variant, Call Log, System Prompt, README; Testing Decisions); builds on the
Mutating Tool mechanism of `docs/specs/0016-write-tools.md`. **ADRs:** none.

- [x] `ROUTER_ENABLE_SHELL`: exactly `1` enables; unset, empty or `0`
  disables; any other value makes `main` print `Configuration error: ...` to
  stderr and exit 1. Read after `.env` loading, so a `.env` value works.
- [x] Registration happens through one explicit Tool Registry startup
  function called by `main`, never at import. Disabled: Tool Registry and
  `TOOL_DEFS` identical to today. Enabled: `shell` added (schema: required
  `command` string `minLength: 1`, `additionalProperties: false`; description
  per spec) and advertised in `TOOL_DEFS`; every other Tool unchanged. Tests
  can enable it and restore the default registry.
- [x] `shell` is a Mutating Tool using the existing prepare / `confirm` /
  apply flow. Prepare resolves `bash` on `PATH`, else `sh`; neither is a Tool
  error returned before `confirm` is called. `write`/`edit` behavior is
  unchanged.
- [x] Apply runs `[<shell>, "-c", command]` with cwd the Workspace Root,
  stdin `DEVNULL`, the environment inherited unfiltered, in its own process
  group/session. Pipes, redirects and `&&` work.
- [x] A completed command returns `{"stdout", "stderr", "exit_code"}` as a
  non-error Tool result for any exit code; output decoded as UTF-8 with
  replacement characters. A failure to start the process is a Tool error.
- [x] Tool Confirmation for `shell`: header `shell: <workspace root>`, the
  exact command as preview (control characters sanitized as today), question
  `Run this command? [y/N] `; `write`/`edit` keep `Apply this change? [y/N] `.
  Only `y`/`yes` runs it; other answers, EOF in piped mode, or no `confirm`
  callback return the existing rejection error and run nothing; Ctrl-C at
  the question interrupts the turn without running it.
- [x] Run, rejected and failed `shell` calls produce the existing Tool
  execution Call Log entry and `tool>` line; no new Call Log entry type.
- [x] README Mutating Tools section documents `shell`: `ROUTER_ENABLE_SHELL`
  (default off, registration gate), command confirmation, bash/sh, Workspace
  Root cwd, no stdin, inherited environment, no allowlist and no sandbox,
  non-zero exit as a normal result.
- [x] Tests at the `execute_batch`, `TOOL_DEFS`, `run_repl` (fake Provider
  via `install_fake_urlopen`) and `main` seams cover the above, including a
  marker file not created on rejection. Full offline suite passes.
