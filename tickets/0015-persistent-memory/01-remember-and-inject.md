# 01: Record Memory Notes with /remember and inject Memory into the System Prompt

**What to build:** The user types `/remember <text>` and the Memory Note is
appended to the global Memory file (`ROUTER_MEMORY_PATH`, default
`~/.personal_agent/memory.jsonl`). From the next routed turn of this Run, and
in every later Run and Session, every Provider exchange's System Prompt starts
with the Memory. A `/remember` that pushes Memory past 2000 characters prints
one warning. A malformed Memory file stops startup with a configuration
error. Nothing is written to the Call Log. `/help`, Tab completion and the
README cover `/remember` and Memory.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0015-persistent-memory.md` (Implementation Decisions:
Memory module, Path, File format, Writes, Load and lifetime, `/remember
<text>`, Command parsing, System Prompt, Router, Call Log, No Tool, Test
isolation, README; Testing Decisions); **ADRs:** none.

- [x] The test suite's autouse env isolation clears `ROUTER_MEMORY_PATH` and
  points it at a per-test temporary file; no test reads or writes the real
  default file.
- [x] A new leaf Memory module resolves the path (`ROUTER_MEMORY_PATH` as an
  exact file, `~` expanded; unset or empty means
  `~/.personal_agent/memory.jsonl`, never cwd- or Workspace-Root-relative),
  loads Memory Notes (missing file = empty, blank lines ignored), and appends
  one note as `{"text": ..., "added": ...}` with `added` in the Call Log's
  UTC timestamp format, creating the parent directory when needed.
- [x] Memory is loaded once at startup for a fresh Run and for Resume. A line
  that is not a JSON object with string `text` and string `added` makes
  `main` print a configuration error naming the file and exit 1.
- [x] `/remember <text>` stores the rest of the input line, whitespace
  stripped, line breaks collapsed to one space, internal spacing otherwise
  kept, prints `Remembered.`, and the REPL's Memory then includes it.
  `/remember` with no text prints a local error and writes nothing.
- [x] An OS error while writing prints a local error; the REPL's Memory and
  the file stay unchanged.
- [x] When total note text length goes from at most 2000 to over 2000 on a
  `/remember`, one warning is printed. It is not printed on later
  `/remember`s while Memory stays over 2000, nor at startup, and is never
  logged.
- [x] `route()` and `compress()` accept optional Memory Notes and pass them
  to every exchange (initial, Tool follow-ups, Escalation, Compression). With
  at least one note the System Prompt begins with a Memory section (a short
  heading, then `- <text>` per note in stored order, no timestamps), ahead of
  the role line, date line, Tool rules and Conversation Summary. With none,
  the System Prompt is exactly today's (existing tests still pass).
- [x] The REPL passes its current Memory to every routed turn and every
  `/compress`, so a note added mid-Run reaches the next turn's System Prompt.
- [x] A second `run_repl` (fresh and resumed) against the same Memory file
  sends the notes; `/clear`, `/undo` and `/compress` leave Memory unchanged.
- [x] No Call Log entry is written for `/remember` or the warning; no new
  entry type exists and `log_version` stays 2. No Tool reads or writes
  Memory.
- [x] `/help` lists `/remember`, Tab completes it in the Input Box, and the
  README documents Memory (global scope, file and default path,
  `ROUTER_MEMORY_PATH`, System Prompt injection, the warning, not logged).
- [x] Tests cover the above at the `run_repl`, `main`, `route()` and
  `InputBox` seams, including the default path resolving under a temporary
  `HOME`. Full offline suite passes.
