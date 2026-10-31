status: approved
ticket: [tickets/0018-shell-tool/01-opt-in-shell-with-confirmation.md, tickets/0018-shell-tool/02-timeout-and-output-cap.md]
reviewed_range: 9e73f2dd1bd11e46130a81f8d06563f3d7f83142..ec343caf346d26c073985e9eb126d036b3394344

## Round 2 (approved)

Both round-1 blocking findings fixed and independently reproduced by the reviewer:
`sleep 1000 & echo hi` and `(trap '' TERM; sleep 1000) & echo hi` (and several
variants) now time out and clean up within timeout+grace instead of hanging.
`apply_shell` bounds the whole apply step (wait + both drain joins) by the
timeout deadline; `_kill_process_group` SIGKILLs the whole group
unconditionally after the grace period. `uv run pytest -q`: 602 passed.

One `suggestion`-severity residual: a command that detaches from the process
group (`setsid`, or a self-daemonizing process) and keeps the pipes open can
still block the final join unboundedly - out of the "no sandbox" scope
accepted in round 1, optionally worth a README note. Not a blocker.

Round-1 findings below are kept for history.


criteria:
  - criterion: "01: ROUTER_ENABLE_SHELL strict parsing (1 / unset|empty|0 / else Configuration error, exit 1), read after .env"
    result: pass
  - criterion: "01: registration only via explicit startup function called by main; disabled registry/TOOL_DEFS identical; schema; tests can restore"
    result: pass
  - criterion: "01: two-phase Mutating Tool; bash else sh resolved in prepare, error before confirm; write/edit unchanged"
    result: pass
  - criterion: "01: argv [shell,-c,cmd], cwd Workspace Root, stdin DEVNULL, inherited env, own session; pipes/redirects/&&"
    result: pass
  - criterion: "01: {stdout,stderr,exit_code} non-error for any exit code; UTF-8 replace; start failure is Tool error"
    result: pass
  - criterion: "01: Tool Confirmation header/preview/question; only y/yes runs; reject/EOF/no callback run nothing; Ctrl-C interrupts"
    result: pass
  - criterion: "01: existing Call Log entry and tool> line for run/rejected/failed"
    result: pass
  - criterion: "01: README shell subsection"
    result: pass
  - criterion: "01: tests at execute_batch/TOOL_DEFS/run_repl/main seams; full suite passes"
    result: pass
  - criterion: "02: ROUTER_SHELL_TIMEOUT_SECONDS / ROUTER_SHELL_MAX_OUTPUT_BYTES parsing, default to effective read limit, errors only when enabled"
    result: pass
  - criterion: "02: on timeout SIGTERM the group, SIGKILL after grace if still alive; background child does not survive; Tool error, no partial output"
    result: fail
  - criterion: "02 (What to build): a shell command can no longer hang a turn"
    result: fail
  - criterion: "02: stdout/stderr drained concurrently, capped independently, excess discarded; [...truncated] marker; read_file unchanged"
    result: pass
  - criterion: "02: timed-out calls produce existing Call Log entry and tool> line"
    result: pass
  - criterion: "02: README documents both settings, SIGTERM-then-SIGKILL, marker"
    result: pass
  - criterion: "02: tests with short timeouts; full offline suite passes"
    result: pass

findings:
  - severity: blocking
    location: src/personal_agent/tools/shell.py apply_shell (process.wait(timeout=...) then unbounded stdout_thread.join()/stderr_thread.join())
    impact: >
      The timeout only bounds the lifetime of the direct bash child, not the turn.
      Any command that backgrounds a process which inherits stdout or stderr (e.g.
      `server &`, `yes >/dev/null &`, `sleep 1000 & echo hi`) makes bash exit at
      once, process.wait returns with timed_out=False, and the drain-thread joins
      then block until that background process closes the pipe - possibly forever.
      The REPL turn hangs with no timeout, which is exactly what ticket 02 says
      must not happen, and the leftover process keeps running in the user's
      session.
    evidence: >
      With ROUTER_SHELL_TIMEOUT_SECONDS=1, apply_shell(prepare_shell({"command":
      "sleep 8 & echo hi"})) returned {'stdout':'hi\n','stderr':'','exit_code':0}
      after 8.0s elapsed. With `sleep 1000 &` it would block for 1000s. No
      existing test covers a backgrounded child with inherited stdout/stderr.
    required_change: >
      Bound the whole apply step, including draining, by the timeout deadline -
      e.g. join the drain threads with the remaining deadline. If still alive at
      the deadline, or the leader exited but the pipes are still held open, treat
      it as a timeout: killpg SIGTERM, then SIGKILL, then join. Add an
      execute_batch test using `sleep 30 &`-style backgrounding with inherited
      stdout and a 1s timeout, asserting the call returns within ~timeout+grace.
  - severity: blocking
    location: src/personal_agent/tools/shell.py _kill_process_group
    impact: >
      SIGKILL escalation depends only on whether the group leader (bash) is still
      alive, not the whole process group. If bash dies on SIGTERM but a group
      member ignores or handles SIGTERM, SIGKILL is never sent. That member
      survives the timeout, and because it holds the pipes, apply_shell blocks in
      join() until it exits on its own - again leaving the turn unbounded.
    evidence: >
      Command `(trap '' TERM; sleep 12) & sleep 30` with a 1s timeout returned
      "command timed out after 1 seconds" only after 12.0s. The TERM-immune sleep
      survived the SIGTERM, was never SIGKILLed, and the join waited for it to
      finish naturally.
    required_change: >
      After the grace period, check the group, not the leader (e.g.
      os.killpg(pgid, 0) succeeding, or send SIGKILL to the group unconditionally
      and ignore ProcessLookupError). Then reap the leader and join the drains.
      Add a test with a SIGTERM-ignoring background child that asserts it is gone
      and the call returns within ~timeout+grace.
  - severity: suggestion
    location: "tests/test_main.py test_main_configures_shell_timeout_and_output_cap_from_* (asserts shell_tool._shell_config)"
    impact: >
      Asserts private module state, which the spec's Testing Decisions exclude
      ("No assertions on private helpers"). Brittle to refactoring but otherwise
      correct.
    evidence: "assert shell_tool._shell_config == shell_tool.ShellConfig(timeout_seconds=30, max_output_bytes=2048)"
    required_change: "Optional. Verify through behavior instead, e.g. main-configured cap/timeout observed via an execute_batch result."

checks:
  - "uv run pytest -q: 600 passed in 12.58s"
  - "Manual probe via apply_shell with 1s timeout: 'sleep 8 & echo hi' took 8.0s and returned a normal result (finding 1)"
  - "Manual probe: \"(trap '' TERM; sleep 12) & sleep 30\" with 1s timeout took 12.0s before returning the timeout error (finding 2)"
  - "Security gate review: shell entry is added to _REGISTRY only by enable_shell_tool(), called only from main after exact '1' check; import-time registry is unchanged; router reads tools_module.TOOL_DEFS at call time; execute_batch rejects unknown 'shell' when not registered; _execute_mutating calls confirm before apply and treats confirm=None as rejection - no bypass path found"
  - "Memory bound: _drain_capped keeps at most cap bytes per stream and discards the rest per 64 KiB chunk; confirmed by code and the `yes` flood test"
  - "Working tree clean after checks; probe script lived in the scratchpad; no leftover probe processes"

residual_risks:
  - "Standards axis: no hard violations found. parse_positive_int generalization of the former _parse_positive_byte_count is justified reuse."
  - "Ctrl-C-at-question for shell is not separately tested; relies on the unchanged generic confirm path, which existing tests cover."
  - "A command that escapes the process group (setsid/nohup + setsid) can still hold pipes even after the deadline-bounded join fix. Acceptable given the spec's 'no sandbox' scope, worth a README note."
  - "docs/CONTEXT.md glossary 'Tool' line already updated by the orchestrator before this round (commit d2f48c1) - the reviewer's copy predates that; no action needed."
