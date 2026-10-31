# 0016 - Mutating Tools (write, edit)

Brief: `docs/briefs/0016-write-tools.md`. Vocabulary (Mutating Tools, Tool
Confirmation, Workspace Tools, Workspace Root, Tool Registry, Call Log,
Terminal, Input Box) is in `docs/CONTEXT.md`; scope is recorded there under
"Tool boundary" and "Mutating Tools scope". No ADR: every decision here is
either settled in the brief and `docs/CONTEXT.md` or a local mechanism
choice.

## Problem Statement

The agent can inspect the Workspace Root (`list_files`, `read_file`,
`search_text`) but cannot change it. When the user asks for a file to be
created or a line to be fixed, the model can only print the new text and the
user has to copy it into place by hand. At the same time, the user does not
want a model changing files without seeing and approving each change first.

## Solution

Two new built-in Mutating Tools join the Tool Registry:

- `write(path, content)` creates a new file, or overwrites an existing one,
  with the full given content, only inside a directory that already exists.
- `edit(path, old_string, new_string, replace_all=false)` replaces the one
  exact occurrence of `old_string` in an existing file, or every occurrence
  when `replace_all` is true; zero matches, or more than one without
  `replace_all`, is an error.

Both use the same Workspace Root bounds as the Workspace Tools. Before
either one changes anything, the REPL shows a Tool Confirmation: the unified
diff of the change (or, for a `write` that creates a file, its full content)
and a `[y/N]` question. Only an explicit yes applies the change; anything
else leaves the file untouched and tells the model the change was rejected.
`ROUTER_MAX_WRITE_BYTES` (default 64 KiB) caps the size of what may be
written. The existing Tool execution Call Log entry is the audit trail.

## User Stories

1. As a REPL user, I want the model to create a new file in my Workspace Root with `write`, so that I do not have to copy generated text into a file by hand.
2. As a REPL user, I want the model to overwrite an existing file with `write`, so that it can rewrite a whole file when that is simpler than many edits.
3. As a REPL user, I want the model to change one exact piece of an existing file with `edit`, so that small fixes do not require rewriting the file.
4. As a REPL user, I want `edit` with `replace_all` to replace every occurrence, so that a rename inside a file is one Tool call.
5. As a REPL user, I want `edit` to fail when `old_string` is not found, so that the model never believes a change happened when it did not.
6. As a REPL user, I want `edit` to fail when `old_string` appears more than once and `replace_all` is not set, so that the wrong occurrence is never changed.
7. As a REPL user, I want `edit` to match exactly, with no fuzzy or whitespace-tolerant matching, so that what is replaced is exactly what the model named.
8. As a REPL user, I want to see the full content of a new file before `write` creates it, so that I know exactly what will appear on disk.
9. As a REPL user, I want to see a unified diff before `write` overwrites an existing file, so that I see what I would lose.
10. As a REPL user, I want to see a unified diff before `edit` changes a file, so that I can check the change in context.
11. As a REPL user, I want every `write` and `edit` to wait for my explicit approval, so that no file changes without my consent.
12. As a REPL user, I want anything other than an explicit yes (including an empty line) to reject the change, so that a stray Enter never modifies a file.
13. As a REPL user, I want a rejected change to leave the file exactly as it was, so that rejecting is always safe.
14. As a REPL user, I want the model told that I rejected the change, so that it can adjust instead of assuming success.
15. As a REPL user, I want the model to keep working after a rejection within the same turn, so that one rejected change does not end the turn.
16. As a REPL user, I want Ctrl-C at the confirmation question to interrupt the turn without writing, so that I can abort the whole request.
17. As a REPL user, I want the spinner stopped while I am asked to confirm, so that it does not draw over the diff or the question.
18. As a REPL user, I want model-supplied content in the diff shown with terminal control characters sanitized, so that a malicious file body cannot garble or hijack my terminal.
19. As a REPL user, I want Tool Confirmation to work in the interactive Input Box, so that it fits the normal interactive REPL.
20. As a user piping input into the REPL, I want the confirmation answer read from the next input line, and end of input treated as rejection, so that scripted runs stay explicit and fail closed.
21. As a REPL user, I want a Tool call that would fail validation (bad path, missing parent directory, excluded file, too large, no unique match) to fail before I am asked to confirm, so that I never approve a change that cannot happen.
22. As a REPL user, I want `write` into a directory that does not exist to fail rather than create directories, so that the model cannot silently build directory trees.
23. As a REPL user, I want `write` and `edit` confined to the Workspace Root: relative paths only, no traversal, no symlink escape, so that the model can never change files outside it.
24. As a REPL user, I want `write` onto a dangling symlink, a directory, or a directory symlink rejected, so that a write can never land outside the Workspace Root or replace a directory.
25. As a REPL user, I want `.env`, `*.pem` and `*.key` never written or edited, so that secrets files stay out of reach of the model.
26. As a REPL user, I want `edit` to reject a binary, non-UTF-8, or over-read-limit file, so that it only operates on text it could read.
27. As a user, I want `ROUTER_MAX_WRITE_BYTES` to cap what `write` writes and what `edit` produces, default 64 KiB, so that a runaway model cannot fill my disk.
28. As a user, I want an invalid `ROUTER_MAX_WRITE_BYTES` to stop startup with a configuration error, so that a typo is not silently ignored.
29. As a Call Log reader, I want each `write` and `edit` (applied, rejected, or failed) recorded as a normal Tool execution entry with its arguments and result, so that the Call Log is the audit trail of every change.
30. As a Call Log reader, I want no new Call Log entry type, so that Resume and existing readers keep working unchanged.
31. As a REPL user, I want the live `tool>` line printed for `write` and `edit` like any other Tool, so that I see the outcome after confirming.
32. As a REPL user, I want the three Workspace Tools and the other built-ins to keep running without any confirmation, so that reading stays fast.
33. As a developer calling `route()` without a confirmation callback, I want Mutating Tools to be rejected, so that no code path can write without a gate.
34. As a README reader, I want `write`, `edit`, Tool Confirmation, `ROUTER_MAX_WRITE_BYTES`, and the no-backup / Git-is-the-revert posture documented, so that I know what the agent can change and how to undo it.
35. As a REPL user, I want a write that fails at the OS level (for example, permission denied) reported as a Tool error, so that the model and I both learn it did not happen.

## Implementation Decisions

- **Tools module.** `write` and `edit` live beside the Workspace Tools in the
  tools package's workspace module and reuse its path validation
  (`_resolve_workspace_path`, `_is_excluded`, `_file_target`,
  `_read_text`), not a second implementation. The Workspace Tools
  themselves are unchanged.
- **Two-phase Mutating Tool.** Each Mutating Tool is split into a prepare
  step and an apply step. Prepare runs every check that can fail (path,
  exclusion, parent directory, size limit, UTF-8, match count) and computes
  the full new file content plus the preview; it never touches disk. Apply
  writes the prepared content. Tool Confirmation sits between them, so a
  doomed change is never shown for approval.
- **`write` path rules.** `path` is relative and has no `..`. The parent
  directory is resolved strictly through the existing workspace resolver
  (must exist, be a directory, and resolve inside the Workspace Root); no
  directory is created. The final name must not be excluded. If the target
  exists (including as a symlink) it must pass the existing file-target rules
  (a regular file resolving inside the Workspace Root, neither the candidate
  nor the resolved name excluded); a dangling symlink, a directory, or a
  directory symlink is rejected. Content is encoded as UTF-8 (an unencodable
  string is a Tool error) and written as bytes with no newline translation.
- **`edit` rules.** `path` must pass the existing file-target rules. The file
  is read through the existing bounded reader with `ROUTER_MAX_READ_BYTES`;
  binary or non-UTF-8 content is a Tool error. `old_string` must be
  non-empty (schema `minLength: 1`). Count of exact, case-sensitive
  occurrences: zero is an error; more than one without `replace_all` is an
  error naming the count; otherwise the one occurrence, or every occurrence
  with `replace_all`, is replaced. `new_string` equal to `old_string` is an
  error (no change to make).
- **Size limit.** `ROUTER_MAX_WRITE_BYTES` is parsed and validated in the
  existing workspace configuration exactly like `ROUTER_MAX_READ_BYTES`
  (unset or empty means 65536; otherwise a positive whole-byte count; else a
  configuration error printed by `main`, exit 1). `write` content, and the
  full resulting content of an `edit`, larger than the limit (in UTF-8
  bytes) is a Tool error; nothing is truncated.
- **Tool results.** `write` returns the path and bytes written and whether
  the file was created or overwritten; `edit` returns the path and the
  number of replacements. Every failure is a `ToolExecutionError`, so it
  becomes a normal error Tool result the model sees.
- **Tool Registry.** `_ToolEntry` gains a marker for Mutating Tools (with
  its prepare/apply pair). `write` and `edit` are registered with argument
  schemas: `write` requires `path` (string, `minLength: 1`) and `content`
  (string); `edit` requires `path`, `old_string` (both `minLength: 1`) and
  `new_string` (string), with optional boolean `replace_all` defaulting to
  false; `additionalProperties: false` on both. Both appear in `TOOL_DEFS`,
  so every Provider sees them.
- **Confirmation seam.** `execute_batch` takes an optional `confirm`
  callback and `route()` gains a matching optional parameter passed down the
  Tool loop, alongside the existing `on_tool_result`. For a Mutating Tool,
  after schema validation and a successful prepare, `execute_batch` calls
  `confirm` with the Tool name, the relative path, and the preview (whether
  it is a new-file content preview or a diff). A `True` return applies the
  change; `False` produces an error result ("change rejected by the user")
  and nothing is written. When no `confirm` callback is given, Mutating
  Tools are rejected the same way (fail closed). A `KeyboardInterrupt` from
  the callback propagates, ending the turn as `interrupted` through the
  existing REPL path, with nothing written. Non-mutating Tools never call
  `confirm`.
- **Preview.** For a `write` creating a file: the full content. For a
  `write` overwriting and for every `edit`: a unified diff (stdlib
  `difflib`) of old versus new content, labelled with the relative path.
- **REPL Tool Confirmation.** The Terminal builds the `confirm` callback per
  routed turn, like the Tool result printer. It stops the spinner if one is
  running, prints a header naming the Tool and path, then the preview with
  control characters sanitized (multiline), then asks `Apply this change?
  [y/N] `. Only `y` or `yes` (case-insensitive, surrounding whitespace
  ignored) approves; anything else rejects. Interactive mode reads the answer
  through the Input Box's prompt_toolkit session as a single-line prompt
  with that question; piped or plain mode reads the next line from the same
  input source the REPL reads tasks from, and end of input rejects (the REPL
  then exits at its next read, as today). The spinner resumes afterwards.
- **Call Log.** No new entry type. The existing Tool execution entry already
  records arguments and result for applied, rejected and failed calls
  (brief decision 6). `log_version` is unchanged; Resume is unaffected.
- **System Prompt.** Unchanged; the Tool descriptions carry the usage
  contract (existing directory only, exact unique match, user confirmation).
- **README.** The Workspace Tools section stops calling the Workspace Root
  read-only and a Mutating Tools section documents `write`, `edit`, Tool
  Confirmation (diff/content, `[y/N]`, piped behavior), exact-match rules,
  no parent-directory creation, `ROUTER_MAX_WRITE_BYTES`, full content in
  the Call Log, and that Git is the only revert mechanism.

## Testing Decisions

- Good tests assert external behavior only: files on disk in a temporary
  Workspace Root, Tool results, what the REPL prints, the tool results sent
  back to the fake Provider, the Session's Call Log lines, and `main`'s exit
  status and stderr. No assertions on private helpers.
- Seams (existing; no new seam):
  - `execute_batch` with `ToolCall`s against a configured temporary
    workspace and a stub `confirm` callback: every path, symlink, exclusion,
    size, UTF-8 and match rule; that failures happen before `confirm` is
    called; approve, reject, and missing callback outcomes.
  - `run_repl` with an input stream, an output stream, and the Provider faked
    at `urlopen` via `install_fake_urlopen`, returning a `write`/`edit` Tool
    call: preview printed and sanitized, `y`/`yes` applies, other answers and
    EOF reject, the model receives the rejection, Call Log entry written.
  - `InputBox` with a pipe input for the interactive confirmation prompt.
  - `main` for `ROUTER_MAX_WRITE_BYTES` configuration errors.
- Prior art: `tests/test_workspace_tools.py` (path bounds, symlinks,
  exclusions, limits), `tests/test_tools.py` (`execute_batch`),
  `tests/test_repl.py` (Tool lines, Call Log assertions),
  `tests/test_input_box.py`, `tests/test_main.py`, `tests/conftest.py`.

## Out of Scope

- Fuzzy or whitespace-tolerant matching for `edit`.
- Implicit parent-directory creation on `write`.
- Before-images, backups, or versioning of overwritten content.
- Deleting, moving, or renaming files; patches; shell commands; MCP;
  environment-variable access.
- A persistent "always allow" or per-session approval setting.
- Confirmation for any non-mutating Tool.
- A new Call Log entry type.

## Further Notes

- Piped-mode behavior (answer read from the next input line, EOF rejects) is
  a planner mechanism choice: the brief requires explicit approval and says
  nothing about piped input; this keeps approval explicit and fails closed.
- The full `write` content is recorded in the Call Log by the existing Tool
  execution entry, bounded by `ROUTER_MAX_WRITE_BYTES`.
- Applying writes directly (no temp-file replace), so symlinked targets and
  file permissions are preserved; a mid-write OS failure is reported as a
  Tool error.
