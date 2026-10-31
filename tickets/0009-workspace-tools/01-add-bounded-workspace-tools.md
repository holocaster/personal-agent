# 01: Add bounded Workspace Tools

**What to build:** A user can start the Router in a project and have the
model list project files, read a bounded text file, or literally search text
through the existing Tool flow. The Session resolves one safe Workspace Root
at startup, errors clearly if it is invalid, and never exposes shell access,
writes, secrets matched by the agreed exclusions, or files outside that root.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0009-workspace-tools.md` (all sections); **ADRs:**
`docs/adrs/0002-hand-rolled-provider-contract.md`.

- [x] At startup after `.env` loading, resolve and validate
  `ROUTER_WORKSPACE` once (`.` from the starting directory when unset/empty)
  and configure it before the REPL can route a task; invalid/missing roots
  and invalid `ROUTER_MAX_READ_BYTES` values produce a clear non-zero startup
  error before any Provider call. An unset/empty read limit is 64 KiB; a set
  limit is a positive whole-byte count.
- [x] Add `list_files`, `read_file`, and `search_text` to the existing Tool
  Registry, with their JSON Schemas, descriptions, and callables declared
  together so all Providers advertise them through the existing Tool
  definitions. Keep calculator, current_time, Providers, Tool loop, Call Log
  schema, and REPL behavior unchanged.
- [x] `list_files` accepts optional relative directory `path`, defaults to
  `.`, recursively returns deterministic workspace-relative file paths to a
  maximum depth of eight and 100 results, and tells the model when the list
  was truncated.
- [x] `read_file` accepts required relative file `path` and returns complete
  UTF-8 `content` only when it is at or below the configured byte limit; it
  never returns a partial oversized file.
- [x] `search_text` accepts non-empty literal `text` and optional relative
  `path`, matches UTF-8 text case-insensitively, and returns deterministic
  workspace-relative file paths, 1-based lines, and matching-line excerpts;
  directory search is bounded to depth eight and 100 matches with truncation
  reported, while a single-file target is supported.
- [x] All path access is relative to the resolved Workspace Root: reject
  absolute paths, out-of-root traversal, outbound file symlinks, missing or
  wrong-kind targets, and inaccessible targets with normal per-call Tool
  errors; never follow directory symlinks. Include hidden and Git-ignored
  files, but omit exact `.env`, `*.pem`, and `*.key` basenames and return an
  explicit error if one is directly requested.
- [x] Treat NUL-containing or invalid-UTF-8 files as binary/unreadable:
  reject direct reads and single-file searches, and skip them when walking a
  search directory. Keep every Workspace Tool failure isolated to its call so
  another Tool in the same batch still executes and the existing Tool
  execution logging/result flow is retained.
- [x] Add focused temporary-workspace tests for startup configuration,
  schemas, listing, reading, searching, exclusions, limits, binary targets,
  traversal, symlinks, and error results; add one scripted Router Tool-round
  test proving the new Tool result reaches the Provider follow-up and the
  Call Log. Run the full offline suite.
- [x] Concisely document `ROUTER_WORKSPACE`, `ROUTER_MAX_READ_BYTES`, fixed
  limits, and the read-only boundary in README.
