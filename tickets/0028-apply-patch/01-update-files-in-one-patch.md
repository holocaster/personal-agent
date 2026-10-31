# 01: Update several files in one confirmed, all-or-nothing Patch

**What to build:** In `build` Agent Mode, the model can call `apply_patch`
with one Patch in the OpenAI/Codex envelope that updates one or more existing
files, with one or more hunks each, located by exact context lines and
optional `@@` anchors. The whole Patch is validated before the user is asked;
the user sees one Tool Confirmation with a combined diff of every file and
answers once; an approved Patch is written whole, and a mid-apply OS error
restores already-written files. `plan` never offers or runs it. In this
ticket `*** Add File:` and `*** Delete File:` sections are recognized by the
parser but return a Tool error ("not supported yet"); ticket 02 enables them.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0028-apply-patch.md` (R1, R2, R3, R4 Update and
duplicate-path rules, R5, R6, R7 for Update, R8; Implementation Decisions;
Testing Decisions); **ADRs:** ADR-0005 (Call Log is the Conversation record).

- [x] `apply_patch` is registered in the default Tool Registry with schema
      `{patch: string, minLength 1}` (required, no additional properties),
      requires Tool Confirmation, and carries the compact envelope description
      from R1. It is advertised in `build` for every model and absent from
      `plan`; a fabricated `plan` call gets the existing plan-mode Tool error
      before validation or confirmation. (R1)
- [x] The parser implements R2: Begin/End markers (blank lines around the
      envelope ignored, marker lines trimmed, one trailing `\r` stripped per
      line), `*** Update File:` with hunks started by `@@`/`@@ <anchor>` (first
      one optional), ` `/`-`/`+` lines, empty line as empty context, optional
      `*** End of File`. Tool errors, with the Patch line number where useful,
      for missing markers, no file sections, an Update with no hunks, an empty
      hunk, `*** Move to:`, and unrecognized lines. (R2)
- [x] Hunk matching implements R3 exactly: LF or CRLF line model with
      untouched bytes preserved; hunks applied top to bottom with a moving
      cursor; anchor = first exact line at or after the cursor; unanchored
      context must be unique in its region (distinct "not found" and
      "ambiguous" errors naming path and hunk number); anchored context uses
      the first occurrence after the anchor; `*** End of File` pins to the last
      line; a `+`-only hunk appends at end of file; a no-op Update is a Tool
      error; results always end with a line ending. (R3)
- [x] Update targets pass `edit`'s existing-file rules through the shared
      workspace helpers (relative, in-root, no symlink escape, excluded names,
      regular UTF-8 file, Mutating File Limit on existing and result). The same
      path twice (relative path or resolved target) is a Tool error. (R4)
- [x] Every check runs before Tool Confirmation; on any failure the confirm
      callback is never called and no file changes. (R5)
- [x] One confirmation: path argument is the paths comma-joined in Patch
      order; preview is the per-file unified diffs in Patch order with
      `--- <path>` / `+++ <path>` headers. `apply_patch` is in the
      Fetched-Content-Warning-aware set; the prompt is
      `Apply this change? [y/N] `. Rejection, EOF or no callback returns
      `change rejected by the user` with nothing written; Ctrl-C keeps
      existing interrupted-turn semantics. (R6)
- [x] Apply writes prepared bytes in Patch order directly (symlink and
      permissions kept). On an OS error, every file touched so far, including
      the failing one, is rewritten with its original bytes; the Tool error
      names the failing file and lists any path that could not be restored.
      (R7)
- [x] Success returns `{"files": [{"path", "action": "update"}, ...]}` in
      Patch order; the normal Tool execution Call Log entry and `tool>` line
      are produced with no new entry type. (R8)
- [x] Tests at the `execute_batch` seam (prior art: `write`/`edit` tests in
      `tests/test_workspace_tools.py`) cover: multi-file multi-hunk success;
      anchors, including repeated context disambiguated by an anchor;
      not-found and ambiguous context; hunk ordering; `*** End of File`;
      `+`-only append; empty-line context; CRLF file preserved; trailing
      newline added; no-op Update; every R2 grammar error; bounds (absolute,
      traversal, symlink escape, excluded, missing, binary, over-limit
      existing and result); duplicate path; confirm never called on failure;
      rejection leaves files untouched; preview content and path argument;
      mid-apply failure on the second file restores the first and the failing
      one; restore failure reported. At the `run_repl` seam: the
      Fetched-Content Warning on `apply_patch` after a successful `webfetch`
      (prior art `tests/test_repl.py`), and plan denial plus plan Tool set
      (prior art `tests/test_agent_mode.py`). Full offline suite passes.
