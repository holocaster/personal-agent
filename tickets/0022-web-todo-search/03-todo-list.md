# 03: todo Tool and a Todo List that follows the Conversation

**What to build:** The model can call `todo(todos)` to replace its Todo List
(items `{content, status}`), with no Tool Confirmation. The REPL prints a
compact checklist after each successful update. While any item is `pending`
or `in_progress`, the list is sent at the end of the System Prompt, including
on the next exchange of the same turn. The list follows the Conversation:
`/undo` and `/retry` restore it to before the removed turn, `/clear` empties
it, a failed or interrupted turn leaves it unchanged, Compression (manual or
Auto-Compress) keeps it, and Resume rebuilds it from the Call Log.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0022-web-todo-search.md` (Requirements R13-R18, R19 for
`todo` and the always-offered Tool list; Implementation Decisions: new `todo`
module, Router, Terminal (REPL), Call Log; Testing Decisions: Seam 2);
**ADRs:** none.

- [x] R13: `todo` registered by default, no confirmation; schema per R13
  (empty array valid; unknown status, missing or extra field is the normal
  "invalid arguments" error); success returns `{"todos": <list>}`;
  description covers 3+ step tasks, whole-list replacement, and at most one
  `in_progress`.
- [x] R14: the current Todo List is the `todos` of the latest successful
  `todo` result in the Conversation's turns, else the Todo baseline (empty
  at start); error results and updates in a failed or interrupted turn never
  persist.
- [x] R15: with at least one `pending`/`in_progress` item the System Prompt
  ends with a `Todo List:` block, one `- [<status>] <content>` line per item
  in order; no block when empty or all finished; never in the Compression
  call.
- [x] R16: each exchange of a turn sees the list as updated by earlier Tool
  rounds in that turn (last successful `todo` in a batch wins).
- [x] R17: a successful `todo` prints `tool> todo` then one line per item
  with `[ ]`/`[~]`/`[x]`/`[-]` markers, sanitized and cut to 120 chars, or
  `tool> todo (empty)`; existing color/piped rules; failures use the generic
  error line.
- [x] R18: `/undo` and `/retry` restore the pre-turn list; `/clear` empties
  turns and baseline; Compression sets the baseline from the dropped turns
  and previous baseline so the current list is unchanged and a later
  `/undo` of a kept turn is still correct; `load_conversation` returns the
  Todo baseline from the same replay and `main` passes it to the REPL; no
  new Call Log entry type or field.
- [x] R19 (part): `README.md` documents `todo`, the checklist and the Todo
  List lifecycle, and the Tools section's always-offered list includes the
  new default Tools.
- [x] Tests through `route`/`run_repl` with `install_fake_urlopen`: System
  Prompt block present after a `todo` call on the next exchange of the same
  turn and on later turns, absent when all finished or empty, absent from
  the Compression call; checklist output; list after `/undo`, `/retry`,
  `/clear`, a failed turn, `/compress` followed by `/undo` of a kept turn,
  and after Resume (including across a compression). Schema errors at the
  `tools.execute_batch` seam. Existing `load_conversation` callers updated.
  Full offline suite passes.
