# 0022 — webfetch, Todo List, regex/glob search

## Goal

Three small capabilities picked from the opencode comparison (`docs/research/done/2026-09-23-opencode-feature-comparison.md`): let the model read a web page, keep its own checklist on long tasks, and search the workspace precisely. Also fix a proven defect: `list_files(".")` on this repo returns 96 of 100 results from `.git/` and never reaches `src/`.

## Scope

### `webfetch` (Network Tool)

- Parameter `url` only; `http`/`https` only, any other scheme is a Tool error. Localhost and private networks are allowed.
- Requires Tool Confirmation showing the URL, same flow as `shell` (non-interactive EOF rejects). Registered by default, no env var.
- One GET, redirects followed. Result `{url, status, content_type, content, truncated}`, `url` being the final URL.
- HTML is converted to plain text with the stdlib `html.parser`, dropping `script`/`style`/`nav` (and similar non-content elements). `text/*`, JSON and markdown pass through. Binary types (images, PDF, ...) are a Tool error.
- `content` is bounded by the Tool Output Cap: cut with the `[...truncated]` marker and `truncated: true`. No pagination.
- Fixed constants: 30 s timeout, 5 MiB download limit. HTTP 4xx/5xx, timeout, and exceeding the download limit are Tool errors (status included when there is one).
- Uses stdlib `urllib`, like the Providers. No new dependency.

### `todo` Tool and Todo List

- `todo(todos)` replaces the whole list. Item `{content, status}`, status `pending | in_progress | completed | cancelled`. No priority. An empty list is valid (clears it).
- Tool description tells the model when to use it (3+ step tasks) and to keep at most one item `in_progress`; that rule is not validated.
- No Tool Confirmation.
- The REPL prints a compact checklist after each update.
- The Todo List belongs to the Conversation: `/undo` restores the list from before the undone turn (so `/retry` does too), `/clear` empties it, Resume rebuilds it from the Call Log, Compression leaves it unchanged.
- Sent in the System Prompt while any item is `pending` or `in_progress`; omitted when empty or all finished. No `todoread` Tool.

### `search_text` / `list_files`

- `search_text` gains `regex: bool` (default `false`). Literal behaviour is unchanged when false. Regex stays case-insensitive; an invalid regex is a Tool error. Excerpts centre on the first match either way.
- `search_text` gains optional `glob`; `list_files` gains optional `pattern`. Shared semantics, case-sensitive: no `/` in the pattern matches the file name at any depth (`*.py`); with `/` it matches the path relative to the searched directory (`src/**/test_*.py`). Filtering happens before the 100-result limit.
- A directory walk skips `.git`, `.venv`, `node_modules`, `__pycache__` when it meets them below the requested path. An explicitly requested path inside one of them is still walked/read.
- Result ordering stays by path.
- Docs: `README.md` Tool list reflects the new Tools and parameters.

## Out of scope

- Markdown conversion or link preservation in `webfetch`; `websearch`; POST or custom headers.
- Paginating a fetched page.
- Honouring `.gitignore`.
- A `todoread` Tool, todo priorities, validating the single-`in_progress` rule.
- A regex timeout.
- mtime ordering of `list_files` results.

## Settled decisions

1. **`webfetch` is confirmed** despite being read-only: a prompt-injected page can make the model encode workspace content into a URL. Showing the URL costs one keypress and closes that path.
2. **New term Network Tool** rather than stretching Mutating Tool; Tool Confirmation now covers Mutating and Network Tools.
3. **Plain text via stdlib, not markdown**: no new dependency; lost links are acceptable for now.
4. **Truncate, don't paginate** pages: paging would re-download per call; `curl` via `shell` covers the rare full-page need.
5. **Regex is opt-in** (`regex: true`) so literal searches like `foo(` keep working without escaping.
6. **Glob is a parameter, not a new Tool**: reuses the walk's depth/result bounds and keeps the Tool count down. Gitignore-style semantics (name-anywhere vs. path) is what models already expect from ripgrep.
7. **Fixed skip list, not `.gitignore`**: four names fix the proven flood with no dependency. Explicit paths still work, so the "Git-ignored files remain readable" decision holds.
8. **Todo List in the System Prompt**, not a `todoread` Tool: survives Compression, always visible, one Tool fewer. Only while unfinished, so a done list stops costing tokens.
9. **Todo List follows the Conversation** (undo/clear/resume): a list saying "done" for an undone turn would be inconsistent state.
10. **Glob is case-sensitive** while `search_text` content matching stays case-insensitive: file names follow Unix convention.

## Open questions

None — grilling frontier closed and confirmed by the user on 2026-09-25.

## Known issues

- A pathological regex can hang the REPL (Python `re` has no timeout). Accepted.
- `webfetch`'s 30 s total deadline covers reading the body only; DNS, connect, headers and chunk-size lines are bounded per socket operation, so a hostile server can hold a fetch longer (Ctrl-C still interrupts). Accepted.
- Auto-Compress has no dedicated Todo List test; it shares the Compression path that is tested.

## Follow-ups (not part of this feature)

- **`shell` guardrails** (user request, 2026-09-25): completed in feature 0023-shell-guardrails after separate discovery. It adds Strong Confirmation for recognized dangerous commands and does not add a sandbox or blocklist.
