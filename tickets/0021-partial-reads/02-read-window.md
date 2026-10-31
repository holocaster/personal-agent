# 02: read_file returns a Read Window bounded by the Tool Output Cap

**What to build:** `read_file(path, offset, limit)` returns a Read Window of
numbered lines with `has_more`/`next_offset`, read streaming with no
whole-file size limit, cut at the Tool Output Cap (`PA_MAX_READ_BYTES`, default
now 32 KiB) instead of rejected. The model can read a multi-MB log one window
at a time, jump to a line number, and keep going from `next_offset`; `shell`
output inherits the new 32 KiB default.

**Blocked by:** 01 (Mutating File Limit) - this ticket lowers
`PA_MAX_READ_BYTES` to 32 KiB, which must no longer affect `edit`/`write`, and
it reworks the same workspace file-reading code.

**Spec:** `docs/specs/0021-partial-reads.md` (Requirements R1-R10, R15, R16
for the `read_file`/`PA_MAX_READ_BYTES`/`shell` parts; Implementation
Decisions: Workspace tools module, Configuration, Tool Registry, Truncation
marker, Byte measurement, Call Log; Testing Decisions); **ADRs:** none.

- [x] `read_file` schema: `path` required, `offset` integer >= 1 default 1,
  `limit` integer >= 1 default 500 (R1).
- [x] Lines follow the R2 model; each returned line is `<number>\t<line>` with
  the line's own terminator kept; `content` is their concatenation (R3).
- [x] Result is `{content, has_more, next_offset}`; `next_offset` is the first
  line not returned when `has_more`, else null; no total line count (R4).
- [x] Read is streaming and stops once the window is complete and it is known
  whether another line exists; no whole-file size limit and no "file exceeds"
  error for `read_file`; memory bounded even for a single multi-MB line (R5).
- [x] UTF-8 length of `content` (prefixes included) stays within the cap; a
  window that would exceed it ends before the first line that does not fit,
  with `has_more` true and `next_offset` at that line (R6).
- [x] A first line alone over the cap is returned alone as
  `<number>\t<kept>[...truncated]`, cut on a character boundary, using the
  existing `[...truncated]` marker; `next_offset` is the following line (R7).
- [x] Only bytes in the returned content are checked for NUL / invalid UTF-8,
  giving the existing "file is binary or not valid UTF-8" error; a character
  split by an R7 cut is dropped, not an error (R8).
- [x] `offset` past the line count is the Tool error
  `offset <offset> is past end of file (<count> lines)` (`line` when 1); an
  empty file at offset 1 returns empty content, `has_more` false,
  `next_offset` null (R9).
- [x] `read_file` and `edit` Tool descriptions carry the R10 statements (window
  by 1-based offset/limit, prefix is not part of the file, continue from
  `next_offset`, output capped at a line boundary; never put the prefix in
  `old_string`). `edit` does not strip prefixes.
- [x] `PA_MAX_READ_BYTES` defaults to 32768; `shell` output still defaults to
  the effective value and `PA_SHELL_MAX_OUTPUT_BYTES` still overrides (R15).
- [x] `README.md` (Workspace Tools and shell sections), `docs/ENV_VARS.md` and
  `.env.example` describe `PA_MAX_READ_BYTES` as the Tool Output Cap (default
  32768; `read_file`, `search_text`, and by default `shell`), `read_file`'s
  `offset`/`limit`, numbered lines, `has_more`/`next_offset`, and no file
  size limit; `.env.example`'s `PA_SHELL_MAX_OUTPUT_BYTES` example is 32768
  (R16).
- [x] Tests at the `tools.execute_batch` seam cover each criterion above,
  including: a window read from a file whose bytes after the window are
  binary succeeds; a multi-MB file and a multi-MB single line are readable
  at offset 1; the default read cap via `configure_workspace`. The old
  whole-file `read_file` test is replaced, not kept. Full offline suite
  passes.
