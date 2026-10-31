# 02: List Memory with /memory and remove a Memory Note with /forget

**What to build:** The user types `/memory` to see every Memory Note with a
1-based positional index, and `/forget <index>` to remove the note at that
position from the Memory file. The removed note is gone from the next routed
turn's System Prompt and from every later Run. `/help`, Tab completion and the
README cover both commands.

**Blocked by:** 01 (Record Memory Notes with /remember and inject Memory into
the System Prompt).

**Spec:** `docs/specs/0015-persistent-memory.md` (Implementation Decisions:
Writes, `/memory`, `/forget <index>`, Command parsing, Call Log, README;
Testing Decisions); **ADRs:** none.

- [x] `/memory` (no arguments) prints each note as `<index>. <text>`, 1-based,
  in stored order, text sanitized for control characters as `/history` does,
  no timestamps. With no notes it prints `No Memory Notes.`. Arguments give
  the standard "takes no arguments" error.
- [x] `/forget <index>` with a positive integer within range removes that
  note, prints `Forgot: <text>` (sanitized), and the REPL's Memory no longer
  includes it; a following `/memory` shows the renumbered list.
- [x] The Memory module removes a note by rewriting the file through a
  temporary file beside it that replaces the original; remaining notes keep
  their `text`, `added` and order.
- [x] A missing, extra, non-numeric, zero, negative or out-of-range argument
  prints a local error naming the valid range, and neither the REPL's Memory
  nor the file changes. An OS error while rewriting prints a local error and
  changes nothing.
- [x] After `/forget`, the next routed turn's System Prompt no longer carries
  the note (and has no Memory section when none remain); a later `run_repl`
  against the same file does not send it.
- [x] No Call Log entry is written for `/memory` or `/forget`.
- [x] `/help` lists `/memory` and `/forget`, Tab completes both in the Input
  Box, and the README's Memory section documents them, including re-running
  `/memory` between removals.
- [x] Tests cover the above at the `run_repl` and `InputBox` seams. Full
  offline suite passes.
