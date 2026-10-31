# 0021 - Partial reads

Brief: `docs/briefs/0021-partial-reads.md` (all decisions settled; referenced
below as "brief decision N"). Extends `docs/specs/0009-workspace-tools.md`
(`read_file`, `search_text`), `docs/specs/0016-write-tools.md` (`write`,
`edit`) and `docs/specs/0018-shell-tool.md` (`shell` output cap). Vocabulary
(Read Window, Tool Output Cap, Mutating File Limit, Workspace Tools, Mutating
Tools, Tool Confirmation) is in `docs/CONTEXT.md`. No ADR applies or is added.

## Problem Statement

`read_file` returns a whole file or nothing. `PA_MAX_READ_BYTES` (64 KiB) is
both the largest file the model can read and the amount that enters the
Conversation, so a large file (a log, a generated file, a long module) cannot
be read at all, and a mid-size one costs its full size in context on every
later turn until Compression. `search_text` returns every matching line in
full, so one minified-JSON line times 100 matches leaks the same way. And
because `edit` and `write` read the existing file through the same limit, a
70 KB file cannot be edited even to change one line.

## Solution

`read_file` returns a Read Window: a range of lines chosen by a 1-based
`offset` and a line `limit` (default 500), each line prefixed with its line
number and a TAB, plus `has_more` and `next_offset` so the model knows exactly
where to continue. Files of any size are readable, one window at a time, read
streaming. `PA_MAX_READ_BYTES` becomes the Tool Output Cap (default 32 KiB):
the most bytes one Tool call hands the model. A window that would exceed it is
cut at the last whole line that fits, never rejected. `search_text` excerpts
are shortened around the match and its whole response is bounded by the same
cap. `shell` output keeps defaulting to that cap. `write`/`edit` stop using
`PA_MAX_READ_BYTES` altogether and are bounded instead by the Mutating File
Limit, `PA_MAX_WRITE_BYTES`, now defaulting to 1 MiB.

## User Stories

1. As the model, I want to read a file by line range, so that I receive only the part I need instead of the whole file.
2. As the model, I want `offset` to be 1-based like `search_text`'s `line`, so that I can jump straight to a search hit.
3. As the model, I want `offset` to default to 1 and `limit` to default to 500, so that a plain `read_file(path)` shows the start of a file at a useful size.
4. As the model, I want each returned line prefixed with its line number, so that I always know where I am in the file.
5. As the model, I want the Tool description to tell me the line-number prefix is not part of the file, so that I never copy it into `edit`'s `old_string`.
6. As the model, I want `edit`'s Tool description to repeat that warning, so that I see it at the moment I build an `old_string`.
7. As the model, I want a leaked prefix in `old_string` to produce the existing "old_string was not found" error, so that a mistake never corrupts a file.
8. As the model, I want `has_more` to tell me whether lines exist after the window, so that I know whether the file continues.
9. As the model, I want an explicit `next_offset`, so that I never miscount where to continue after a cut.
10. As the model, I want `next_offset` to be null when nothing follows, so that the end of the file is unambiguous.
11. As the model, I want a window that would exceed the Tool Output Cap to be cut at the last whole line that fits, so that I get as much as possible and know where to resume instead of guessing a smaller `limit`.
12. As the model, I want a single line longer than the cap returned truncated with `[...truncated]`, so that a minified file does not block me forever at one line.
13. As the model, I want the next window after a truncated line to start at the following line, so that I make progress through the file.
14. As the model, I want an `offset` past the end of the file to be an error naming the file's line count, so that I can correct the request instead of seeing a silent empty result.
15. As the model, I want an empty file read at offset 1 to return empty content rather than an error, so that reading an empty file is not a failure.
16. As the model, I want a binary or non-UTF-8 window to be the existing "file is binary or not valid UTF-8" error, so that the behavior I know is unchanged.
17. As a user, I want a file of any size to be readable one window at a time, so that the agent can inspect large logs and generated files.
18. As a user, I want a read to stop at the end of the requested window, so that reading the head of a 500 MB log is fast and uses little memory.
19. As a user, I want no whole-file size limit on `read_file`, so that "file too large" never stops the agent from looking at something.
20. As a user, I want the Tool Output Cap to default to 32 KiB, so that a few reads do not fill the model's context.
21. As a user, I want the line-number prefixes counted toward the cap, so that the cap is what the model actually receives.
22. As a user, I want `search_text` excerpts shortened to about 200 characters around the match, so that one long line cannot flood the context.
23. As the model, I want the excerpt centred on the match with `…` marking a cut side, so that the match itself is always visible and I can tell the line continues.
24. As a user, I want the whole `search_text` response bounded by the Tool Output Cap, with `truncated` set when cut, so that 100 matches cannot exceed it.
25. As the model, I want `search_text`'s `line` numbers counted exactly as `read_file` counts lines, so that a search hit's `line` is always a valid `offset`.
26. As a user, I want `edit` to work on any file up to the Mutating File Limit (1 MiB by default), so that changing one line of a 70 KB file works.
27. As a user, I want `write` to overwrite files up to the same limit, so that the diff preview works for real source and config files.
28. As a user, I want an existing file over the Mutating File Limit to be a Tool error before Tool Confirmation, so that I am never shown an unreviewable diff and memory stays bounded.
29. As a user, I want `edit`/`write` unaffected by `PA_MAX_READ_BYTES`, so that lowering the model's output budget never blocks an edit.
30. As a user, I want `shell` output to keep defaulting to the Tool Output Cap (now 32 KiB), with `PA_SHELL_MAX_OUTPUT_BYTES` still overriding, so that one knob controls what a Tool call hands the model.
31. As a user, I want `PA_MAX_READ_BYTES` and `PA_MAX_WRITE_BYTES` to keep their names and validation, so that my existing configuration keeps working.
32. As a user, I want `README.md`, `docs/ENV_VARS.md` and `.env.example` to describe the new meanings and defaults, so that the docs match the behavior.
33. As a Call Log reader, I want `read_file` and `search_text` results logged exactly as returned, so that the log still shows what the model saw.

## Requirements

- **R1 Read Window arguments.** `read_file` takes `path` (required), `offset`
  (integer, minimum 1, default 1) and `limit` (integer, minimum 1, default
  500), declared in the Tool Registry schema. Invalid values are the existing
  "invalid arguments" error from schema validation.
- **R2 Line model.** A line is a run of bytes ending in `\n`, or the final run
  of bytes at end of file when it does not end in `\n`. A file's line count is
  the number of such lines (`"a\nb\n"` and `"a\nb"` both have 2; an empty file
  has 0). Line numbers start at 1.
- **R3 Numbered content.** Each returned line is `<number>\t<line>`, where
  `<line>` is the line exactly as in the file including its own terminator
  (`\n` or `\r\n`; none for an unterminated last line). `content` is the
  concatenation of the returned lines.
- **R4 Result shape.** A successful read returns
  `{"content": str, "has_more": bool, "next_offset": int | null}`.
  `has_more` is true when at least one line exists after the last returned
  line; `next_offset` is the number of the first line not returned when
  `has_more` is true, else null. No total line count is returned (brief
  decision 6).
- **R5 Streaming.** The file is read incrementally from its start and reading
  stops as soon as the window is complete and it is known whether one more
  line exists. There is no whole-file size limit and the "file exceeds the
  N-byte read limit" error no longer exists for `read_file`. Memory used is
  bounded by the window and the Tool Output Cap, never by file size or line
  length (a single huge line is skipped past in bounded chunks).
- **R6 Tool Output Cap on `read_file`.** The UTF-8 byte length of `content`,
  prefixes included, never exceeds the Tool Output Cap (the configured
  `PA_MAX_READ_BYTES`), except as allowed by R7. When the next whole line
  would push it over, the window ends before that line; `has_more` is true and
  `next_offset` is that line's number.
- **R7 Over-cap single line.** When the first line of a window alone exceeds
  the cap, the window is that one line: `<number>\t<kept text>[...truncated]`
  with no terminator, where the kept text is the longest prefix of the line
  that keeps the whole returned line within the cap, cut on a UTF-8 character
  boundary (possibly empty when the cap is smaller than the prefix and marker,
  the only case the cap is exceeded). `has_more`/`next_offset` then refer to
  the line after it. The marker is the same `[...truncated]` `shell` uses.
- **R8 Binary / non-UTF-8.** Only the bytes that go into the returned content
  are checked: a NUL byte, or bytes that are not valid UTF-8, is the existing
  "file is binary or not valid UTF-8" Tool error. A multibyte character split
  by an R7 cut is dropped, not treated as invalid. Bytes after the window are
  never checked (brief decision 7).
- **R9 Offset past end.** When `offset` is greater than the file's line count,
  the call is the Tool error `offset <offset> is past end of file (<count>
  lines)` (singular `line` when the count is 1). Exception: an empty file read
  at `offset` 1 returns `{"content": "", "has_more": false, "next_offset":
  null}`.
- **R10 Tool descriptions.** The `read_file` description states: it returns a
  window of lines chosen by 1-based `offset` and `limit` (default 500); every
  line starts with its line number and a TAB, which is not part of the file;
  continue from `next_offset` while `has_more` is true; output is capped and
  cut at a line boundary. The `edit` description states: never include the
  line-number prefix shown by `read_file` in `old_string`. `edit` does not
  strip prefixes (brief decision 4).
- **R11 `search_text` excerpts.** Each match's `excerpt` is the matched line
  when it is at most 200 characters (constant, no env var). A longer line is
  cut to a 200-character slice centred on the first occurrence of the search
  text in that line (clamped to the line's ends), with `…` (U+2026) prepended
  when the slice does not start at the line's start and appended when it does
  not reach the line's end. The line's `\n` terminator (and a `\r` before it)
  is never part of the excerpt.
- **R12 `search_text` line numbering.** `search_text` numbers lines by the R2
  line model, so every `line` it reports is a valid `read_file` `offset` for
  that file. Matching rules, depth and the 100-result limit are unchanged.
- **R13 `search_text` output bound.** Matches are accumulated in the existing
  order; a match is not added when the running total of the UTF-8 byte length
  of each kept match's JSON encoding would exceed the Tool Output Cap. When
  matches are dropped for this reason or the 100-result limit, `truncated` is
  true.
- **R14 Mutating File Limit.** `PA_MAX_WRITE_BYTES` (default now 1 MiB =
  1048576) bounds the existing file `edit` loads and the existing file
  `write` loads for its diff preview (an existing file larger than it is the
  Tool error `file exceeds the <N>-byte write limit`, before Tool
  Confirmation), as well as the resulting content (unchanged
  `content exceeds the <N>-byte write limit` error). `edit` and `write` no
  longer read through `PA_MAX_READ_BYTES` at all.
- **R15 Defaults and `shell`.** `PA_MAX_READ_BYTES` defaults to 32 KiB
  (32768). Both env vars keep their names and positive-integer validation
  (brief: out of scope to rename). `PA_SHELL_MAX_OUTPUT_BYTES` still defaults
  to the effective `PA_MAX_READ_BYTES` and still overrides it; no `shell` code
  change is expected beyond the new default flowing through.
- **R16 Docs.** `README.md` (Workspace Tools, Mutating Tools, shell sections),
  `docs/ENV_VARS.md` and `.env.example` describe: `PA_MAX_READ_BYTES` as the
  Tool Output Cap, default 32768, applying to `read_file`, `search_text` and
  by default `shell`; `read_file`'s `offset`/`limit`, numbered lines,
  `has_more`/`next_offset`, and no file size limit; `search_text` excerpt
  shortening; `PA_MAX_WRITE_BYTES` as the Mutating File Limit, default
  1048576, applying to the existing file and the result of `write`/`edit`;
  `PA_SHELL_MAX_OUTPUT_BYTES`'s example value 32768.

## Implementation Decisions

- **Workspace tools module** holds all behavior changes. `read_file` gets its
  own streaming line reader (binary-mode, line by line with a bounded read
  length so an over-cap line is never held whole); it no longer uses the
  shared whole-file text reader. The whole-file reader remains for `edit`,
  `write` and `search_text`; its limit parameter is now fed the Mutating File
  Limit by `edit`/`write`, and its over-limit error text becomes the "write
  limit" wording of R14. `search_text` keeps reading whole files (out of
  scope to change) but splits lines per R2.
- **Configuration** keeps the single `WorkspaceConfig` with `max_read_bytes`
  and `max_write_bytes`; only the two default constants change (32 KiB,
  1 MiB). `main` wiring and `configure_shell` are unchanged.
- **Tool Registry** changes only the `read_file` schema (R1) and the
  `read_file` and `edit` descriptions (R10). No new Tool, no execution-path
  change.
- **Truncation marker** is the existing `[...truncated]` constant; reuse it
  rather than defining a second copy (it may move to a shared place in the
  tools package if importing it from `shell` would create a cycle).
- **Excerpt constant**: a module-level `200`-character constant; the ellipsis
  is extra to those 200 characters. Centring uses the match index found in
  the casefolded line, clamped to the original line; for the rare characters
  whose casefold changes length the slice may be off by a few characters,
  which is acceptable for an "about 200 characters" excerpt.
- **Byte measurement**: `read_file` measures the UTF-8 length of `content`
  only (the small fixed JSON envelope is not counted); `search_text` measures
  each match's compact JSON encoding without ASCII escaping. Both are a
  deliberate, simple reading of "the most bytes one Tool call hands to the
  model".
- **Call Log**: no schema change; Tool execution entries record the new
  result shapes as returned.

## Testing Decisions

- Good tests assert external behavior only: the `ToolResult` content and
  `is_error` returned for a Tool call, file bytes on disk after a Mutating
  Tool, whether the `confirm` callback was called, and configured defaults -
  never the internal reader.
- **One seam: `tools.execute_batch`** (existing, highest seam for Tools), with
  `workspace.configure_workspace(tmp_path, <read cap>, <write limit>)` to set
  small caps. Prior art: `tests/test_workspace_tools.py`
  (`test_read_file_returns_complete_text_and_rejects_binary_oversize_and_unsafe_targets`,
  `test_search_text_is_literal_case_insensitive_bounded_and_skips_binary_directory_files`,
  `test_write_content_over_the_limit_is_an_error_before_confirm_is_called`,
  the `test_edit_*` tests). Existing assertions that encode the old
  behavior (whole-file `{"content": ...}`, "file exceeds" on read, 64 KiB
  defaults) are updated, not kept alongside.
- Streaming (R5) is proven behaviorally: a window read from a file whose bytes
  after the window are binary/invalid succeeds; a file larger than any cap
  (for example several MB, or one multi-MB line) is readable at offset 1.
- Default values are asserted through `configure_workspace` with no limits
  (prior art: `test_workspace_configuration_defaults_and_rejects_invalid_limits`),
  and the `shell` default through the existing
  `test_shell_max_output_bytes_defaults_to_the_effective_max_read_bytes_when_unset`
  / `tests/test_main.py` shell-config tests, adjusted only if they hard-code
  64 KiB.
- The full offline suite must pass.

## Out of Scope

As the brief: a total line count in `read_file`'s result; `edit` stripping
line-number prefixes; byte-offset, regex or section reads; changes to
`list_files`, or to `search_text`'s matching rules, depth or 100-result limit;
an env var for the excerpt length; renaming `PA_MAX_READ_BYTES` /
`PA_MAX_WRITE_BYTES`. Also out of scope: streaming or bounding `search_text`'s
per-file read, and any change to the `shell` Tool's code.

## Further Notes

- Two edge cases the brief did not spell out were decided here as the direct
  reading of settled decisions: an empty file at offset 1 is a normal empty
  window (R9), since "past end of file" cannot sensibly apply to reading the
  start of an empty file; and `search_text` counts lines with the same `\n`
  model as `read_file` (R12), which is what the brief's "matching
  `search_text`'s `line`" requires. For ordinary `\n` and `\r\n` files this is
  identical to the previous numbering; only exotic separators (lone `\r`,
  form feed, U+2028 and similar) number differently.
- The Tool Output Cap can be exceeded only in the degenerate R7 case of a cap
  smaller than a line-number prefix plus the marker.
- An offset-past-end error on a huge file reads to the end to count lines;
  that cost is accepted by brief decision 8.
