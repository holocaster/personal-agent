# 01: Record turn outcomes and clears in the Call Log

**What to build:** Every Call Log written by the REPL is a complete, versioned
record of the Conversation. `session_start` declares `log_version: 2`; every
routed turn ends with a Turn End entry stating its outcome (and, when `ok`,
exactly the messages that entered the Conversation); every `/clear` writes a
`conversation_cleared` entry. Nothing reads these back yet; a reader can
already see each turn's outcome without inferring it from Attempts.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0012-session-resume.md` (Implementation Decisions: Call
Log format version, Turn End entry, Conversation clear entry, Call Log module;
Testing Decisions); **ADRs:** ADR-0005, ADR-0003.

- [x] `session_start` includes `log_version: 2`; its other fields are unchanged.
- [x] A successful routed turn writes `type: "turn_end"`, `status: "ok"` and
  `messages` equal to the turn's messages the REPL appends to the
  Conversation (user message, assistant Tool requests, Tool results, final
  answer), after that turn's Attempt and Tool execution entries.
- [x] A failed routed turn (including a Budget Guardrail block) writes
  `status: "error"` with `error` holding the Router result's error text.
- [x] A routed turn interrupted with Ctrl+C writes `status: "interrupted"`
  with no messages or error.
- [x] REPL Commands, exit words and blank lines write no Turn End.
- [x] `/clear` writes `type: "conversation_cleared"`; `/clear` output and
  behavior are otherwise unchanged.
- [x] Every new entry carries `timestamp` and `session_id` like existing
  entries, and the Call Log module owns writing them.
- [x] Tests at the `run_repl` seam with the fake Provider cover each status,
  a Tool-using `ok` turn, `/clear`, and the full line order of a mixed Run;
  existing line-order assertions are updated for the new entries. Full
  offline suite passes.
