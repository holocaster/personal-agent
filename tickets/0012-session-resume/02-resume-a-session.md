# 02: Resume a Session with --resume

**What to build:** The user starts a new Run of an existing Session with
`--resume <session-id>` or `--resume last`. The REPL rebuilds the
Conversation from the `ok` Turn Ends after the last `conversation_cleared`,
prints `Resumed session <id>: N turns.`, writes `session_resumed`, and keeps
appending to the same Call Log file under the same Session Id. Any Resume
error prints one line to stderr and exits 1 before the REPL opens.

**Blocked by:** 01 (Record turn outcomes and clears in the Call Log).

**Spec:** `docs/specs/0012-session-resume.md` (all sections, notably
Implementation Decisions: Call Log module, Session Id validation, Resume
errors, Startup, REPL, Per-Run spend, Tier Config); **ADRs:** ADR-0005,
ADR-0003.

- [x] `main` parses one optional `--resume SESSION` with stdlib `argparse`
  and accepts an explicit argument list; existing `main` tests do not pick up
  pytest's argv. Starting without `--resume` behaves exactly as today.
- [x] `--resume <id>` loads the Session's Call Log: the Conversation is the
  ordered turns from `ok` Turn End `messages` after the last
  `conversation_cleared`; `error` and `interrupted` Turn Ends, Attempts with
  no Turn End, `session_resumed` and `session_end` entries contribute nothing.
- [x] `--resume last` resumes the highest Session Id among Call Log files in
  the configured base path's directory that match the base path's naming.
- [x] The REPL prints `Resumed session <id>: N turns.` (N = restored turns)
  before the first input, `/history` shows the restored turns, and the next
  routed turn sends the restored turns within the existing Context Window
  rule.
- [x] The Run appends to the same Call Log file under the same Session Id: a
  `session_resumed` entry with the current Tier Config `tiers`, then the
  Run's entries, then `session_end`. No new Session Id or file is created.
- [x] Spend resets per Run: the Status Footer and `session_end.total_cost`
  count only this Run; the Budget Guardrail starts fresh.
- [x] Resume errors print one line to stderr and exit 1 before the Input Box
  or REPL starts, and write nothing to any Call Log: unknown Session Id
  (missing file, or a value without the Session Id shape, which is never used
  to build a path), `last` with no Session files, a Call Log without
  `log_version: 2`, and a Call Log line that is not valid JSON.
- [x] A resumed Session can be resumed again with the same result plus the
  newer turns.
- [x] Tests build resumable logs by running a real first Run through
  `run_repl` (legacy and malformed logs may be written directly), and cover
  the behaviors above at the `run_repl` and `main` seams. Full offline suite
  passes.
