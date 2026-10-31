# 0022 - webfetch, Todo List, regex/glob search

Brief: `docs/briefs/0022-web-todo-search.md` (all decisions settled; referenced
below as "brief decision N"). Extends `docs/specs/0009-workspace-tools.md` and
`docs/specs/0021-partial-reads.md` (`list_files`, `search_text`),
`docs/specs/0016-write-tools.md` and `docs/specs/0018-shell-tool.md` (Tool
Confirmation), `docs/specs/0014-turn-controls.md`,
`docs/specs/0012-session-resume.md` and `docs/specs/0020-auto-compress.md`
(Undo, Retry, clear, Resume, Compression). Vocabulary (Network Tool, Todo List,
Tool Confirmation, System Prompt, Workspace Tools, Tool Output Cap,
Conversation, Compression, Resume, Undo, Retry) is in `docs/CONTEXT.md`
("Workspace search" and "Tool boundary" decisions included). No ADR applies or
is added.

## Problem Statement

The model cannot read a web page, so a task like "check what this doc page
says" needs `curl` through `shell` and returns raw HTML. On a long multi-step
task the model has nowhere to keep its own plan, so it loses track of steps,
especially after Compression. And workspace search is imprecise: `search_text`
only does literal matching, neither Tool can filter by file name or path, and
a root `list_files(".")` on this repo returns 96 of its 100 results from
`.git/` and never reaches `src/` - a proven defect.

## Solution

A new Network Tool, `webfetch(url)`, GETs one `http`/`https` URL after Tool
Confirmation shows the URL, and returns the page as plain text (HTML converted
with the stdlib parser), bounded by the Tool Output Cap. A new `todo(todos)`
Tool lets the model write its own Todo List, which the REPL prints as a
compact checklist and which is sent in the System Prompt while it has
unfinished items; the list follows the Conversation through `/undo`,
`/retry`, `/clear`, Resume and Compression. `search_text` gains opt-in
`regex` and a `glob` file filter, `list_files` gains a glob `pattern`, and
every directory walk skips `.git`, `.venv`, `node_modules` and `__pycache__`
below the requested path.

## User Stories

### Workspace search

1. As a user, I want `list_files(".")` to skip `.git`, `.venv`, `node_modules` and `__pycache__`, so that a root listing shows my source files instead of 96 Git objects.
2. As the model, I want `search_text` over a directory to skip the same directories, so that matches come from the project, not from vendored or generated files.
3. As the model, I want to still list or search inside `.git` (or another skipped directory) when I name it explicitly as `path`, so that Git-internal or dependency files remain reachable when I really need them.
4. As the model, I want a file path inside a skipped directory to stay readable by `read_file` and searchable by `search_text`, so that the skip list never blocks an explicit request.
5. As the model, I want `list_files` to accept a glob `pattern`, so that I can list only `*.py` files without paging through everything.
6. As the model, I want a pattern without `/` to match the file name at any depth, so that `*.py` behaves the way ripgrep and gitignore taught me.
7. As the model, I want a pattern with `/` to match the path relative to the searched directory, so that `src/**/test_*.py` selects exactly the files I mean.
8. As the model, I want `**` to match zero or more whole directories and `*` to stay within one path segment, so that path patterns are precise.
9. As the model, I want glob matching to be case-sensitive, so that it follows Unix file-name convention (brief decision 10).
10. As the model, I want `search_text` to accept the same `glob` filter with the same meaning, so that I learn one pattern syntax for both Tools.
11. As the model, I want filtering to happen before the 100-result limit, so that a filtered listing is not cut short by files the filter would have removed.
12. As the model, I want results to stay ordered by path, so that listings remain predictable across calls.
13. As the model, I want `search_text` to stay literal by default, so that searching for `foo(` keeps working without escaping (brief decision 5).
14. As the model, I want `regex: true` to switch `search_text` to a regular expression, so that I can search for patterns like `def \w+_tool`.
15. As the model, I want regex search to stay case-insensitive like literal search, so that switching modes does not change casing behaviour.
16. As the model, I want an invalid regex to be a Tool error naming the problem, so that I can correct the expression.
17. As the model, I want the excerpt of a regex hit centred on the first match in the line, so that the match is always visible even in a long line.
18. As a user, I want `README.md` to document `pattern`, `glob`, `regex` and the skip list, so that the docs match the behaviour.

### webfetch

19. As the model, I want a `webfetch(url)` Tool, so that I can read a documentation page or an API response the user points me to.
20. As a user, I want `webfetch` registered by default with no env var, so that it works out of the box like `shell`.
21. As a user, I want every `webfetch` to require Tool Confirmation showing the exact URL, so that a prompt-injected page cannot make the model smuggle workspace content out through a URL without me seeing it (brief decision 1).
22. As a user, I want only an explicit `y`/`yes` to approve a fetch, and end of input to reject it, so that the gate behaves exactly like `shell`'s.
23. As the model, I want a rejected fetch to come back as the usual rejection Tool error, so that I can continue the turn without assuming the fetch happened.
24. As the model, I want a URL with any scheme other than `http`/`https` to be a Tool error before the user is asked, so that `file://` and similar never reach the prompt.
25. As a user, I want localhost and private-network URLs allowed, so that the model can read my local dev server's pages (Tool Confirmation is the gate).
26. As the model, I want redirects followed and the final URL returned as `url`, so that I know where the content actually came from.
27. As the model, I want HTML converted to plain text with scripts, styles, navigation and similar non-content elements dropped, so that the page's readable text is what enters the Conversation.
28. As the model, I want `text/*`, JSON and markdown returned as they are, so that API responses and raw docs are not mangled.
29. As the model, I want a binary response (image, PDF, ...) to be a Tool error naming its type, so that I never receive garbage bytes.
30. As a user, I want the returned content bounded by the Tool Output Cap with the `[...truncated]` marker and `truncated: true`, so that one page cannot flood the context (brief decision 4).
31. As the model, I want the result to carry `status` and `content_type`, so that I can tell what I received.
32. As the model, I want HTTP 4xx/5xx to be a Tool error including the status, so that a 404 is not mistaken for content.
33. As a user, I want a fixed 30 s timeout, so that a hanging server cannot stall the REPL.
34. As a user, I want a fixed 5 MiB download limit that is a Tool error when exceeded, so that a huge response cannot exhaust memory.
35. As a user, I want `webfetch` built on stdlib only (`urllib`, `html.parser`), so that no dependency is added (brief decision 3).
36. As a Call Log reader, I want `webfetch` calls and results logged like every other Tool execution, so that I can audit what was fetched.
37. As a user, I want `README.md` to document `webfetch` and that it is a Network Tool gated by Tool Confirmation, so that I know what it can do.

### Todo List

38. As the model, I want a `todo(todos)` Tool that replaces the whole Todo List, so that I can keep my own checklist on a long task.
39. As the model, I want each item to be `{content, status}` with status `pending`, `in_progress`, `completed` or `cancelled`, so that I can track progress per step.
40. As the model, I want an empty list to be valid and clear the Todo List, so that I can drop a plan I no longer need.
41. As the model, I want the Tool description to tell me to use it for tasks of three or more steps and to keep at most one item `in_progress`, so that I use it the intended way.
42. As the model, I want an invalid list (unknown status, missing field, extra field) to be the normal "invalid arguments" Tool error, so that the list never holds malformed items.
43. As a user, I want `todo` to run without Tool Confirmation, so that the model's bookkeeping never interrupts me.
44. As a user, I want the REPL to print a compact checklist after each successful update, so that I can follow the model's plan as it works.
45. As the model, I want the current Todo List in the System Prompt while any item is `pending` or `in_progress`, so that I always see my plan, including after Compression (brief decision 8).
46. As a user, I want the Todo List left out of the System Prompt when it is empty or every item is finished, so that a done list stops costing tokens.
47. As the model, I want an update to be visible in the System Prompt of the very next exchange in the same turn, so that my plan is current while I work through Tool rounds.
48. As a user, I want `/undo` to restore the Todo List as it was before the undone turn, so that the list never claims work from a removed turn is done (brief decision 9).
49. As a user, I want `/retry` to do the same, since it Undoes a successful last turn first, so that a retried task starts from the list it originally started from.
50. As a user, I want `/clear` to empty the Todo List, so that a fresh conversation starts with no leftover plan.
51. As a user, I want Resume to rebuild the Todo List from the Call Log, so that a resumed Session continues with the same plan.
52. As a user, I want Compression (manual or Auto-Compress) to leave the Todo List unchanged, so that the plan survives while old turns are summarized.
53. As a user, I want a turn that fails or is interrupted to leave the Todo List as it was before that turn, so that the list always matches the Conversation.
54. As a user, I want no separate `todoread` Tool, so that the Tool count stays down (brief decision 8).
55. As a user, I want `README.md` to document `todo` and the Todo List lifecycle, so that I know how it behaves.

## Requirements

### Workspace search

- **R1 Walk skip list.** Every directory walk (`list_files`, `search_text` on
  a directory) does not descend into a directory named exactly `.git`,
  `.venv`, `node_modules` or `__pycache__` that it meets below the requested
  directory. The requested directory itself is always walked, even when it
  is (or is inside) one of those names. Explicit file paths (`read_file`,
  `search_text` on a file) are unaffected. Existing bounds (depth 8, 100
  results, symlink and exclusion rules) are unchanged.
- **R2 Glob semantics.** One shared, case-sensitive matcher. A pattern with
  no `/` matches a file's name at any depth. A pattern containing `/` matches
  the file's path relative to the searched directory (the `path` argument),
  segment by segment: `**` as a whole segment matches zero or more
  directories; `*`, `?` and `[...]` never match `/`. The pattern is matched
  as given, with no normalization.
- **R3 `list_files(pattern)`.** Optional `pattern` (string, `minLength` 1).
  When given, only walked files matching it (R2) are kept. Filtering happens
  before the 100-result limit, so `truncated` reflects the filtered count.
  Returned paths stay relative to the Workspace Root and ordered by path.
- **R4 `search_text(glob)`.** Optional `glob` (string, `minLength` 1). When
  `path` names a directory, only walked files matching it (R2) are searched,
  filtered before any matching or result limit. When `path` names a file,
  `glob` is ignored.
- **R5 `search_text(regex)`.** Optional `regex` (boolean, default `false`).
  When false, matching is exactly the existing literal, case-insensitive
  behaviour. When true, `text` is compiled as a Python regular expression
  with case-insensitive matching and searched per line (the R2 line of
  feature 0021, without its `\n` terminator or a `\r` before it); an invalid
  expression is the Tool error `invalid regex: <reason>`, before any file is
  read. Excerpts (feature 0021 R11) centre on the first match in the line in
  both modes. Line numbering, the Tool Output Cap bound and the 100-result
  limit are unchanged.
- **R6 Search descriptions.** The Tool Registry schemas declare R3-R5's
  parameters; the `list_files` and `search_text` descriptions state the
  glob semantics in one sentence, that `search_text` is literal unless
  `regex` is true, and that `.git`, `.venv`, `node_modules` and
  `__pycache__` are skipped unless named as `path`.

### webfetch

- **R7 Registration.** `webfetch` is registered in the Tool Registry by
  default (no env var) with schema `{url: string, minLength 1}`, required,
  no additional properties. Its description says it GETs one `http`/`https`
  URL, returns the content as text (HTML converted to plain text), follows
  redirects, is capped, and requires the user's confirmation.
- **R8 URL validation.** Before Tool Confirmation: a URL whose scheme is not
  `http` or `https` (case-insensitive), or that has no host, is a Tool error
  and `confirm` is never called. No host restriction: localhost and private
  addresses are allowed.
- **R9 Tool Confirmation.** `webfetch` goes through the same
  prepare -> Tool Confirmation -> apply path as the Mutating Tools. The REPL
  shows `webfetch: <url>` and asks `Fetch this URL? [y/N] `. Only `y`/`yes`
  (case-insensitive, trimmed) approves; anything else, or end of input,
  yields the existing `change rejected by the user` Tool error with nothing
  fetched; Ctrl-C interrupts the turn as for other confirmations.
- **R10 Fetch.** One GET with a fixed identifying `User-Agent` (not
  model-controlled), redirects followed. A redirect to a scheme other than
  `http`/`https` is a Tool error. Fixed module constants: 30 s timeout, 5 MiB
  (5242880 bytes) download limit. Tool errors: HTTP status >= 400
  (`HTTP <status> <reason>`), a timeout, a body larger than the download
  limit (checked while reading; never buffered beyond limit + 1 bytes), and
  any other network failure (message includes the reason).
- **R11 Content.** The media type is the `Content-Type` header without
  parameters, lowercased. `text/html` and `application/xhtml+xml` are
  converted to plain text with the stdlib `html.parser`: the content of
  `script`, `style`, `noscript`, `template`, `svg`, `iframe` and `nav` is
  dropped; block-level elements and `<br>` break lines; runs of spaces are
  collapsed and more than one consecutive blank line is reduced to one;
  character references are decoded. `text/*` (including `text/markdown`),
  `application/json`, `application/*+json`, `application/xml`,
  `application/*+xml` and `application/javascript` pass through unchanged.
  Any other type, or a missing `Content-Type`, is the Tool error
  `unsupported content type: <type>`. Text is decoded with the header's
  `charset` when present and known, else UTF-8, replacing undecodable bytes.
- **R12 Result.** `{"url": <final URL>, "status": int, "content_type":
  <media type>, "content": str, "truncated": bool}`. When the UTF-8 length
  of `content` would exceed the Tool Output Cap (`PA_MAX_READ_BYTES`),
  `content` is cut on a character boundary so that it plus the
  `[...truncated]` marker fits within the cap, the marker is appended, and
  `truncated` is true. No pagination.

### Todo List

- **R13 `todo` Tool.** Registered by default, no Tool Confirmation. Schema:
  `todos` (required) is an array of objects `{content: string minLength 1,
  status: enum pending|in_progress|completed|cancelled}`, both required, no
  additional properties; an empty array is valid. A successful call returns
  `{"todos": <the list as given>}`. The description tells the model to use
  it for tasks of three or more steps, that each call replaces the whole
  list, and to keep at most one item `in_progress` (not validated).
- **R14 State belongs to the Conversation.** The current Todo List is the
  `todos` of the latest successful `todo` Tool result in the Conversation's
  turns; when there is none, it is the Todo baseline (R18), which starts
  empty. A `todo` error result never changes it. Updates made during a turn
  that fails or is interrupted do not persist, because that turn never
  enters the Conversation.
- **R15 System Prompt.** When the current Todo List has at least one
  `pending` or `in_progress` item, the System Prompt ends with a block
  headed `Todo List:` listing every item in order as
  `- [<status>] <content>`. Otherwise no Todo block is sent. The Compression
  call's System Prompt never carries it.
- **R16 Within a turn.** Every exchange of a routed turn uses the Todo List
  as of that exchange: the list at the start of the turn, replaced by each
  successful `todo` result of earlier Tool rounds in the same turn (the last
  one in a batch wins).
- **R17 REPL checklist.** A successful `todo` result is printed live in place
  of the generic Tool line: `tool> todo` followed by one line per item,
  `  [ ] ` pending, `  [~] ` in progress, `  [x] ` completed, `  [-] `
  cancelled, then the content, sanitized and cut to the existing 120-char
  Tool line limit; an empty list prints `tool> todo (empty)`. Colors and
  piped mode follow the existing Tool line rules. A failed `todo` call uses
  the generic error line.
- **R18 Lifecycle.** `/undo` (and the Undo `/retry` performs) restores the
  list as it was before the removed turn. `/clear` empties it (turns and
  baseline). A Compression, manual or Auto-Compress, leaves the current Todo
  List unchanged: before dropping turns it sets the Todo baseline to the
  list derived from the turns being dropped and the previous baseline, so a
  later `/undo` of a kept turn still restores the right list. Resume
  rebuilds turns, Conversation Summary and Todo baseline by replaying the
  Call Log with the same rules, so the resumed list equals the live list at
  the end of the last Run. No new Call Log entry type or field.

### Docs

- **R19 README.** `README.md` documents: the skip list, `list_files`
  `pattern`, `search_text` `glob` and `regex` (Workspace Tools section);
  `webfetch` as a Network Tool with its confirmation, limits, content
  handling and result shape; `todo`, the checklist and the Todo List
  lifecycle; the Tools section's list of always-offered Tools and the
  "only Tool-execution gate" sentence updated to cover `webfetch`.
  `docs/ENV_VARS.md` and `.env.example` need no change (no new env var).

## Implementation Decisions

- **Workspace tools module** holds R1-R5. The walk gets a fixed module-level
  set of skipped directory names applied to children only. The glob matcher
  is one private helper used by both Tools; Python 3.12 has no
  `glob.translate`/`PurePath.full_match`, so it splits pattern and relative
  path on `/` and matches segment by segment with `fnmatch.fnmatchcase`,
  recursing on a `**` segment. Regex mode compiles once with `re.IGNORECASE`
  and `re.error` becomes the Tool error. The excerpt helper takes the match
  start and length instead of the casefolded needle, so literal and regex
  hits share it; literal matching itself is untouched.
- **New `webfetch` module in the tools package** exposes a prepare step
  (validates the URL, builds the confirmation label and preview, touches no
  network) and an apply step (fetch, classify, convert, truncate). It reads
  the Tool Output Cap from the configured workspace, the way `shell` does,
  and reuses the existing `[...truncated]` constant. HTML conversion is a
  small `html.parser.HTMLParser` subclass. Redirects use `urllib`'s default
  handler plus a check that refuses a non-`http(s)` target (the stdlib
  handler would otherwise follow `ftp`). The timeout and download limit are
  module constants so tests can lower them.
- **Tool Registry** gains the `webfetch` and `todo` entries and the new
  search parameters/descriptions. The entry flag that routes a Tool through
  prepare -> Tool Confirmation -> apply is generalized to mean "requires
  Tool Confirmation" (it now covers the Network Tool), renamed accordingly;
  `execute_batch`'s behaviour is otherwise unchanged. `todo` is a plain
  function Tool.
- **New `todo` module in the tools package** owns everything Todo-shaped:
  the Tool function, deriving the current list from Conversation messages
  plus a baseline (R14), the System Prompt block (R15) and the checklist
  lines (R17). It keeps no global state; state lives in the Conversation and
  the baseline the REPL holds.
- **Router**: `route` takes the Todo List at turn start and threads it to
  the System Prompt builder, updating it after each Tool batch from
  successful `todo` results (R16). `compress` passes none (R15).
- **Terminal (REPL)** holds the Todo baseline next to the Conversation
  Summary, derives the current list from turns + baseline before each
  routed turn, updates the baseline on Compression and `/clear` (R18),
  prints the `todo` checklist through the existing Tool-result printer
  (R17), and asks `Fetch this URL? [y/N] ` for `webfetch` in the existing
  confirm callback (R9).
- **Call Log**: `load_conversation` also returns the Todo baseline, computed
  during the same replay (a `conversation_compressed` entry derives it from
  the turns it drops; `conversation_cleared` resets it). `main` passes it
  into the REPL with the resumed turns and summary. No schema change.
- **No new dependency**; no new env var.

## Testing Decisions

- Good tests assert external behaviour only: the `ToolResult` content and
  `is_error` of a Tool call, whether `confirm` was called, the System Prompt
  text a Provider receives, REPL output, and the Conversation rebuilt on
  Resume - never private helpers.
- **Seam 1: `tools.execute_batch`** (existing) with
  `workspace.configure_workspace(tmp_path, ...)`, for R1-R8, R10-R13. Prior
  art: `tests/test_workspace_tools.py` (list_files/search_text tests) and
  `tests/test_shell_tool.py` (confirm-callback tests). `webfetch` tests run
  a real `http.server.ThreadingHTTPServer` on `127.0.0.1` port 0 in a
  fixture (localhost is allowed by R8), serving HTML, JSON, markdown, a
  redirect, a 404, a binary type and an oversized body; timeout and download
  limit constants are monkeypatched small. No network outside localhost.
- **Seam 2: `route` / `run_repl` with the existing fake Provider transport**
  (`install_fake_urlopen`) for R9, R14-R18: scripted `todo` calls, then
  assert the next exchange's System Prompt, the printed checklist, and the
  list after `/undo`, `/retry`, `/clear`, `/compress` (and Auto-Compress) and
  after Resume (`call_log.load_conversation` + `run_repl(resumed=...)`).
  Prior art: `tests/test_routing.py` System Prompt tests,
  `tests/test_repl.py` confirm, undo/retry, compress and resume tests.
  Existing callers unpacking `load_conversation`'s two values are updated.
- Registry-wide tests (`test_every_registered_schema_passes_check_schema`,
  any Tool-name list assertion) cover the new entries.
- The full offline suite must pass.

## Out of Scope

As the brief: markdown conversion or link preservation in `webfetch`;
`websearch`; POST or custom headers; paginating a fetched page; honouring
`.gitignore`; a `todoread` Tool, priorities, validating the single
`in_progress` rule; a regex timeout; mtime ordering of `list_files`. Also:
any `shell` guardrail (brief follow-up, its own discovery), re-confirming
each redirect hop, reading an HTML page's `<meta charset>`, and a Todo List
in `/history` beyond the Tool calls it already shows.

## Further Notes

- Decided here as direct readings of the brief:
  - R14: an update in a failed or interrupted turn does not persist. The
    brief ties the list to the Conversation (decision 9) and requires Resume
    to rebuild it from the Call Log; only turns that entered the
    Conversation can give the same answer live and on Resume.
  - R18: the Todo baseline is what lets "Compression leaves it unchanged"
    and "`/undo` restores the list from before the undone turn" hold
    together after old turns (and their `todo` calls) leave the
    Conversation.
  - R11: "text/*, JSON and markdown pass through; binary is an error" is
    read as an allowlist of text-like types (adding XML and JavaScript,
    which are text); everything else, including a missing `Content-Type`,
    is an error.
  - R12: the cap includes the marker, like `read_file`'s over-cap line
    (feature 0021 R7).
  - R4: `glob` only filters directory walks; an explicit file `path` is
    searched as named.
  - R9: the URL confirmed is the requested one; redirects are followed
    without a second confirmation (the brief says "redirects followed").
- Known issue (brief): a pathological regex can hang the REPL; accepted.
- Hidden and Git-ignored files outside the four skipped directory names stay
  listed, so the existing hidden/ignored-files listing test keeps holding.
