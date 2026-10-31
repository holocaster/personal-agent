# 01: Workspace search: skip list, glob filters, opt-in regex

**What to build:** A root `list_files(".")` on this repo reaches `src/`
instead of returning 96 `.git/` entries: every directory walk skips `.git`,
`.venv`, `node_modules` and `__pycache__` below the requested path, while
naming one of them explicitly as `path` still works. The model can narrow
`list_files` with a glob `pattern` and `search_text` with a `glob` filter
(one shared, case-sensitive semantics), and can switch `search_text` to a
case-insensitive regular expression with `regex: true`. Literal search
behaves exactly as today.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0022-web-todo-search.md` (Requirements R1-R6, R19 for
the Workspace Tools section; Implementation Decisions: Workspace tools
module, Tool Registry; Testing Decisions: Seam 1); **ADRs:** none.

- [x] R1: a walk below the requested directory does not descend into a
  directory named exactly `.git`, `.venv`, `node_modules` or `__pycache__`;
  `list_files(".git")`, `search_text` with `path` inside `.venv`, and
  `read_file` of a file inside `.git` all still work. Depth, 100-result,
  symlink and exclusion rules unchanged; hidden files outside those names
  still listed.
- [x] R2: one shared case-sensitive glob matcher: no `/` matches the file
  name at any depth; with `/` matches the path relative to the searched
  directory segment by segment, `**` = zero or more directories, `*`/`?`/
  `[...]` never cross `/`.
- [x] R3: `list_files` optional `pattern` (`minLength` 1) filters before the
  100-result limit; `truncated` reflects the filtered count; paths stay
  Workspace-Root-relative and ordered by path.
- [x] R4: `search_text` optional `glob` (`minLength` 1) filters walked files
  before matching and limits; ignored when `path` names a file.
- [x] R5: `search_text` optional `regex` (boolean, default false). False is
  unchanged literal behaviour. True compiles `text` case-insensitively and
  matches per line without its terminator; an invalid regex is the Tool
  error `invalid regex: <reason>` before any file is read. Excerpts centre
  on the first match in both modes; line numbers, Tool Output Cap bound and
  100-result limit unchanged.
- [x] R6: Tool Registry schemas declare the new parameters; `list_files` and
  `search_text` descriptions state the glob semantics, literal-unless-regex,
  and the skip list.
- [x] R19 (part): `README.md` Workspace Tools section documents the skip
  list, `pattern`, `glob` and `regex`.
- [x] Tests at the `tools.execute_batch` seam: skip list below the root and
  explicit paths into skipped directories; name-only and path globs
  (including `**` matching zero directories, case sensitivity, `*` not
  crossing `/`); filter-before-limit with `truncated`; `glob` on a file path
  ignored; regex hit, case-insensitivity, anchors on a CRLF line, excerpt
  centring on a regex match in a long line, invalid regex error; existing
  literal-search tests unchanged. Full offline suite passes.
