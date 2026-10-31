status: approved
ticket: tickets/0018-shell-tool/03-always-clean-shell.md
reviewed_range: 6d032118aaf33719ba38c0999e8f918e6b7503e9..a6a2f5d9e4ec4088f21769f2f8edc0fafe2d07ac

criteria:
  - criterion: "On normal completion the group gets SIGTERM, then the grace period, then SIGKILL, before the result is returned. Result shape and exit code are unchanged. A redirected background child, including a TERM-immune one, is gone."
    result: pass
  - criterion: "The kill tolerates an already-empty group: no ProcessLookupError and no grace wait, so an ordinary command sees no added latency."
    result: pass
  - criterion: "Both post-kill joins share one deadline, DRAIN_JOIN_TIMEOUT_SECONDS=2. When it expires the call returns the specified Tool error and the escaped process is not signalled."
    result: pass
  - criterion: "Drain threads are daemon threads. Pipes are not closed while a drain may still be reading, and are closed as before when the drains finished."
    result: pass
  - criterion: "The Call Log and tool> line handle the new error the same way as any other Tool error, with no new entry type."
    result: pass
  - criterion: "The README shell subsection covers always-clean and the setsid escape. The '## Tools' section no longer says 'two built-in Tools'."
    result: pass
  - criterion: "Tests (a)-(d) are at the execute_batch seam. (d) is skipped without setsid and kills the escaped pid in teardown."
    result: pass
  - criterion: "Existing 01/02 tests are unchanged and the full offline suite passes."
    result: pass

findings:
  - severity: suggestion
    location: src/personal_agent/tools/shell.py (module constant, _kill_process_group, apply_shell)
    impact: >
      Comments cited ticket numbers ("ticket 03") that will go stale, and were
      longer than the CLAUDE.md "no comments unless really necessary" rule
      prefers. Not a regression (the file already had similar comments), and
      not blocking.
    evidence: "Comment blocks like '# Always-clean lifecycle (ticket 03): ...'"
    required_change: "Applied by the orchestrator directly after approval: trimmed to the non-obvious reasons (close-blocks-on-reader-lock hazard, zombie reap) and dropped ticket references. Full suite re-run after the edit: 606 passed."

checks:
  - "uv run pytest -q: 606 passed in 24.2s (reviewer's run)"
  - "uv run pytest -q: 606 passed in 23.24s (orchestrator's re-run after trimming comments)"
  - "Independent repro of all four scenarios (redirected bg child, TERM-immune bg child, ordinary-command latency, setsid escape) by the reviewer - see full transcript in the round's handoff message"
  - "Interpreter-exit check: an abandoned daemon drain still blocked in read() does not hang process exit"

residual_risks:
  - "A theoretical pgid-reuse race on an already-empty group (negligible; already true on the pre-existing timeout path)."
  - "A background child that exits just before the kill and is reaped slowly (e.g. some containers) could make the group poll wait up to KILL_GRACE_SECONDS; observed 50ms on this host."
  - "Everything else from round-2 review (0018-shell-tool/01-02-batch.review.md) is now resolved by this ticket - no remaining known issues for this feature."
