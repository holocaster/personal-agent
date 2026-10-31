# 0015 - Persistent Memory

Brief: `docs/briefs/0015-persistent-memory.md`. Vocabulary (Memory Note,
Memory, System Prompt, Conversation Summary, Call Log, REPL Command) is in
`docs/CONTEXT.md`; scope and provenance are recorded there under "Memory
scope and provenance". No ADR: every decision here is either settled in the
brief and `docs/CONTEXT.md` or a local mechanism choice.

## Problem Statement

Everything the agent knows about the user lives in one Session's
Conversation. A fact, preference, or decision the user states ("answer in
metric units", "my main project is X", "we decided to use Postgres") is lost
as soon as a new Session starts, is dropped at the Context Window cut or by
`/clear`, and has to be repeated. There is no durable, user-controlled place
to keep such facts, and the user does not want the cost or risk of an LLM
deciding on its own what to remember.

## Solution

Three new REPL Commands manage a global Memory:

- `/remember <text>` records one Memory Note with the time it was added.
- `/memory` lists the current Memory Notes with a positional index (1, 2,
  3...).
- `/forget <index>` removes the Memory Note at that index.

Memory is one JSONL file per installation, at `ROUTER_MEMORY_PATH` or the
fixed default `~/.personal_agent/memory.jsonl`, the same no matter which
directory, Workspace Root, or Session the agent runs in. Whenever at least
one Memory Note exists, the System Prompt of every Provider exchange carries
the Memory, ahead of everything else it contains (and so ahead of the
Conversation Summary). When a `/remember` pushes total Memory content past
roughly 2000 characters, the REPL prints one warning; nothing is capped or
truncated. Memory operations are never written to the Call Log.

## User Stories

1. As a REPL user, I want to record a fact with `/remember <text>`, so that I do not have to repeat it in every Session.
2. As a REPL user, I want `/remember` to confirm the note was saved, so that I know it took effect.
3. As a REPL user, I want `/remember` with no text to print a local error and save nothing, so that I never create an empty Memory Note.
4. As a REPL user, I want the whole rest of the line after `/remember` kept as the note, spaces included, so that I can write a natural sentence.
5. As a REPL user, I want a multi-line `/remember` entered in the Input Box stored as one line, so that each Memory Note stays one entry in `/memory` and in the System Prompt.
6. As a REPL user, I want each Memory Note stored with the time it was added, so that the file shows when I wrote it.
7. As a REPL user, I want my Memory Notes sent to the model on every later routed turn of this Run, so that a note I just added already shapes the next answer.
8. As a REPL user, I want my Memory Notes sent to the model in every later Run and every new Session, so that they persist across Sessions.
9. As a REPL user, I want the same Memory whether I start the agent from my home directory, a project directory, or with a different `ROUTER_WORKSPACE`, so that Memory is about me, not the project.
10. As a REPL user, I want Memory to survive `/clear`, `/undo`, `/compress` and Resume unchanged, so that Conversation controls never touch my Memory.
11. As a REPL user, I want Memory placed in the System Prompt, not as a Conversation message, so that Provider role ordering and the Context Window are unaffected.
12. As a REPL user, I want Memory to appear ahead of everything else in the System Prompt, including a Conversation Summary, so that my standing facts frame the whole request.
13. As a REPL user, I want no Memory section at all in the System Prompt when I have no Memory Notes, so that an unused feature costs nothing.
14. As a REPL user, I want Memory carried on Tool follow-up exchanges and after Escalation too, so that every exchange of a turn sees the same facts.
15. As a REPL user, I want the `/compress` summary call to see my Memory too, so that the System Prompt means the same thing on every exchange.
16. As a REPL user, I want `/memory` to list every Memory Note in the order I added them, numbered from 1, so that I can see what the model is told and pick one to remove.
17. As a REPL user, I want `/memory` with no notes to say there are none, so that an empty list is not mistaken for an error.
18. As a REPL user, I want `/memory` to show note text safely even if it contains terminal control characters, so that listing Memory cannot garble my terminal.
19. As a REPL user, I want `/forget <index>` to remove the Memory Note at that position, so that I can drop a fact that is wrong or stale.
20. As a REPL user, I want `/forget` to tell me which note it removed, so that I can see I picked the right one.
21. As a REPL user, I want `/forget` with a missing, non-numeric, zero, negative, or out-of-range index, or with extra arguments, to print a local error and change nothing, so that a typo never deletes the wrong note.
22. As a REPL user, I want a removed Memory Note gone from the next routed turn's System Prompt and from every later Run, so that forgetting is immediate and durable.
23. As a REPL user, I want to re-run `/memory` after a `/forget` to see the renumbered list, so that I use current indices for the next removal.
24. As a REPL user, I want one warning when a `/remember` pushes total Memory past roughly 2000 characters, so that I know every request is getting larger.
25. As a REPL user, I want that warning not repeated on later `/remember`s while Memory stays over the threshold, and never printed at startup, so that it is not noise.
26. As a REPL user, I want nothing capped, truncated, or dropped automatically, so that only I decide what Memory contains.
27. As a Call Log reader, I want no Call Log entry for `/remember`, `/memory`, `/forget` or the warning, so that the Call Log stays a record of one Session and Memory's only record is its own file.
28. As a user, I want Memory in a plain JSONL file (one `{"text", "added"}` object per line), so that I can read, back up, or edit it by hand.
29. As a user, I want `ROUTER_MEMORY_PATH` to choose the Memory file, so that I can keep it somewhere else or use a separate Memory for experiments.
30. As a user, I want the default Memory file at `~/.personal_agent/memory.jsonl`, created with its directory on the first `/remember`, so that Memory works without any setup.
31. As a user, I want a missing Memory file treated as an empty Memory, so that a fresh install starts cleanly.
32. As a user, I want a malformed Memory file to stop startup with a clear configuration error naming the file, so that a hand edit gone wrong is never silently discarded or overwritten.
33. As a REPL user, I want a failed write (for example, no permission) to print a local error and leave Memory as it was, so that the REPL and the file never disagree.
34. As a user, I want no model or Tool able to write Memory, so that Memory has no ungoverned writes and no extra Attempt cost.
35. As a REPL user, I want `/help` to list `/remember`, `/memory` and `/forget`, so that I can discover them.
36. As a REPL user, I want Tab to complete the new commands in the Input Box, so that they are as quick to type as the others.
37. As a README reader, I want Memory, its commands, its file, `ROUTER_MEMORY_PATH`, and the warning documented, so that I can use it without reading the code.
38. As a developer, I want the test suite never to touch my real `~/.personal_agent/memory.jsonl`, so that running tests cannot change my Memory.

## Implementation Decisions

- **Memory module.** A new leaf module at the package root (per the Package
  organization decision in `docs/CONTEXT.md`) owns the Memory file: resolving
  its path, loading every Memory Note, appending one, and removing one by
  position. It knows nothing about the REPL or Providers. A Memory Note is
  its `text` and its `added` ISO-8601 UTC timestamp, in the same format as
  the Call Log's `timestamp`.
- **Path.** `ROUTER_MEMORY_PATH` names the exact file (unlike
  `ROUTER_LOG_PATH`, which is a base path). Unset or empty means the fixed
  default `~/.personal_agent/memory.jsonl`. `~` is expanded. The path is
  never resolved against the cwd or the Workspace Root by default (brief
  decision 4).
- **File format.** One JSON object per line, `{"text": ..., "added": ...}`,
  in the order added. Missing file means empty Memory. A line that is not a
  JSON object with string `text` and string `added` makes the file
  malformed; blank lines are ignored.
- **Writes.** `/remember` creates the parent directory if needed and appends
  one line. `/forget` rewrites the file without the removed note, writing a
  temporary file beside it and replacing the original, so a failure never
  leaves a half-written Memory. An OS error on either write is reported as a
  local REPL error and the REPL's Memory is unchanged.
- **Load and lifetime.** Memory is loaded once at startup, before the first
  prompt (fresh Run and Resume alike). A malformed file is reported by `main`
  as a configuration error naming the file, exit status 1, the same way other
  configuration errors are reported. During the Run the REPL holds the loaded
  Memory Notes and updates them only after a successful write, so the REPL
  and the file agree. Two concurrent Runs writing Memory are unsupported
  (last writer wins), matching the existing "two concurrent Runs" posture.
- **`/remember <text>`.** The note text is the input after the command name,
  with surrounding whitespace stripped and every internal run of line breaks
  collapsed to one space. Empty text is a local error. On success it confirms
  (`Remembered.`) and, if total Memory content (the sum of every note's
  `text` length) was at most 2000 characters before and is over 2000 after,
  prints one warning saying Memory is past about 2000 characters and is sent
  with every request. The rule is stateless: no flag is persisted, so the
  warning prints only on the crossing `/remember` and again only if Memory
  drops back under the threshold and crosses it again. It never prints at
  startup.
- **`/memory`.** No arguments. Prints each Memory Note as `<index>. <text>`,
  1-based, in stored order, text sanitized for control characters as
  `/history` does. With no notes prints `No Memory Notes.`. Timestamps are
  not shown.
- **`/forget <index>`.** Exactly one argument, a positive integer no larger
  than the number of notes; anything else (missing, extra, non-numeric, zero,
  negative, out of range) is a local error naming the valid range and
  changes nothing. On success prints `Forgot: <text>` (sanitized). Indices
  are positional against the current Memory, as `/memory` would show it now.
- **Command parsing.** `COMMANDS` gains `/remember`, `/memory`, `/forget`
  (feeding the unknown-command check and Input Box Tab completion);
  `HELP_TEXT` gains one line each. The generic "takes no arguments" rule
  keeps applying to every command except `/model`, `/remember` and
  `/forget`. `/remember` takes its text from the raw input line, not from
  whitespace-split arguments, so spacing inside the note is kept.
- **System Prompt.** Gains an optional Memory section, present only when at
  least one Memory Note exists, placed ahead of everything else in the
  prompt (before the role line, date line, Tool rules, language rule and
  Conversation Summary), per the System Prompt glossary entry. It carries a
  short heading saying these are facts the user asked to be remembered,
  then one line per note in stored order (`- <text>`), without timestamps.
  With no notes the System Prompt is exactly today's.
- **Router.** `route()` and `compress()` each gain an optional Memory Notes
  input, passed to every exchange they make (initial exchange, Tool
  follow-ups, Escalation, Compression). When absent, behavior and System
  Prompt are exactly today's. The Router never reads the Memory file itself;
  the REPL passes its current Memory Notes on each routed turn and each
  `/compress`.
- **Call Log.** No new entry type and no change to existing entries. Memory
  text reaches a Provider only through the System Prompt, which the Call Log
  does not record today, and this feature does not change that. `log_version`
  stays 2; Resume is unaffected.
- **No Tool.** The Tool Registry is unchanged; no Tool reads or writes
  Memory (brief, Out of scope).
- **Test isolation.** The autouse router-env isolation in the test suite
  clears `ROUTER_MEMORY_PATH` and points it at a per-test temporary file, so
  no test ever reads or writes the real default file.
- **README.** A Memory section documents `/remember`, `/memory`, `/forget`,
  the JSONL file and its default path, `ROUTER_MEMORY_PATH`, injection into
  the System Prompt, the 2000-character warning, that nothing is logged to
  the Call Log, and that Memory is global rather than per Session or
  Workspace Root. The REPL commands list and System Prompt paragraph mention
  it.

## Testing Decisions

- Good tests assert external behavior only: what the REPL prints, the
  contents of the Memory file, the System Prompt in the request body the
  fake Provider receives, the lines in the Session's Call Log file, and
  `main`'s exit status and stderr. No assertions on private helpers or module
  globals.
- Seams (existing, highest available; no new seam):
  - `run_repl` driven with an input stream and an output stream, the
    Provider faked at `urlopen` via `install_fake_urlopen`, and
    `ROUTER_MEMORY_PATH` pointed at a temporary file. Covers every command,
    the warning, persistence to the file, the System Prompt carrying (or not
    carrying) Memory on the next routed turn and on `/compress`, and the
    absence of Memory entries in the Call Log.
  - A second `run_repl` (fresh or with `resumed`) against the same Memory
    file for persistence across Runs and Sessions.
  - `main` with an explicit argument list for the malformed-file
    configuration error and for the default path resolving under the home
    directory (with `HOME` pointed at a temporary directory).
  - `route()` directly for Memory on Tool follow-ups and after Escalation,
    as the existing routing tests do.
  - `InputBox` with a pipe input for Tab completion of the new commands.
- Prior art: `tests/test_repl.py` (`/compress`, `/history`, System Prompt
  with Conversation Summary, Call Log assertions), `tests/test_routing.py`
  (System Prompt content, Escalation, Tool loop), `tests/test_main.py`
  (configuration errors, `--resume`), `tests/test_input_box.py` (Tab
  completion), `tests/conftest.py` (env isolation fixtures).

## Out of Scope

- LLM-curated memory: no model call decides what to remember or summarizes
  notes.
- A Tool for the model to read or write Memory.
- Autonomous skill creation or self-improving skills.
- Per-Workspace-Root or per-Session Memory.
- Entry-count or size caps, automatic truncation.
- Status Footer or `/history` surfacing of Memory.
- Editing a Memory Note in place (forget and remember again instead).
- Showing timestamps in `/memory` or the System Prompt.
- Safe concurrent writes from two Runs at once.

## Further Notes

- The brief says Memory goes "ahead of the Conversation Summary"; the System
  Prompt glossary entry says "ahead of everything else". Placing Memory
  first in the prompt satisfies both.
- "Roughly 2000 characters" is implemented as a strict `> 2000` on the sum
  of note text lengths; separators and headings are not counted.
- Because `/forget` indices are positional, removing several notes needs a
  `/memory` in between (brief decision 3).
