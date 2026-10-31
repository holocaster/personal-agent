# 02: Add and delete files in a Patch, and document apply_patch

**What to build:** The same `apply_patch` Patch can also create new files
with `*** Add File:` and remove files with `*** Delete File:`, mixed freely
with Update File sections. Added files show as all-added and deleted files as
all-removed in the one combined diff; both follow the same Workspace Root
bounds, validate-before-confirm and all-or-nothing restore as updates. The
README documents `apply_patch`.

**Blocked by:** 01 (Update several files in one confirmed, all-or-nothing
Patch).

**Spec:** `docs/specs/0028-apply-patch.md` (R2 Add/Delete sections, R4 Add
and Delete rules, R6 Add/Delete preview headers, R7 add/delete restore, R8
actions, R9); **ADRs:** none.

- [x] Parser accepts `*** Add File: <path>` followed by zero or more `+`
      lines (content = those lines, each ending with `\n`; zero lines creates
      an empty file) and `*** Delete File: <path>` with no body; any non-`+`
      line in an Add body is a Tool error naming the line. The ticket-01
      "not supported yet" errors are removed. (R2)
- [x] Add: parent directory must already exist (no creation); target must
      not exist, including a dangling symlink ("file exists; use Update
      File"); excluded names rejected; content within the Mutating File
      Limit. Delete: existing-file rules, not itself a symlink, UTF-8 text
      within the Mutating File Limit. Duplicate-path detection covers every
      operation. All checks run before Tool Confirmation. (R4, R5)
- [x] Combined preview uses `--- /dev/null` / `+++ <path>` for Add and
      `--- <path>` / `+++ /dev/null` for Delete, in Patch order among Update
      sections; every file appears with its headers even when empty. (R6)
- [x] Apply creates added files and unlinks deleted files in Patch order. On
      an OS error, added files are removed and deleted or updated files are
      rewritten from their original bytes, including the failing one; any
      unrestorable path is listed in the Tool error. (R7)
- [x] Result entries carry `"action": "add"` / `"delete"` alongside
      `"update"`, in Patch order. (R8)
- [x] README documents `apply_patch` beside `write`/`edit` per R9: envelope
      and operations, exact matching and anchors, path bounds (deletes
      included), validation before one confirmation, all-or-nothing apply
      with restore, denial in `plan`, and Git as the only revert after
      approval. (R9)
- [x] Tests at the `execute_batch` seam cover: add plus update plus delete in
      one Patch; add into a missing directory; add over an existing file and
      over a dangling symlink; add of an excluded name; add over the limit;
      empty add; delete of a missing file, a symlink, an excluded file, a
      binary file, an over-limit file; the same path as add and delete;
      preview headers and content for add and delete; rejection leaves every
      file as it was; mid-apply failure after an add and a delete restores
      both (added file gone, deleted file back with original bytes). Full
      offline suite passes.
