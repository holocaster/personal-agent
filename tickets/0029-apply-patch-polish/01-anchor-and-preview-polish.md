# 01 — Blank `@@ ` anchor and preview line splitting

**Spec:** none (fast path)
**Blocked by:** none
**Origin:** optional suggestions 1 and 2 in `tickets/0028-apply-patch/01-02-batch.review.md`

## Context

Two small follow-ups to the `apply_patch` Tool (feature 0028) that the user asked to apply.

1. In the Patch hunk parser, a hunk header of `@@` followed only by whitespace (e.g. `@@ `, `@@   `, `@@\t`) is currently read as an anchor whose text is empty or whitespace, which matches the first blank line after the cursor. That silently resolves context a bare `@@` would reject as ambiguous.
2. The shared unified-diff builder used for Tool Confirmation previews (`write`, `edit`, `apply_patch`) splits text with `str.splitlines(keepends=True)`, which also breaks on form feed, vertical tab, `\x1c`-`\x1e`, `\x85`, U+2028 and U+2029. Such a line does not end in `\n`, so the preview gets a spurious `\ No newline at end of file` marker mid-diff.

## Acceptance criteria

1. A hunk header line that is `@@` followed only by whitespace is treated exactly like a bare `@@` (no anchor). A header `@@ <text>` with non-whitespace text keeps its current behavior, including preserving the raw anchor text (trailing whitespace kept).
2. With file `k\n\nk\nend\n` and a Patch hunk header `@@ ` then `-k` / `+K`, the result is the same Tool error a bare `@@` gives ("context is ambiguous"), and no file changes.
3. Preview diffs split lines only on `\n` (keeping `\r\n` together as one line ending), never on other Unicode line breaks. The `\ No newline at end of file` marker appears only after the final line of a side whose text lacks a final `\n`.
4. A preview for text containing a form feed mid-line (e.g. old `a\x0cb\nc\n`, new `a\x0cb\nC\n`) shows `a\x0cb` as one line with no `\ No newline at end of file` marker.
5. Bytes written by `write`, `edit` and `apply_patch` are unchanged by this ticket; only the preview text and the header parsing change.
6. One test per criterion 2 and 4 at the existing Tool test seams; full suite green.
