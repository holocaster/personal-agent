# 0009 - Workspace Read Tools

## Goal

Let the Router inspect the project it was started for through a minimal,
read-only Toolset. Today its Tools can calculate and report time but cannot
ground an answer in the user's files. The feature must retain the existing
Tool Registry boundary rather than introducing MCP, shell access, or a general
filesystem capability.

## Scope

1. Add three built-in Workspace Tools to the existing Tool Registry:
   `list_files`, `read_file`, and `search_text`.
2. Resolve `ROUTER_WORKSPACE` once at startup. When unset, its value is `.`
   from the process's starting directory; the resolved root must exist and be
   a directory. An invalid value stops startup before any Provider call.
3. Accept only paths relative to the resolved Workspace Root. Reject absolute
   paths, traversal outside the root, and symlinks that resolve outside it.
4. Include hidden and Git-ignored files inside the root, except `.env`,
   `*.pem`, and `*.key`.
5. Keep fixed limits for depth (8) and returned results (100). Search only
   text files. `read_file` rejects a file larger than `ROUTER_MAX_READ_BYTES`;
   its default is 64 KiB when the environment variable is unset.
6. Return explicit Tool errors for invalid paths, unavailable files, binary
   search targets, bounds violations, and files over the read limit.

## Out of scope

- MCP, plugins, OAuth, or external Resources.
- Shell commands, writes, patches, deletes, or environment-variable reading.
- Configurable depth or result-count limits.
- Regex search, case-sensitive search, and partial reads of oversized files.
- Persisting the Workspace Root across Sessions.

## Settled decisions

- The three Tools remain available through the current Tool Registry and
  existing Provider/Call Log/REPL flow.
- `ROUTER_WORKSPACE` defaults to the directory where the process starts, not
  to the repository root or a model-selected directory.
- Workspace paths are relative only.
- `search_text` is a literal, case-insensitive text search and returns each
  matching file, line number, and excerpt.
- Oversized reads fail rather than silently truncating; the model can search
  or inspect another file instead.
- `ROUTER_MAX_READ_BYTES` is optional and defaults to 64 KiB.

## Open questions

None.
