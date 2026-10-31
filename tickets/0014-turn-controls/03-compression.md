# 03: Compress the Conversation with /compress

**What to build:** `/compress` asks the easy tier for a Conversation Summary
of the previous summary plus every turn except the two most recent, then
replaces those turns with the summary. The summary travels in the System
Prompt of every later exchange, `/history` shows it first, `/clear` drops it,
and a `conversation_compressed` entry lets a Resume rebuild the same
Conversation. `/help`, Tab completion and the README cover `/compress`.

**Blocked by:** 02 (Undo and Retry the last turn) - the Resume replay extends
the `turn_undone` step, and `/retry` must treat a compressed-away turn as
already removed.

**Spec:** `docs/specs/0014-turn-controls.md` (Implementation Decisions:
Compression call, `/compress` command, System Prompt, `/history`, `/clear`,
Resume rule, Commands list, README; Further Notes); **ADRs:** ADR-0001,
ADR-0005.

- [x] With two or fewer turns, `/compress` prints a local error and makes no
  Provider call.
- [x] Otherwise it makes the summary call to the easy tier's Provider and
  model: no Tools advertised, local retries on retryable failures, no
  Escalation, no Turn End; each Attempt is logged as a normal `attempt` entry
  with `task` `/compress`, and its cost counts toward the Budget Guardrail and
  the Status Footer spend. The request is one user message holding the
  instruction, the previous summary if any, and the replaced turns as plain
  text (all of them, not only those inside the Context Window).
- [x] On success the Conversation becomes the new summary plus the two most
  recent turns, a `conversation_compressed` entry carrying `summary` is
  written, and the REPL confirms how many turns were compressed.
- [x] On failure (error or empty answer) the Conversation and summary are
  unchanged, no `conversation_compressed` entry is written, and the error is
  shown.
- [x] Every later exchange's System Prompt (including Tool follow-ups and
  Escalation) carries the summary; it is never added as a message. With no
  summary the System Prompt is unchanged.
- [x] A second `/compress` includes the previous summary in its input and
  replaces it.
- [x] `/history` prints `summary: <text>` (sanitized) before the remaining
  turns; with only a summary, only that line.
- [x] `/clear` drops the summary as well as the turns. `/undo` after
  `/compress` removes the newest kept turn, never the summary. `/retry` of a
  turn compressed away routes the task without Undoing anything.
- [x] Resume replays the Call Log in order (clear, `ok` Turn End, `turn_undone`,
  `conversation_compressed` keeps the two most recent remaining turns and sets
  the summary), and the resumed Run's System Prompt and `/history` carry the
  summary. `log_version` stays 2; the `Resumed session <id>: N turns.` line
  counts turns only.
- [x] `/help` lists `/compress`, Tab completes it, and the README documents it
  and the `conversation_compressed` entry.
- [x] Tests cover the above at the `run_repl` seam (fake Provider request
  bodies, Call Log lines, Resume via a real first Run), `main --resume`, and
  `InputBox`. Full offline suite passes.
