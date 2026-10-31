# 02: Undo and Retry the last turn

**What to build:** `/undo` removes the most recent successful turn from the
Conversation and records a `turn_undone` entry, so a Resume does not bring it
back. `/retry` re-sends the most recent routed task of the Run: if that turn
succeeded and is still the last turn, it is first Undone; otherwise the task
is simply sent again. The re-sent task is a normal routed turn that honors
the Tier Pin. `/help`, Tab completion and the README cover both commands.

**Blocked by:** 01 (Pin a Complexity Tier with /model) - `/retry` must honor
the Tier Pin.

**Spec:** `docs/specs/0014-turn-controls.md` (Implementation Decisions: Undo,
Retry, Resume rule (`turn_undone` step), Commands list, README; Further
Notes); **ADRs:** ADR-0005.

- [x] `/undo` removes the last turn of the Conversation, writes a
  `turn_undone` entry (`type`, `timestamp`, `session_id` only) and confirms;
  the next routed turn no longer sends it and `/history` no longer shows it.
  The original Turn End stays in the Call Log.
- [x] Repeated `/undo` removes one more turn each time; with no turn left it
  prints a local error and writes nothing.
- [x] `/retry` with no routed task yet in this Run (including right after a
  Resume) prints a local error and sends nothing.
- [x] `/retry` after an `ok` turn that is still the last turn writes one
  `turn_undone`, then routes the same task as a normal turn (spinner, Tool
  lines, Turn End, output, footer); the Conversation holds the task once.
- [x] `/retry` after an `error` or `interrupted` turn, or after an `ok` turn
  already removed by `/undo` or `/clear`, routes the task without Undoing
  anything.
- [x] `/retry` runs the Classifier again when no Tier Pin is set and starts at
  the pinned tier when one is.
- [x] If the re-sent turn fails, the Undone turn stays undone.
- [x] Resume applies each `turn_undone` in log order, removing the most recent
  remaining turn (no-op when none), so a resumed Conversation equals the live
  one; logs without `turn_undone` resume exactly as before.
- [x] `/help` lists `/undo` and `/retry`, Tab completes them, and the README
  documents them and the `turn_undone` entry.
- [x] Tests cover the above at the `run_repl` seam (Resume via a real first
  Run plus `call_log.reset_session`) and `InputBox`. Full offline suite passes.
