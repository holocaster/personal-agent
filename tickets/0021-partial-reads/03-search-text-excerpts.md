# 03: search_text excerpts centred on the match and bounded by the Tool Output Cap

**What to build:** `search_text` no longer leaks whole long lines: each
match's `excerpt` is about 200 characters centred on the match with `…` on a
cut side, the whole response stays within the Tool Output Cap (`truncated`
set when cut), and every reported `line` is a valid `read_file` `offset`.
Searching a minified-JSON file returns a small, usable result.

**Blocked by:** 02 (Read Window) - `line` numbers must follow the line model
`read_file` introduces there, and the cap default this ticket relies on and
documents is set there.

**Spec:** `docs/specs/0021-partial-reads.md` (Requirements R11-R13, R16 for
the `search_text` part; Implementation Decisions: Workspace tools module,
Excerpt constant, Byte measurement; Testing Decisions); **ADRs:** none.

- [x] A matched line of at most 200 characters is the excerpt unchanged; a
  longer one is a 200-character slice centred on the first occurrence of the
  search text, clamped to the line's ends, with `…` (U+2026) prepended /
  appended on each cut side. The `\n` terminator and a `\r` before it are
  never in the excerpt. The 200 is a module constant, no env var (R11).
- [x] Lines are numbered by the `\n` line model shared with `read_file`, so a
  reported `line` read back with `read_file(path, offset=line, limit=1)`
  returns that line. Matching rules, depth and the 100-result limit are
  unchanged (R12).
- [x] Matches stop being added once the running total of each kept match's
  compact JSON encoding (UTF-8, no ASCII escaping) would exceed the Tool
  Output Cap; `truncated` is true when cut by the cap or by the 100-result
  limit (R13).
- [x] `README.md` Workspace Tools section describes excerpt shortening and
  that `search_text` output is bounded by the Tool Output Cap (R16).
- [x] Tests at the `tools.execute_batch` seam: short line unchanged; long line
  with the match near the start, middle and end (correct `…` sides, match
  visible); a small cap truncates the match list with `truncated` true; a
  search hit's `line` round-trips through `read_file`. Existing
  `search_text` test still passes. Full offline suite passes.
