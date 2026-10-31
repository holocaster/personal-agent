# 03: Always-clean `shell` with a bounded final drain

**What to build:** A `shell` call never leaves anything running and never
hangs. When a call ends - normal completion (any exit code) or timeout - the
command's whole process group is killed, so a process it backgrounded with
its output redirected away (e.g. `nohup server >/dev/null 2>&1 &`) no longer
survives the Tool result. A process that escaped the group with `setsid` and
still holds the output pipes open cannot be killed (no sandbox), but the
call now returns a Tool error after a short fixed wait instead of blocking
forever. An ordinary command that backgrounds nothing returns the same
`{stdout, stderr, exit_code}` in the same time as today. The stale "two
built-in Tools" sentence in the README "## Tools" section is fixed.

**Blocked by:** 02 (`shell` timeout and bounded output cap) - changes its
apply step and process-group kill.

**Spec:** `docs/specs/0018-shell-tool.md` (Solution; User Stories 24,
40-44; Implementation Decisions: Always-clean process lifecycle, Bounded
final drain, README; Testing Decisions: ticket 03 bullet; Out of Scope).
Brief: `docs/briefs/0018-shell-tool.md` settled decisions 7 and 8.
**ADRs:** none.

Ticket decisions (planner, implementation-level):
- The final-drain bound is a new fixed module constant next to
  `KILL_GRACE_SECONDS`, named `DRAIN_JOIN_TIMEOUT_SECONDS`, value `2`, not
  configurable. It is one shared deadline for both drain joins, not 2s each.
- The ticket-02 rule is kept: if the leader exits but a group member still
  holds the pipes at the command deadline, the call is still the existing
  timeout error (existing ticket-02 tests stay unchanged). Ticket 03 only
  adds a kill on the normal path and a bound on the post-kill joins.
- Error on drain-bound expiry: `command timed out after N seconds; a process
  that left the process group may still be running` (N is the configured
  timeout).

- [x] On a normal completion the process group is killed (SIGTERM, grace,
  SIGKILL, as on timeout) before the result is returned; the result shape
  and exit code are unchanged. A child backgrounded with output redirected
  away from the pipes - including one that ignores SIGTERM - is gone after
  the call returns.
- [x] The group kill tolerates an already-empty group (no
  `ProcessLookupError` escapes, no grace-period wait), so a command that
  backgrounds nothing returns the same result with no added latency. This
  also covers the timeout path when every remaining pipe holder has left
  the group.
- [x] After the kill, both drain-thread joins together are bounded by
  `DRAIN_JOIN_TIMEOUT_SECONDS`. If a drain is still running at expiry the
  call returns the Tool error above; the escaped process is not signalled.
- [x] Abandoned drain threads are daemon threads, and their pipe objects are
  not closed from the calling thread while they are still reading (closing
  a buffered pipe blocks on the reader's lock until the read returns -
  verified by the planner; that would reintroduce the hang). Pipes are
  closed as today when the drains finished.
- [x] The Call Log Tool execution entry and `tool>` line appear for the new
  error exactly as for any Tool error; no new entry type.
- [x] README `shell` subsection states that every call kills the command's
  process group when it ends (background processes do not survive), and
  that a process which leaves the group (e.g. `setsid`) is not killed and,
  if it holds the output open, the call ends in a Tool error after a short
  bounded wait. README "## Tools" section no longer claims a fixed "two
  built-in Tools"; it names `calculator`/`current_time` without implying
  they are the only Tools offered (pointing to Workspace Tools and Mutating
  Tools sections).
- [x] Tests at the `execute_batch` seam, 1-2s timeouts, no private-helper
  assertions: (a) `sleep 30 >/dev/null 2>&1 & echo $! > child.pid; echo hi`
  returns `{stdout: "hi\n", stderr: "", exit_code: 0}` and the child pid is
  gone; (b) same with a SIGTERM-ignoring child
  (`(trap '' TERM; sleep 30) >/dev/null 2>&1 & ...`) - child gone; (c) a
  plain `echo hi` returns its result in well under `KILL_GRACE_SECONDS`;
  (d) `setsid sleep 30 & echo $! > child.pid; echo hi` (the setsid'd sleep
  inherits stdout) with a 1s timeout returns the drain-bound Tool error in
  under ~timeout + grace + drain bound + slack, and the test kills the
  escaped pid itself in teardown; skip (d) when `setsid` is not on `PATH`.
  Reviewer repro commands from `01-02-batch.review.md` round 2 are a
  starting point.
- [x] Existing ticket 01/02 tests pass unchanged. Full offline suite passes.
