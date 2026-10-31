# 0028 — apply_patch Tool

Brief: `docs/briefs/0028-apply-patch.md`. Vocabulary (Patch, Mutating Tools,
Mutating File Limit, Tool Confirmation, Fetched-Content Warning, Agent Mode,
Workspace Root, Tool Registry, Call Log) is in `docs/CONTEXT.md`; scope is
recorded there under "apply_patch scope", "Tool boundary", "Mutating Tools
scope" and "Agent Mode scope". Prior Mutating Tool design: `docs/specs/0016-write-tools.md`.
The Call Log stays the Conversation record (ADR-0005). Envelope grammar
reference: `openai/codex` `codex-rs/core/assets/tools/apply_patch.lark` and
`codex-rs/apply-patch/src/parser.rs` (consulted 2026-09-27; inspiration only,
not a dependency). No new ADR: every product decision is settled in the brief
and `docs/CONTEXT.md`; the rest are local mechanism choices recorded below.

## Problem Statement

A change that touches several files, or several places in one file, costs the
model one `edit` or `write` call per change and the user one Tool
Confirmation per call. The user reviews the change in fragments, and a
rejection or failure halfway leaves the workspace half-changed. GPT models are
also trained on the OpenAI/Codex patch envelope and use `edit` less reliably.

## Solution

A new `apply_patch` Mutating Tool takes one Patch in the OpenAI/Codex
envelope. The Patch can add, update and delete several files, with several
hunks per updated file, located by exact context lines and optional `@@`
anchors. The whole Patch is checked against the current files before the user
is asked anything; any problem is a Tool error and nothing is touched. The
user then sees one Tool Confirmation with one combined diff of every file and
answers once for the whole Patch. An approved Patch is applied whole: if a
write fails partway, files already changed are restored from their in-memory
originals. `apply_patch` is offered beside `write` and `edit` to every model
in `build` and denied in `plan`.

## User Stories

1. As a REPL user, I want the model to change several files in one Tool call, so that a multi-file change is one step instead of many.
2. As a REPL user, I want one Tool Confirmation for the whole Patch, so that I approve a coherent change once instead of answering many prompts.
3. As a REPL user, I want the confirmation to show one combined diff of every file in Patch order, so that I review the whole change together.
4. As a REPL user, I want the confirmation header to name every file the Patch touches, so that I see the blast radius before reading the diff.
5. As a REPL user, I want a deleted file shown as all of its lines removed, so that I see exactly what I would lose.
6. As a REPL user, I want an added file shown as all of its lines added, so that I see what will appear on disk.
7. As a REPL user, I want rejecting the confirmation to leave every file untouched, so that rejecting is always safe.
8. As a REPL user, I want a blank answer, anything other than `y`/`yes`, or end of input to reject, so that a stray Enter never changes files.
9. As a REPL user, I want Ctrl-C at the confirmation to interrupt the turn without writing, so that I can abort the whole request.
10. As a REPL user, I want the model told the Patch was rejected, so that it can adjust instead of assuming success.
11. As a REPL user, I want the Fetched-Content Warning on an `apply_patch` confirmation after successful external content in the same turn, so that I read the Patch with suspicion when web content may have steered it.
12. As a REPL user, I want a Patch that cannot apply to fail before I am asked, so that I never approve a change that cannot happen.
13. As a REPL user, I want a Patch to apply whole or not at all, so that I never end up with half a refactor on disk.
14. As a REPL user, I want files already written restored when a later write fails, so that an OS error mid-apply does not leave the workspace inconsistent.
15. As a REPL user, I want to be told which files could not be restored if restoring itself fails, so that I know what to fix with Git.
16. As the model, I want to update a file with several hunks located by context lines, so that I never have to count line numbers.
17. As the model, I want an `@@` anchor line (for example a function or class header) to narrow where a hunk applies, so that I can target repeated code without long context.
18. As the model, I want several hunks for one file to apply top to bottom, so that later hunks never match text above earlier ones.
19. As the model, I want `*** End of File` to pin a hunk to the end of the file, so that I can change the last lines unambiguously.
20. As the model, I want a hunk with only `+` lines to append to the end of the file, as in Codex, so that appending needs no context.
21. As the model, I want a completely empty line inside a hunk read as an empty context line, so that a stripped trailing space does not break the Patch.
22. As the model, I want a Tool error naming the file and hunk when context is missing or ambiguous, so that I can correct just that hunk.
23. As the model, I want a Tool error naming the line when the Patch text is malformed, so that I can fix the envelope.
24. As the model, I want `*** Move to:` rejected with a clear Tool error, so that I fall back to add plus delete instead of guessing.
25. As the model, I want to add a new file with `*** Add File:`, so that creation fits in the same Patch as edits.
26. As the model, I want to delete a file with `*** Delete File:`, so that removals fit in the same Patch.
27. As a REPL user, I want Add File on an existing file to fail, so that a whole file is never silently overwritten; Update File is the way to change it.
28. As a REPL user, I want Add File into a missing directory to fail, matching `write`, so that the model cannot silently build directory trees.
29. As a REPL user, I want Update or Delete on a missing file to fail before confirmation, so that I never approve a no-op.
30. As a REPL user, I want the same path twice in one Patch to fail, so that the combined diff never hides one change behind another.
31. As a REPL user, I want an empty Patch to fail, so that the model never believes a no-op changed something.
32. As a REPL user, I want every path in a Patch held to the same bounds as `write`/`edit` (relative, inside the Workspace Root, no symlink escape, `.env`/`*.pem`/`*.key` excluded), including deletes, so that `apply_patch` opens no new hole.
33. As a REPL user, I want the Mutating File Limit applied per file to both the existing file and the result, so that a Patch cannot load or produce an oversized file.
34. As a REPL user, I want binary or non-UTF-8 files refused for update and delete, so that the diff I approve is readable and complete.
35. As a user in `plan` Agent Mode, I want `apply_patch` neither offered nor executable, so that planning never changes the workspace.
36. As a user of any model, I want `apply_patch` always offered beside `write` and `edit` in `build`, so that Escalation across Providers never loses a Tool mid-turn.
37. As a Call Log reader, I want each `apply_patch` call (applied, rejected, or failed) recorded as a normal Tool execution entry with the Patch and the result, so that the Call Log remains the audit trail.
38. As a REPL user, I want the live `tool>` line for `apply_patch` like any other Tool, so that I see the outcome after confirming.
39. As a README reader, I want `apply_patch`, its envelope, its all-or-nothing rule and its bounds documented beside `write`/`edit`, so that I know what it can change and how to undo it.

## Requirements

- **R1 — Registration and Agent Mode.** The Tool Registry declares
  `apply_patch` in the default registry (always, for every model, beside
  `write`/`edit`) with schema `{"patch": string, minLength 1}`, `patch`
  required, no additional properties, and `requires_confirmation`. The
  description states the envelope compactly: `*** Begin Patch` /
  `*** End Patch`, `*** Add File: <path>` followed by `+` lines,
  `*** Delete File: <path>`, `*** Update File: <path>` followed by hunks of
  ` `/`-`/`+` lines with optional `@@ <anchor>` lines and `*** End of File`;
  relative paths; exact context, no line numbers; no `*** Move to:`; the Patch
  applies whole or not at all and needs the user's confirmation. In `plan`,
  `apply_patch` is not advertised and is in the plan-denied set, so a
  fabricated call is rejected with the existing plan-mode Tool error before
  validation or confirmation.
- **R2 — Envelope grammar.** Split `patch` on `\n`, strip one trailing `\r`
  from each line, and ignore blank lines before `*** Begin Patch` and after
  `*** End Patch`. Marker lines (`*** Begin Patch`, `*** End Patch`, file
  headers, `*** End of File`) match after trimming surrounding whitespace;
  content lines are never trimmed. The first line must be `*** Begin Patch`,
  the last `*** End Patch`. Between them come file sections:
  - `*** Add File: <path>` then zero or more lines each starting with `+`
    (the text after `+` is one file line).
  - `*** Delete File: <path>` with no body.
  - `*** Update File: <path>` then one or more hunks. A hunk is optionally
    started by `@@` or `@@ <anchor>`; the first hunk may omit it. Hunk lines
    start with ` ` (context), `-` (removed) or `+` (added); a completely empty
    line is an empty context line. `*** End of File` may close a hunk.
  - A path is the header text after the marker, trimmed.
  Tool errors, each naming the 1-based Patch line where useful: missing
  Begin/End marker; a Patch with no file sections; an Update with no hunks; a
  hunk with no ` `/`-`/`+` lines; `*** Move to:` ("Move to is not
  supported"); any other unrecognized line.
- **R3 — Exact hunk matching.** An existing file is split into lines on `\n`,
  or on `\r\n` when the file contains `\r\n`; untouched lines keep their bytes.
  Hunks of one Update apply top to bottom with a cursor that starts at the
  first line and moves past each applied hunk. For each hunk:
  - An anchor is found as the first line at or after the cursor exactly equal
    to the anchor text; missing is a Tool error. The hunk's search then
    starts after that line.
  - The hunk's old lines (context plus removed, in order) must match a
    contiguous run of lines exactly, case- and whitespace-sensitive, in the
    search region. Without an anchor the run must occur exactly once in the
    region (zero: "context not found"; more: "context is ambiguous, add an
    `@@` anchor or more context"). With an anchor the first occurrence after
    the anchor is used. With `*** End of File` the run must end at the last
    line of the file.
  - A hunk with no old lines (only `+` lines) inserts its lines at the end of
    the file (after locating its anchor, if any), as Codex does.
  - Errors name the path and the 1-based hunk number.
  An Update whose result equals the current content is a Tool error. An
  updated or added file always ends with a line ending (`\n`, or `\r\n` for a
  CRLF file), as Codex does.
- **R4 — Path bounds per operation.** Every path goes through the same
  Workspace Root bounds as `write`/`edit`: relative only, no traversal, no
  symlink escape, `.env`/`*.pem`/`*.key` excluded, Mutating File Limit per
  file on both the existing content and the result, UTF-8 text only.
  - Update: the target must pass `edit`'s existing-file rules (a regular file,
    possibly through an in-root symlink, not binary or non-UTF-8).
  - Add: the parent directory must already exist (no creation, matching
    `write`); the target must not exist, including as a dangling symlink
    ("file exists; use Update File").
  - Delete: the target must pass the existing-file rules, must not itself be
    a symlink (deleting would remove only the link while the preview showed
    the target's content), and must be UTF-8 text within the Mutating File
    Limit so its removed content can be shown.
  - The same path twice in one Patch, compared by path relative to the
    Workspace Root and by resolved target for existing files, is a Tool error.
- **R5 — Validate everything before confirming.** Parsing, every path check,
  every hunk match and every size check for every file run before Tool
  Confirmation, without touching disk. The first failure returns one Tool
  error (`{"error": ...}`), the confirmation callback is never called, and no
  file changes.
- **R6 — One Tool Confirmation.** The existing confirmation callback shape is
  unchanged. `apply_patch` passes the Patch's paths comma-joined in Patch
  order as the path, and one combined preview: per file, in Patch order, a
  unified diff with `--- <path>` / `+++ <path>` headers for Update,
  `--- /dev/null` / `+++ <path>` for Add, `--- <path>` / `+++ /dev/null` for
  Delete; every file appears with its headers even when its content is empty.
  The Terminal shows `apply_patch: <paths>`, the sanitized preview, the
  Fetched-Content Warning when the turn already had successful external
  content (`apply_patch` joins `shell`/`write`/`edit` in the warning-aware
  set), and `Apply this change? [y/N] `. Approve applies the whole Patch;
  rejection, EOF or no callback returns `change rejected by the user` with
  nothing touched; Ctrl-C keeps the existing interrupted-turn semantics.
- **R7 — All-or-nothing apply.** After approval, operations run in Patch
  order: Add and Update write the prepared bytes directly (as `edit` does, so
  an in-root symlink and file permissions are kept); Delete unlinks the file.
  If any operation raises an OS error, every file touched so far, including
  the failing one, is restored from memory: updated and deleted files are
  rewritten with their original bytes, added files are removed. The Tool
  error names the failing file and reason; if any restore also fails, the
  error lists the paths that could not be restored. Files are not
  re-validated between confirmation and apply, matching `write`/`edit`.
- **R8 — Result and logging.** Success returns
  `{"files": [{"path": <path>, "action": "add"|"update"|"delete"}, ...]}` in
  Patch order. The existing Tool execution Call Log entry, `tool>` line,
  Provider follow-up and Resume handling apply unchanged; no new Call Log
  entry type.
- **R9 — Documentation.** README documents `apply_patch` beside
  `write`/`edit`: the envelope and operations, exact matching and anchors,
  the path bounds (deletes included), validation before one confirmation,
  all-or-nothing apply with restore, denial in `plan`, and that Git stays the
  only revert mechanism after approval.

## Implementation Decisions

- **New Tools module.** The Patch parser, hunk matcher, prepare step and
  apply step live in one new module in the Tools package beside the workspace
  module. It reuses the workspace module's path helpers (relative-path
  validation, directory target, existing-file target, exclusion, bounded text
  reader, configured Workspace Root and Mutating File Limit), not a second
  implementation. The workspace module keeps `write`/`edit` unchanged.
- **Two-phase shape.** `apply_patch` follows the existing prepare → Tool
  Confirmation → apply path in the Tool Registry. Its prepare step returns a
  prepared value exposing `display_path` and `preview` (what the Registry and
  confirmation callback already read) plus, per file in Patch order, the
  action, target path, original bytes (or absence) and new bytes (or
  deletion). The apply step consumes it and returns the R8 result. No change
  to the confirmation callback signature or the Terminal prompt code beyond
  what the warning-aware set needs.
- **Registry wiring.** Add the entry to the default registry, add
  `apply_patch` to the plan-denied set and to the Fetched-Content-Warning-aware
  set. It is not in the plan Tool set, so `plan` never advertises it.
- **Anchor semantics.** One anchor per hunk, as in the Codex grammar. An
  anchor is a deliberate navigation, so its first occurrence at or after the
  cursor is used; plain context without an anchor must be unique in its
  search region. This satisfies the brief's "repeated context without a
  disambiguating `@@` anchor is a Tool error".
- **Leniency kept to the Codex grammar.** Only what the Codex parser itself
  accepts: trimmed marker lines, a bare `@@`, an omitted first `@@`, empty
  lines as empty context, CR stripped from Patch lines. No heredoc stripping,
  no fuzzy or whitespace-tolerant matching of file content.
- **Paths display.** The prepared `display_path` is the list of Workspace
  Root-relative paths joined by `, `, used in the confirmation header only.

## Testing Decisions

- Test external behavior only: files on disk, the Tool result, whether and
  with what the confirmation callback was called, the Terminal output, and the
  Call Log entry. Never assert private helper names or parser internals.
- Primary seam: the Tool Registry's `execute_batch` with a scripted confirm
  callback, as the existing `write`/`edit` tests in
  `tests/test_workspace_tools.py` do. Cover grammar, matching, bounds,
  validation-before-confirm (callback never called, files unchanged),
  rejection, preview contents, result shape, and mid-apply failure with
  restore (monkeypatch the file write or unlink to fail on the Nth file, as
  `test_write_apply_failure_is_reported_as_a_tool_error` does).
- Second seam, for wiring only: `run_repl` with scripted Provider Tool calls,
  as `tests/test_repl.py` (Fetched-Content Warning after `webfetch`, confirm
  prompt text) and `tests/test_agent_mode.py` (plan denial before validation
  and confirmation, plan Tool set) do. One or two tests each; do not duplicate
  Registry-level coverage.
- Registry schema check: extend the existing "every registered schema passes
  check_schema" coverage implicitly by registration; assert the `apply_patch`
  schema shape like the `write`/`edit` advertisement tests.
- Run the full offline suite after each ticket.

## Out of Scope

`*** Move to:` (rename); Git unified diff format or accepting both formats;
heredoc-wrapped Patches; fuzzy or whitespace-tolerant context matching;
per-model Tool swapping; creating parent directories on Add File; backups or
undo beyond Git; `*** Environment ID:`; re-validating files between
confirmation and apply.

## Further Notes

- Deleting through `apply_patch` is the first non-`shell` delete. A restored
  deleted file gets its original bytes back but default permissions; this only
  happens on a mid-apply OS error and is acceptable.
- A Patch may carry large content for several files; the Mutating File Limit
  bounds each file, not the Patch as a whole. The full Patch is in the Call Log
  Tool execution entry, the same audit posture as `write`.
- Codex always ends updated files with a newline; this spec does the same, so
  updating a file without a final newline adds one, visible in the diff.
