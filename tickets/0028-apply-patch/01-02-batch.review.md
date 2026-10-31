# Review: Batch 01-02 (0028-apply-patch)

status: approved
tickets: [01, 02]
reviewed_range: accb459bde0a7254580dffe551257699cad8cc2c..eee038ce8d5e0b25abb6e4e75f0630a737840087
round: 2

## Result

All round-1 findings fixed (preview newline marker, raw-line `@@` detection, Add resolved-identity dedup, section path in helper errors, raw anchor text). The `_parse_hunks` reorder, which makes indented markers content, is accepted as a tightening consistent with Codex and fails safely. The shared `workspace._unified_diff` change affects preview text only; no regression.

## Optional suggestions (not required)

1. `@@ ` with only trailing whitespace is an empty anchor that matches the first blank line, resolving context a bare `@@` would reject as ambiguous. Matches Codex; the user still sees the diff.
2. `_finish_diff` uses `str.splitlines`, so a line with a form feed or other Unicode line break gets a spurious "\ No newline at end of file" marker in the preview. Preview-only; pre-existing root cause.

## Checks

- `uv run pytest -q` at eee038c: 1085 passed.
- 12-case probe script against `prepare_patch`.
- Tree left clean.
