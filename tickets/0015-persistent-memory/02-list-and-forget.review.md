status: approved
ticket: 0015-persistent-memory/02-list-and-forget
reviewed_range: c85eaad1bd4b84b755efe4b7ce022bed993515f1..fd8e2735676e5cde6eb5284a5bec220da5f93509
note: important finding below fixed post-review (no round-2 doc); verified 2026-09-24 - memory.py forget() now takes notes as authoritative and never re-reads the file, matching the required change.

## Findings

### important - memory.py forget() re-reads the file instead of acting on the REPL's current Memory

Location: `src/personal_agent/memory.py` `forget()` (re-loads the file);
`src/personal_agent/terminal/repl.py` `_handle_forget` (validates the index
against the REPL's in-memory notes, but delegates removal to `forget()`,
which reloads from disk and removes by position there).

`/forget` validates the index against the REPL's in-memory notes list, but
`memory.forget()` re-reads the file and removes by position in *that* read.
If the file changed after startup (the spec explicitly allows hand-editing
it), three things go wrong:

1. The note removed from the file can differ from the one popped from the
   REPL's notes - the REPL and file then disagree, breaking the spec rule
   that they "agree" after a successful write. The user sees `"Forgot: X"`
   while `X` is still sent in every System Prompt for the rest of the Run.
2. If the file is now malformed, `load()` raises `ValueError`, uncaught -
   kills the REPL mid-session.
3. If the file now has fewer notes than the REPL's copy, `forget()` raises
   `IndexError`, uncaught - also kills the REPL mid-session.

Spec requires indices to be "positional against the current Memory, as
`/memory` would show it now" - `/memory` renders the REPL's notes, not the
file's.

Evidence: scratch reproduction outside the repo. Starting from REPL notes
`[A, B]`, rewriting the file externally to `[B]`, then calling
`_handle_forget(["1"])` printed `"Forgot: B"`, left REPL notes `['B']` and
file `[]` (diverged). With the file rewritten to garbage, raised
`ValueError: memory file ... is malformed`, uncaught by the run loop
(`repl.py` ~152-183 only catches `StopIteration`/`EOFError`/
`KeyboardInterrupt` around input, not around `_handle_command`). With the
file emptied, raised `IndexError`, likewise uncaught.

Required change: make `/forget` act on the same Memory `/memory` shows and
keep the REPL and file in agreement. Simplest option: pass the REPL's
current notes (or the remaining list after removal) into `memory.forget`
and have it rewrite the file from that via the existing temp-file +
`os.replace` path, with no re-load - matches the spec's "last writer wins"
posture already established for `/remember`. Add a `run_repl`-level test
where the file changes between startup and `/forget`.

### suggestion - forget(): stale temp file / permissions / symlink on write failure (not required)

If the temp-file write fails partway (e.g. `ENOSPC`), the original stays
intact but a stale `<path>.tmp` is left behind; `os.replace` also drops the
original file's permissions and would replace a symlinked Memory file with
a regular file. Minor. Optional: clean up the temp file on failure;
optionally resolve the real path before replacing.

### suggestion - write-failure test monkeypatches memory.forget wholesale (not required)

`test_forget_write_failure_is_a_local_error_and_leaves_memory_unchanged`
replaces `memory.forget` entirely, so it only proves the REPL catches
`OSError` - it never exercises a real failure through the temp-file/replace
path. Optional: trigger a real failure (e.g. patch `os.replace`) and assert
the file and REPL notes are both unchanged.

## Checks

- `uv run pytest -q` at HEAD (range head plus bookkeeping-only commit):
  497 passed in 8.29s.
- Scratch reproduction script (outside the repo) confirmed the
  divergence/crash in the important finding.
- Standards: follows repo conventions, no stray comments, no emojis, no
  Fowler smells worth flagging. The duplicated range check (REPL and
  `memory.forget` both check range) is defensible as module-level
  validation.
- Spec: every ticket criterion implemented; no scope creep. One requirement
  ("REPL and file agree"; indices positional against current Memory as
  `/memory` shows) is implemented incorrectly when the file changes during
  the Run.

## Residual risks (informational, no action required)

- Ticket 01's `/remember` likewise does not reconcile external file
  changes (it appends, so no crash) - outside this ticket's scope.
