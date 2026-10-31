## Problem Statement

The Router can use arithmetic and time Tools but cannot inspect the project
where it was started. Answers about local code or configuration therefore
cannot be grounded in the user's files. It needs a small, bounded read-only
way to inspect that project without exposing a shell, arbitrary filesystem
access, or MCP.

## Solution

Add three built-in Workspace Tools to the existing Tool Registry:
`list_files`, `read_file`, and `search_text`. At startup the application
resolves one Workspace Root from `ROUTER_WORKSPACE` (or `.` when unset) and
configures the Tools with it. Every model-supplied path is relative to that
root and every result is bounded. The normal Registry, Provider, Tool loop,
Conversation, and Call Log paths carry the Tools exactly as they do the
existing calculator and time Tools.

## User Stories

1. As a Router user, I want the model to list files in my started project, so that it can discover relevant project material.
2. As a Router user, I want the model to list a subfolder, so that it can narrow exploration without receiving unrelated files.
3. As a Router user, I want the model to read a small project file, so that its answer can use the file's actual contents.
4. As a Router user, I want the model to search project text literally without case sensitivity, so that it can find relevant code and configuration quickly.
5. As a Router user, I want search matches to name the file, line, and excerpt, so that the model can verify where a fact came from.
6. As a Router user, I want Workspace Tools to default to the directory in which I started the process, so that they operate on the project I chose rather than an inferred repository root.
7. As a Router user, I want an invalid Workspace Root reported before I enter a task, so that a configuration mistake does not produce an ungrounded session.
8. As a Router user, I want Tool paths constrained to the Workspace Root, so that a model cannot inspect unrelated files.
9. As a Router user, I want outbound symlinks rejected, so that a path that looks local cannot escape the Workspace Root.
10. As a Router user, I want ordinary hidden and Git-ignored project files available, so that useful local configuration is not silently omitted.
11. As a Router user, I want `.env`, PEM, and key files excluded, so that likely secrets are not supplied to a Provider.
12. As a Router user, I want bounded file listings and searches, so that one Tool result cannot consume the conversation.
13. As a Router user, I want an adjustable maximum readable file size with a safe default, so that I can tune the Tool for my project without receiving partial file contents.
14. As a Router user, I want clear Tool errors for unavailable, unsafe, binary, and oversized targets, so that the model can choose a valid next action.
15. As a Router user, I want the existing calculator, current-time Tool, Providers, and REPL behavior to continue working, so that adding project inspection does not change routing behavior.

## Implementation Decisions

### Workspace configuration

- `ROUTER_WORKSPACE` is read once after `.env` loading during application
  startup. When unset or empty, its source value is `.` and is resolved from
  the process's starting directory. The resolved Workspace Root must exist
  and be a directory. A failure prints a clear startup configuration error
  and exits before the REPL can route a task or call a Provider.
- `ROUTER_MAX_READ_BYTES` is an optional positive integer byte count. When
  unset or empty it is `65536` (64 KiB). A non-integer, zero, or negative
  value is a startup configuration error. The resolved root and byte limit
  are configured once for the Session; Workspace Tools never inspect
  environment variables themselves.
- Keep this configuration and the Workspace Tool functions in the Tool area
  (a small dedicated workspace helper is acceptable only if it keeps the
  Tool Registry declaration simple). Do not add a Provider, MCP, plugin, or
  general filesystem abstraction. The Registry remains the single source of
  each Tool's JSON Schema, description, and callable function.

### Tool contracts and bounds

- Add these JSON-Schema-validated Tool contracts to the existing Registry:
  - `list_files` accepts optional `path`, a relative directory path defaulting
    to `.`. It recursively returns regular files and safe in-root symlinked
    files below that directory, as workspace-relative POSIX-style paths,
    sorted deterministically. It does not follow directory symlinks.
  - `read_file` accepts required `path`, a relative regular-file path, and
    returns its complete UTF-8 text as `content` only when its byte size is at
    or below the configured read limit. It never truncates a file.
  - `search_text` accepts required non-empty `text` and optional `path`
    defaulting to `.`. The optional path may identify a directory or one file.
    It performs literal, case-insensitive matching in UTF-8 text files and
    returns sorted matches with workspace-relative `path`, 1-based `line`,
    and the complete matching-line `excerpt`.
- `list_files` and `search_text` search no deeper than eight levels below the
  requested directory and return at most 100 entries or matches respectively.
  Their result object includes a `truncated` boolean whenever more eligible
  results exist. The depth limit does not apply when `search_text` is given a
  single file. `read_file` is bounded solely by its byte limit.
- Text-file detection for search and reading is conservative: files with a
  NUL byte or invalid UTF-8 are binary/unreadable text targets. Directory
  searches skip such files; searching one such file returns an explicit Tool
  error. Reading one returns an explicit Tool error rather than decoding or
  altering its bytes.

### Workspace boundary and exclusions

- Resolve every supplied path against the Workspace Root before access. Only
  relative paths are valid; absolute paths, traversal that resolves outside
  the root, and any file symlink whose resolved target is outside the root are
  rejected with a Tool error. A missing path, wrong kind of path, inaccessible
  target, or bounds violation is likewise a Tool error. Directory symlinks
  are neither traversed nor advertised.
- Hidden and Git-ignored files under the root are eligible. Files whose
  basename is exactly `.env` or matches `*.pem` or `*.key` are excluded from
  all three Tools. `list_files` and directory search omit them; an explicit
  read or single-file search returns a clear excluded-file Tool error. The
  exclusions are basename matching as written and do not exclude files such
  as `.env.example`.
- Tool errors continue through the existing `ToolExecutionError` and
  per-call Registry behavior: a failed Workspace Tool produces one error
  result and does not stop its batch. The Call Log records its normal
  `tool_execution` entry and the Provider receives the normal Tool result.

### Integration and documentation

- The Provider-facing Tool definitions are still derived from the Registry,
  so all four Providers advertise the three Workspace Tools with no
  Provider-specific work. The Router's Tool loop, limits, callbacks,
  formatting, Conversation, and Call Log schema remain unchanged.
- README documents the two startup variables, defaults, the fixed depth and
  result limits, and the read-only/security boundary concisely.

## Testing Decisions

A good test drives a Tool through its public Registry execution path or a
complete scripted Router Tool round, then asserts the returned Tool result,
Provider follow-up message, startup result, or visible REPL output. It does
not assert traversal helper calls or private implementation details.

Use temporary workspace trees as the primary seam, configuring the Workspace
Root explicitly for Tool tests. Use the existing fake Provider/`urlopen`
seam for one end-to-end Tool loop, and the existing `main`/stderr test style
for startup validation. Existing `tests/test_tools.py`,
`tests/test_routing.py`, and `tests/test_main.py` are the prior art.

- Configuration: unset values resolve `.` and 64 KiB; a valid explicit root
  and limit are used; a missing path, non-directory root, and invalid read
  limit fail startup before a Provider call.
- Registry and flow: all three definitions advertise their schemas; a
  scripted model can call a Workspace Tool, receives its result in the
  follow-up exchange, and its Tool execution remains logged; existing Tools
  still execute unchanged.
- Listing: recursive deterministic file paths, requested-subfolder scope,
  hidden and Git-ignored inclusion, protected-file omission, depth eight,
  100-result bound/truncation, and safe handling of symlinks are covered.
- Reading: valid complete UTF-8 content, default and explicit size limits,
  over-limit rejection without partial content, missing/directory paths,
  protected files, binary files, absolute paths, traversal, and outbound
  symlinks are covered.
- Search: literal case-insensitive matching, sorted file/line/excerpt
  results, scoped directory and single-file search, binary-file skip versus
  single-binary-file error, protected-file behavior, depth, result bound, and
  invalid path errors are covered.
- Run the complete offline test suite. No live credentials, network calls,
  MCP server, or shell command is used by a Workspace Tool.

## Out of Scope

MCP, plugins, OAuth, external Resources, web access, shell commands, writes,
patches, deletes, environment-variable Tools, arbitrary filesystem access,
regex or case-sensitive search, partial oversized-file reads, configurable
depth or result-count limits, persistence of the Workspace Root across
Sessions, Provider changes, and Call Log schema changes.

## Further Notes

The three Workspace Tools are intentionally the whole first read surface.
Their bounded contracts are preferable to a generic file or command Tool:
the Router already has a Tool Registry that validates arguments, logs each
execution, and returns normal Tool errors to the model.
