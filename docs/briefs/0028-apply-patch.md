# 0028 — apply_patch Tool

## Goal

Let the model change several files, with several hunks each, in one call and one Tool Confirmation, using the patch format OpenAI/Codex models are trained on.

## Scope

- Add a model-facing `apply_patch` Mutating Tool taking one Patch in the OpenAI/Codex envelope: `*** Begin Patch`, `*** Add File:`, `*** Update File:`, `*** Delete File:`, `*** End Patch`. Update hunks locate text by context lines and optional `@@` anchors, never by line numbers.
- Operations: add, update, delete files.
- Validate the whole Patch against the current files before confirmation. Any failure is a Tool error and nothing is touched.
- One Tool Confirmation for the whole Patch showing a combined diff of every file (a delete shows the content being removed). Approve or reject applies to the whole Patch. Fetched-Content Warning applies as for `write`/`edit`.
- All-or-nothing apply: if a write fails mid-apply, restore already-written files from their in-memory originals.
- Registered for every model beside `write`/`edit`; denied in `plan` Agent Mode like the other Mutating Tools.
- Same path bounds as `write`/`edit`: relative paths only, Workspace Root only, symlinks outside rejected, `.env`/`*.pem`/`*.key` excluded, Mutating File Limit per file. Deletes follow the same bounds.
- Existing Tool Registry validation, Call Log entry and result handling.

## Out of scope

- `*** Move to:` (rename); Git unified diff format; accepting both formats.
- Fuzzy or whitespace-tolerant context matching.
- Per-model Tool swapping (offering `apply_patch` instead of `edit`/`write` to GPT models).
- Creating parent directories on Add File.
- Backups or undo beyond Git.

## Settled decisions

1. Build it: multi-file atomic change in one confirmation, and a format GPT models handle better than `edit`.
2. OpenAI/Codex envelope only.
3. Add, update, delete; no move.
4. Validate everything before confirming; all-or-nothing apply with in-memory restore on mid-apply write failure.
5. Exact context matching, like `edit`. Missing context, or context repeated without a disambiguating `@@` anchor, is a Tool error.
6. Always registered beside `write`/`edit`; blocked in `plan`.
7. One confirmation, combined diff, one decision.
8. Add File with a missing parent directory is a Tool error, matching `write`.
9. Add File on an existing file is a Tool error; use Update File.
10. Update/Delete on a missing file, the same path twice in one Patch, and an empty Patch are Tool errors, caught before confirmation.
11. No path-bound exceptions for `apply_patch`, including deletes.

## Open questions

None for product scope. The planner owns the grammar details (e.g. `*** End of File`, trailing newline handling, CRLF), the confirmation-callback shape for multiple paths, result schema, and ticket slicing.
