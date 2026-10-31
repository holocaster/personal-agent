# User guide

Detailed behavior and Tool reference for personal-agent. Start with the [README](../README.md).

- [ChatGPT account and reasoning](#chatgpt-account-and-reasoning)
- [Model catalog](#model-catalog)
- [Project instructions](#project-instructions), [Skills](#skills) and [Subagents](#subagents)
- [Workspace Tools](#workspace-tools), [Mutating Tools](#mutating-tools) and [Network Tools](#network-tools)
- [Questions](#questions-during-a-task), [Memory](#memory) and [Todo List](#todo-list)
- [Terminal and sessions](#terminal-and-sessions), [Commands](#commands) and [Reports](#reports-and-streaming)
- [Context budgeting](#context-budgeting), [Errors](#errors-and-interruption) and [Call Log](#call-log)
- [Detailed audit](#detailed-audit-opt-in), [Session discovery](#session-discovery) and [MCP Resources](#local-mcp-resources)

## ChatGPT account and reasoning

`/connect chatgpt` connects your own ChatGPT account in the local browser, explains
plan use and offers an arrow-key model picker. `/models chatgpt` and
`uv run personal-agent --models chatgpt` list account choices without inference.
`/connect chatgpt enable-plan` requests plan permission explicitly; `different`
connects another account. `/disconnect chatgpt` revokes the session and keeps API
keys and route settings. Credentials stay in a private global store, outside
`.env`. Setup requires an interactive local terminal. A selected ChatGPT route
uses the same task, Tool, Subagent and Compression flow; eligibility depends on
your account. Plan exhaustion stops with `Cota atingida` until you `/retry` or
select another Provider.

For ChatGPT reasoning, `/reasoning` lists the current preference, supported
levels and model default. `/reasoning high` (or another advertised level) saves
the choice for later tasks, retries, Subagents and Compression; `/config` also
offers `reasoning`. `/reasoning auto` restores the service default. The setting
is `PA_CHATGPT_REASONING_EFFORT=auto` by default and applies only to ChatGPT.

## Model catalog

Browse eligible [Models.dev](https://models.dev/) offerings without API keys,
a Session or any model call. Providers are `openrouter`, `openai`,
`anthropic` and `gemini` (Models.dev `google`); IDs are shown exactly.

```bash
uv run personal-agent --models openrouter --search claude
uv run personal-agent --refresh-models                    # refresh, then exit
uv run personal-agent --refresh-models --models gemini    # refresh, then list
```

The catalog is cached at `~/.personal_agent/models-dev.json` and used at any
age with no network request; only a missing or unusable cache triggers one
bounded fetch of `https://models.dev/api.json?type=all`. A failed refresh
exits non-zero and keeps the previous cache. Listed models need declared Tool
calling, text input/output, positive limits and a non-deprecated status;
alpha/beta labels are shown. Listing proves neither account access nor
System/Streaming support. Searches are literal, case-insensitive, on ID or
name, and show at most 100 rows.

In a Session, `/models [provider] [query]` searches the same list (current
Provider by default) and `/models refresh` refreshes it without changing the
pair. If a refresh drops or disqualifies the current pair, it stays selected,
but tasks, `/retry` and `/compress` are blocked locally with the reason until
`/model` selects an eligible pair or a later refresh admits it again.

## Project instructions

The CLI loads Workspace Root `AGENTS.md`, or `CLAUDE.md` only when AGENTS.md
is absent. Neither file is required. References such as `@rules`,
`[@Narquia.md]`, `@"path with spaces"` and `[@'path with spaces']` import
UTF-8 text recursively, relative to each containing file. Names and extensions
are unrestricted; sources appear in order, with canonical duplicates included once.

References start at the beginning of text or after whitespace or `(`.
Unquoted paths stop at whitespace, parentheses, brackets, quotes or backticks;
other punctuation belongs to the filename. Quotes preserve exact names and
allow escaping their enclosing quote or a backslash. Bracketed forms require
an immediate closing `]`. Emails, inline backtick code and fenced code remain literal.

Imports must be regular files inside the Workspace Root; in-root `..` and file
symlinks work. Absolute/URI paths, external targets, `.env`, `*.pem`, `*.key`,
invalid UTF-8 and NUL are rejected. Limits: 64 KiB per file, 256 KiB of distinct
source bytes, 64 sources, 16 files per active chain and 512 KiB expanded text.
Cycles and malformed/missing/unreadable imports fail visibly without truncation.

Sources are reported without their bodies. Invalid startup or Resume stops
before Session activity; later failures preserve the task for repair and `/retry`.
Instructions reload before each task and explicit Retry, remaining fixed during
Attempts, Tools and Compression. Full instructions count toward ordinary Context
Budget; summary calls omit them. User requests and existing mode,
Tool Confirmation and workspace gates retain priority.

## Skills

Put a `SKILL.md` with YAML `name` and `description` frontmatter plus instructions
in `.agents/skills/<name>/` under the Workspace Root or `~/.agents/skills/<name>/`.
Each file can be at most 32 KiB. Global skill directories can be symlinks to
directories within your home; each `SKILL.md` must stay within its resolved skill directory.
Use `/skills` to list effective skills (a valid workspace copy wins on duplicate
names), `/skill <name>` to add an active skill for the Run, `/skill off <name>` to remove
one, or `/skill off` to clear all. A new Run starts with none active; skills do
not grant Tools. The model can call the read-only `skill(name)` or `skill(names)`
Tool to load up to four skills on demand without changing the active set.
`skill(name, path)` reads one relative UTF-8 support file within that skill,
including linked global skills. Paths are limited to 512 characters and content
to 32 KiB; traversal, escaping links, secrets and private recovery files are refused.
Each call must provide exactly one of `name` or `names`.

## Subagents

`agent(name, task, references?)` runs one named role in a fresh process and linked
Session, using the parent's model, workspace, live mode and confirmations. Define
roles in `.agents/agents`, `.claude/agents` or `.codex/agents`, in that order;
workspace definitions precede home definitions. Markdown requires YAML `name` and
`description` frontmatter plus a body; TOML uses `developer_instructions`.
Optional `tools` narrows the parent's Tools; children cannot delegate or ask the
user. Definitions and returned handoffs are bounded to 32 KiB. `/report` shows
delegated cost coverage and child Sessions; Ctrl+C stops the child and its jobs.

## Workspace Tools

The model can list files, read UTF-8 text files a window at a time, and
literally search text in the resolved directory where the process starts.
This Workspace Root remains fixed for the Run.

`read_file(path, offset=1, limit=500)` returns a Read Window: lines
`offset`..`offset+limit-1` (1-based, like `search_text`'s `line`), each
prefixed with `<line number>\t` - a prefix that is not part of the file, so
never copy it into `edit`'s `old_string`. The result is
`{content, has_more, next_offset}`; keep calling with `offset=next_offset`
while `has_more` is true to read further. There is no whole-file size limit:
a file of any size is readable, one window at a time. `PA_MAX_READ_BYTES` is
the Tool Output Cap - the most UTF-8 bytes (prefixes included) one `read_file`
or `search_text` call, or by default `shell`, hands back - and defaults to
`32768` (32 KiB). A window that would exceed it ends at the last whole line
that fits, with `has_more` true and `next_offset` naming where to continue;
the rare case of a single line alone over the cap is returned truncated with
a `[...truncated]` marker instead. An `offset` past the file's line count is
a Tool error naming that count, except reading an empty file at `offset` 1,
which returns empty content.

`search_text(text, path=".", glob=None, regex=false)` numbers lines the same
way `read_file` does, so a reported `line` is always a valid `offset`. A
matched line at most 200 characters long is returned as-is; a longer line is
shortened to about 200 characters centred on the match, with `…` marking a
cut side, so the match is always visible. Matching is literal and
case-insensitive by default; `regex: true` compiles `text` as a
case-insensitive regular expression instead - an invalid expression is a Tool
error naming the problem, before any file is read. The whole response is
bounded by the Tool Output Cap in addition to the existing 100-result limit;
`truncated` is set when either bound cuts the match list.

Listings and directory searches go at most eight directories deep and return
at most 100 results, skipping any directory named exactly `.git`, `.venv`,
`node_modules` or `__pycache__` below the directory searched - name one of
them directly as `path` (or reach a file inside one through `read_file` or
`search_text`) to still search or list it. Paths are always relative to the
Workspace Root; absolute paths, traversal, outbound symlinks, directory
symlinks, `.env`, `*.pem`, and `*.key` are rejected or omitted. Hidden and
Git-ignored files remain eligible.

`list_files` takes an optional `pattern`, and `search_text` an optional
`glob`, filtering the files walked before the 100-result limit or any
matching, using one shared, case-sensitive glob syntax: a pattern with no `/`
matches the file name at any depth; a pattern with `/` matches the path
relative to `path`, segment by segment, where `**` matches zero or more whole
directories and `*`/`?`/`[...]` never cross a `/`. `search_text`'s `glob` is
ignored when `path` names a file rather than a directory.

Run spend has no monetary cap and resets on Resume.

## Mutating Tools

The model can also change the Workspace Root with `write(path, content)`,
which creates a new file or overwrites an existing one with the full given
content. It only writes inside a directory that already exists — it never
creates a parent directory. The same path rules as the Workspace Tools apply:
relative paths only, no traversal, no symlink escape, `.env`/`*.pem`/`*.key`
excluded; an existing target must be a regular file, so a dangling symlink, a
directory, or a directory symlink is rejected. `PA_MAX_WRITE_BYTES` is the
Mutating File Limit, defaulting to `1048576` (1 MiB): it bounds both the
resulting content in UTF-8 bytes and, for an overwrite, the existing file
loaded for the diff preview. Oversized or non-UTF-8 content is a Tool error,
never truncated or transcoded; an existing file over the limit is a Tool
error before Tool Confirmation.

`edit(path, old_string, new_string, replace_all=false)` changes an existing
file by replacing an exact, case-sensitive occurrence of `old_string`: the
one occurrence when it appears once, every occurrence when `replace_all` is
true. There is no fuzzy or whitespace-tolerant matching — what is replaced is
exactly what was named. Zero matches, more than one match without
`replace_all`, or a `new_string` identical to `old_string` is a Tool error
before anything is written. `path` must pass the same file-target rules as
`read_file`, and the file is read with the same bounded reader, bounded by
the Mutating File Limit (`PA_MAX_WRITE_BYTES`) rather than `PA_MAX_READ_BYTES`,
so a binary, non-UTF-8, or over-limit file is a Tool error. The result
reports the path and the number of replacements made.

In `build`, before anything is written, the REPL asks for Tool Confirmation: the full
content for a new file from `write`, or a unified diff against the current
content for a `write` overwrite or any `edit`, then
`Apply this change? [y/N] `. Only an explicit `y` or `yes` (case-insensitive)
applies it; anything else — including a blank line — or end of input leaves
the file untouched and tells the model the change was rejected, so it can
keep working within the same turn instead of assuming it succeeded. Ctrl-C at
the question interrupts the whole turn without writing anything. This is the
Tool-execution gate in `build`; read-only Workspace Tools and `todo` do not
require it. In `auto`, ordinary writes run without a prompt; recognized
Dangerous Commands still require Strong Confirmation (see `/mode` below).

`/recover` separately restores the latest file-changing execution, including
failed/interrupted work and Resume. Owner-only exact snapshots retain bytes,
absence and permissions; shell effects and older Retry executions are excluded.
This is a bounded checkpoint, with no backup history or redo.

### apply_patch

`apply_patch(patch)` applies one Patch in the OpenAI/Codex envelope, adding,
updating and deleting several files - with several hunks per updated file -
as one all-or-nothing change. The envelope is:

```
*** Begin Patch
*** Add File: <path>
+line one
+line two
*** Update File: <path>
@@ <optional anchor>
 context line
-removed line
+added line
*** End of File
*** Delete File: <path>
*** End Patch
```

`*** Add File:` is followed by zero or more `+` lines (their content, each
ending with `\n`; zero lines creates an empty file). `*** Delete File:` takes
no body. `*** Update File:` is followed by one or more hunks: lines starting
with ` ` (context), `-` (removed) or `+` (added), a completely empty line
read as empty context, and an optional leading `@@` or `@@ <anchor>` per hunk
(the first hunk's may be omitted). Context is matched exactly - never by line
numbers - case- and whitespace-sensitively; repeated context that is not
unique in its search region is a Tool error unless an `@@` anchor narrows it
to the first occurrence at or after the anchor. Hunks apply top to bottom
with a moving cursor, so a later hunk never matches text above an earlier
one. `*** End of File` pins a hunk's match to the file's last line; a hunk
with only `+` lines appends at the end of the file. `*** Move to:` (rename)
is not supported - use `Add File` plus `Delete File` instead. An updated file
always ends with a line ending, even if the original did not.

Every path in a Patch, including a delete, passes the same bounds as
`write`/`edit`: relative only, no traversal, no symlink escape,
`.env`/`*.pem`/`*.key` excluded, and the Mutating File Limit
(`PA_MAX_WRITE_BYTES`) on both the existing content and the result. `Update`
targets must pass `edit`'s existing-file rules (a regular file, possibly
through an in-root symlink). `Add` never creates a parent directory, matching
`write`, and its target must not already exist - including as a dangling
symlink, which is a Tool error saying to use `Update File` instead. `Delete`
targets must pass the existing-file rules, must not themselves be a symlink,
and must be UTF-8 text within the limit so their removed content can be
shown. The same path appearing twice in one Patch - by its literal relative
path, or by two different paths resolving to the same file through a
symlink - is a Tool error, as is a Patch with no file sections, an `Update`
producing no change, or any envelope grammar mistake (each such error names
the 1-based line in the Patch where useful).

Every check for every file runs before the user is asked anything: parsing,
path bounds, hunk matching, and size limits. On the first failure nothing is
written and the confirmation callback is never called. Approval then shows
one combined diff, in Patch order, of every file the Patch touches: an
`Update` as a normal unified diff, an `Add` as all-added lines against
`/dev/null`, a `Delete` as all-removed lines against `/dev/null` - every file
appears with its `---`/`+++` headers even when its content is empty. `Apply
this change? [y/N] ` applies the whole Patch in Patch order (writing an
`Add`/`Update` and unlinking a `Delete`, with any in-root symlink and
permissions kept, as `write`/`edit` do); rejection, end of input, or no
confirmation callback leaves every file untouched. If a write or unlink fails
partway, every file touched so far - including the failing one - is restored
from memory: an `Add` is removed, an `Update`/`Delete` is rewritten with its
original bytes and permissions. The Tool error names the failing file and, if a restore
itself also fails, every path that could not be restored.

`apply_patch` is denied in `plan`, exactly like `write`, `edit` and `shell`,
before validation or confirmation. Approved changes participate in the same
latest-execution `/recover` checkpoint as `write` and `edit`.

### shell

A fourth Mutating Tool, `shell(command)`, is on by default. It runs one command string through `bash -c` (falling
back to `sh -c` when `bash` is not on `PATH`), always in the Workspace Root,
with no stdin, and returns `{stdout, stderr, exit_code}`. A non-zero exit
code is a normal result, not a Tool error. The command inherits the parent
process's environment except `TAVILY_API_KEY`, and there is no allowlist,
blocklist, or sandbox — `build` asks for Tool Confirmation, while `auto` runs
unflagged commands without asking; recognized Dangerous Commands (below) still
require Strong Confirmation. Set `PA_ENABLE_SHELL=0`
to disable it (never registered, never offered to a Provider); unset, empty,
or `1` enables it, and any other value is a configuration error at startup.

Before running, every `shell` command is checked against a fixed, ordered
set of Dangerous Command rules, matched on the command string (not a full
shell parse):

- `sudo` — any segment whose leading prefix words (`then`, `do`, `else`,
  `elif`, `{`, `!`, `time`, `sudo`) include `sudo`.
- `recursive rm on a protected path` — a recursive `rm` targeting `/`, `~`,
  `$HOME`, `*`, `..`, or any path that normalizes outside the Workspace Root.
- `git reset --hard`
- `git clean -f` — `--force` or any short flag combination containing `f`
  (e.g. `-fd`, `-xdf`).
- `git push --force` — `--force` or a short flag containing `f`.
- `git checkout -- .`
- `mkfs` — `mkfs` or `mkfs.*`.
- `dd of=` — `dd` with an `of=` argument.
- `redirect to a block device` — `>`/`>>` into `/dev/sd*`, `/dev/hd*`,
  `/dev/vd*`, `/dev/xvd*`, `/dev/nvme*`, `/dev/mmcblk*`, `/dev/dm-*` or
  `/dev/md*`.
- `recursive chmod/chown on / or ~` — `chmod`/`chown -R` targeting `/`, `/*`,
  `~`, `~/`, `$HOME` or `${HOME}`.
- `fork bomb` — the classic `:(){ :|:& };:` shape.
- `pipe into a shell or interpreter` — a single `|` (or `|&`), with an
  optional `sudo`/`env` word, into `sh`, `bash`, `zsh`, `python`,
  `python3(.x)`, `perl` or `node`.
- `eval`
- `shell -c with command substitution` — `bash -c`/`sh -c` whose argument
  starts with `$(`.
- `source of process substitution` — `source`/`.` followed by `<(`.

A command matching one or more rules gets Strong Confirmation instead of the
normal `Run this command? [y/N] ` prompt: the matched rules are printed in
red (`Dangerous command: <rule>, <rule>`), and only the exact word `yes`
(trimmed, any case) runs it — `y`, a blank line, anything else, or end of
input rejects with the usual `change rejected by the user` error, exactly
like a normal rejection. A Dangerous Command is never blocked outright: it
always runs on a deliberate `yes`. The matched rules are not configurable —
no environment variable, setting, or file changes or disables them — and are
written to the Call Log's Tool execution entry (`dangerous_rules`) whether
the command was approved or rejected, so a session can be audited later.
These rules are pattern matching only: an obfuscated command (a quoted or
variable-built interpreter name, `find / -delete`, a command nested inside a
quoted `bash -c '...'` string) is not detected, and there is still no
sandbox.

A command running past `PA_SHELL_TIMEOUT_SECONDS` (default 30) is sent
SIGTERM, then SIGKILL if it is still alive after a short fixed grace period,
and the call becomes a Tool error naming the limit; no partial output is
returned. `PA_SHELL_MAX_OUTPUT_BYTES` (default: the effective
`PA_MAX_READ_BYTES`) caps stdout and stderr independently; a capped
stream ends with `[...truncated]`. Both settings are ignored while `shell`
is disabled.

Every call kills the command's whole process group when it ends — on a
normal exit as well as on a timeout — so a process the command backgrounded
(for example `nohup server >/dev/null 2>&1 &`) does not survive the call. A
process that escapes the group (for example via `setsid`) cannot be killed
this way; if it still holds stdout or stderr open, the call instead ends in
a Tool error after a short additional bounded wait, saying a process that
left the process group may still be running.

#### Background Jobs

`shell` with `background: true` goes through the same confirmation, Dangerous
Command and `plan` rules, then starts the command as a Background Job and
returns `{job_id, state: "running"}` at once. The confirmation preview starts
with `[background job]`. Jobs use the same shell, Workspace Root, no stdin and
environment as `shell`, run in their own process group with stdout and stderr
merged, and have no timeout. At most four run at once (a fifth is refused
before confirmation); each keeps only its latest 64 KiB of output, and the 16
most recently finished jobs stay queryable. When a job's main process exits,
the rest of its process group is stopped.

`job_status(id)` returns `job_id`, `command`, `state` (`running`, `exited`,
`stopped`), `exit_code` and the latest output, capped by
`PA_SHELL_MAX_OUTPUT_BYTES` and prefixed with `[...earlier output discarded]`
when older bytes were dropped. `job_stop(id)` sends SIGTERM, then SIGKILL after
the grace period; a finished job is returned unchanged. Neither asks for
confirmation; `job_status` works in `plan`, `job_stop` does not. Both exist only
when `shell` does. `/jobs` lists jobs and `/jobs stop <id>` stops one, in every
Agent Mode.

Jobs belong to the current Run and are never persisted: Resume does not
restore them, and `/clear`, `/undo`, `/retry`, Compression and mode changes keep
them. `/exit`, `exit`/`quit`, end of input, Ctrl-C at the prompt, an unhandled
error and `/fork` stop every live job and record one `background_jobs_stopped`
Audit Event when the Call Log is still writable. Processes that leave the
process group (for example via `setsid`), or an agent killed by a signal it
cannot handle, are not covered.

## Network Tools

`websearch(query)` is offered in `plan`, `build` and `auto` only when a nonblank
`TAVILY_API_KEY` is set in the environment or startup `.env` (not through
`/config`). Each call shows the complete query and asks
`Search the web? [y/N] ` in `build` or `plan` before sending anything; `auto`
skips this prompt. An explicit `y` or `yes` approves one
Tavily basic search (one API credit); refusal or EOF sends nothing. It returns
up to five source links with short titles and snippets, never page content or
Tavily's generated answer. Results are untrusted third-party data. To read a
source, request `webfetch` separately (with confirmation in `plan` or `build`).

`webfetch(url)` is on by default and GETs one `http`/`https` URL, following
redirects, and reports the final URL. Tool Confirmation shows
`webfetch: <url>` and asks `Fetch this URL? [y/N] ` in `build` or `plan`; `auto`
skips this prompt. The same rules as the Mutating Tools' gate apply in prompted
modes (only `y`/`yes` approves; anything else, or end of
input, rejects with nothing fetched). A URL longer than 150 characters adds a
warning line when prompting, since a long query string can carry workspace content out. The
System Prompt tells the model to treat fetched content as untrusted data. A URL with any other scheme, or no
host, is a Tool error before any request is sent; localhost and private
addresses are allowed. A fixed,
non-model-controlled `User-Agent` is sent; the request times out after 30s
and a response over 5 MiB (5242880 bytes) is a Tool error, as is any HTTP
status 400 or above (`HTTP <status> <reason>`) or other network failure.

Once a `webfetch` succeeds in a turn, every later Tool Confirmation of
`shell`, `write`, `edit` or `apply_patch` in that same turn - including a
later call in the same Tool batch - carries a yellow Fetched-Content Warning
naming every distinct URL fetched so far this turn:
`Warning: this turn fetched <url>, <url>. Web content may have steered this
change; review it carefully.` It only informs; approval is unchanged (a
normal command still takes `y`, a Dangerous Command still needs `yes`), and
it is never shown on the `webfetch` confirmation itself. A rejected or
failed `webfetch` adds nothing. Successful `websearch` results similarly add a
warning about external search content before later `shell`, `write`, `edit`
or `apply_patch` confirmations; rejected or failed searches do not. Both warnings are scoped to
one routed turn: a new task or `/retry` starts without them.

`text/html` and `application/xhtml+xml` are converted to plain text - script,
style, and similar non-content elements dropped, block elements and `<br>`
turned into line breaks, character references decoded. An element hidden
from a human reader - carrying a `hidden` attribute, `aria-hidden="true"`,
or an inline `style` containing `display:none` or `visibility:hidden`
(whitespace- and case-insensitive) - is dropped the same way, together with
everything nested inside it; content after a hidden element is unaffected.
For an element whose end tag is optional in HTML (`li`, `p`, `td`, and
similar), a same-name sibling start tag ends the drop the way a browser's
implicit close would, so `<ul><li hidden>x<li>a</ul>` keeps `a`. Hiding
through a CSS class or an external/`<style>` stylesheet is not detected -
only an inline `style` attribute or the attributes above.

`text/*` (including `text/markdown`), JSON, XML and JavaScript pass through unchanged; any other
content type, or a missing one, is a Tool error naming it. The result is
`{url, status, content_type, content, truncated}`; `content` is bounded by
the same Tool Output Cap (`PA_MAX_READ_BYTES`) as the Workspace Tools, cut on
a character boundary with the `[...truncated]` marker when it would be
exceeded. `webfetch` is stdlib-only (`urllib`, `html.parser`) and needs no
env var.

## Questions during a task

The agent can call `question` in `plan`, `build` or `auto` to show up to four questions
at once, with optional numbered choices and a free-text answer for each. In an
interactive Input Box, answer them in order and the agent continues the same
task; answers are not Tool Confirmation for any later action. With piped input,
the Tool reports that interactive input is required and leaves subsequent task
lines untouched. Ctrl-C interrupts the turn; EOF yields a Tool error.

Choice labels may be strings or text-only objects (`{"text": "Full MVP"}`);
both display as plain labels, with the same nonblank 120-character limit.

Each question with N choices also lists `N+1. Other (custom answer)`; picking
it opens `Custom answer <n>: `, whose text is returned literally. A whole
integer (surrounding spaces, sign and leading zeros allowed) selects a choice;
any other integer shows the valid range and asks again. Other text, such as
`1.5`, is a direct answer, and `text: 5` answers `5` literally. Answers must be
nonblank and at most 1000 characters.

## Memory

`/remember <text>` records one fact, preference, or decision as a Memory
Note, `/memory` lists every current Memory Note with a 1-based index, and
`/forget <index>` removes the note at that position. Memory is global,
not tied to any one session or Workspace Root: it lives in one JSONL file
(one `{"text": ..., "added": ...}` object per line) at `PA_MEMORY_PATH`,
created with its directory on the first `/remember`.

Whenever at least one Memory Note exists, it is injected into ordinary System
Prompts after application rules and Project Instructions, so it shapes
every routed turn of this run and every later run and session. Nothing about
Memory is written to the Call Log — its file is its only record. Recording a
Memory Note pushing total Memory content past roughly 2000 characters prints
one warning that it is now sent with every request; nothing is capped,
truncated, or dropped automatically. Re-run `/memory` between removals to see
the renumbered list, since `/forget <index>` is positional against the
current Memory.

## Todo List

`todo(todos)` is on by default, needs no Tool Confirmation, and lets the
model keep its own checklist on a task of three or more steps: each call
replaces the whole list with the given items, each `{content, status}` with
`status` one of `pending`, `in_progress`, `completed` or `cancelled` (the
model is told to keep at most one `in_progress`, not enforced); an empty
list clears it. After each successful call the REPL prints a compact
checklist in place of the generic Tool line:

```
tool> todo
  [ ] step three
  [~] step two
  [x] step one
```

(`(empty)` for an empty list). While at least one item is `pending` or
`in_progress`, the current list is appended to the System Prompt as a
`Todo List:` block, including on the very next exchange within the same
turn - so the model still sees its own plan mid-turn and after Compression;
once every item is finished or the list is empty, the block drops out. The
list follows the Conversation like everything else: `/undo` and `/retry`
restore it to what it was before the removed turn, `/clear` empties it, a
turn that fails or is interrupted never changes it (it only ever updates
from a turn that actually completes), `/compress` leaves it unchanged,
and `--resume` rebuilds it from the Call
Log to match where the last Run left off. There is no separate read-only
Tool - the model's own last `todo` call is always the source of truth.

## Terminal and sessions

See the [README](../README.md#setup) for installation and first-run setup.

When both stdin and stdout are an interactive terminal, you type into an
Input Box: a `> ` line framed by two horizontal rules. Enter submits,
Alt+Enter (or Escape then Enter) inserts a newline, so a multi-line task is
sent as one task. Arrow up recalls earlier inputs from this session (kept in
memory only, never written to disk), Tab completes a `/command`, and Shift+Tab
cycles `plan → build → auto → plan` while editing, confirming, answering a
question, viewing a preview, or waiting for a Provider or Tool. Drafts and
answers are preserved. During work the current mode remains visible; output
stays in the terminal's scrollback. Below the box, a Status Footer shows the current `/mode`, the
configured Provider/model, its access method (`API key`, `Assinatura ChatGPT` or `unready`), the
approximate current input over the effective input allowance with capacity provenance
(`public`, `manual` or `assumed`; `ctx unknown` after a route, context or Conversation change),
this Run's API spend with reported/estimated/unknown coverage on API routes (no monetary counter
on ChatGPT) and a `/help` hint. Otherwise (piped or
redirected), type a task per line; a `user> ` prompt is shown only when stdin
alone is a terminal. Startup prints `Provider/model: <provider> <model>`. Answers use an
`llm>` prefix; each completed request also prints one compact `[provider] model` line.

OpenRouter requests prefer the cheapest upstream host among those with a p50
throughput of at least 85 tokens/second (`provider.sort: "price"`,
`preferred_min_throughput: 85`), retaining the configured model and default
fallbacks. Slower hosts are deprioritized, not excluded. These preferences do not
pin a provider endpoint; Session affinity remains best effort.

OpenRouter receives the durable Session Id as `session_id` across turns,
Tool follow-ups, retries and Resume. Compression uses a separate `:compression`
identity. Affinity is best effort per model: it guarantees no cache hit, survival
after idle time or reuse across models. Changing the configured pair changes the model.

Claude routes request prompt caching automatically: the direct Anthropic
Provider, and OpenRouter when the model id starts with `anthropic/`, send one
top-level `cache_control` marker with the default five-minute lifetime. There is
no setting. This guarantees no cache hit or saving; other routes are unchanged.

Interactive file and shell confirmations bound large previews to half the
terminal height. Type `v` to inspect the full read-only preview; arrows and
Page Up/Down scroll, and `q` or Escape returns to approval. Viewing never
approves an action; `y`/`yes` is still required (exact `yes` for dangerous
commands). Piped input keeps full previews.

For OpenRouter provider diagnostics, set `PA_OPENROUTER_PROVIDER_DIAGNOSTICS=1`
before starting a Run. Each successful OpenRouter exchange starts a background
metadata lookup; the answer and Attempt latency do not wait for it. When the
lookup finishes, an `upstream_provider` Call Log event identifies the Attempt
by its timestamp, with the host name or, on failure, an `error` reason. A Run that exits immediately may end before the lookup is
recorded. Leave it unset to avoid extra requests.

Every exchange with a Provider carries a System Prompt telling the model to
use Tools for arithmetic and the current date or time rather than guessing,
and to answer in the language the task was written in. The prompt does not
include a changing clock value. Ordinary prompts order application/Tool/trust/
mode/language rules, the task's Project Instructions, Memory, active Skills,
Summary and unfinished Todo. Changing context preserves preceding stable bytes;
cache hits and full-history reuse are not guaranteed. The `/compress` summary call
offers no Tools, so its System Prompt leaves the Tool rules and the Todo
List out.

On an interactive terminal, output is colorized and a spinner animates while
a request is in flight; both are automatically off when piped (`cmd | uv run
python -m personal_agent`) or when `NO_COLOR` is set to any non-empty value.

The REPL keeps one Conversation, rebuilt from the Call Log on Resume. A
follow-up can refer to all retained turns, including after `/model` or a
restart with another Provider/model. Complete request budgeting, not a fixed turn count, controls
when older context needs Compression.

To continue an earlier session after the process exits:

```bash
uv run personal-agent --resume last
uv run personal-agent --resume <session-id>
```

Resume stays in the starting project. `last` compares the latest physical Run
start/resume timestamp, with Session Id as the tie break; interrupted Sessions
remain eligible. Selection fails on unknown metadata or exhausted scan bounds
(4,096 catalog entries, 8 MiB, 8,192 records, 256 KiB retained per record).
Strict replay still rejects malformed logs. Explicit Session ids also stay
inside this project.

The Conversation is rebuilt by replaying that session's Call Log in order:
`/clear` empties it, each successful turn is appended, each `/undo` removes
the last remaining turn, and each `/compress` sets the Conversation Summary
and keeps only the two most recent remaining turns. New turns append to the
same log file. Resume keeps the Session Id and submission count, uses the
current configured pair, and resets Run spend and active Skills. Only
`log_version: 3` Sessions resume; older Call Logs are refused before anything is
appended and stay on disk unchanged, including when `last` selects one. An
unknown, unreadable or malformed session exits with an error.

### Commands

`/retry` and `/compress` can run model inference; connection and catalog commands
may also make network requests.

- `/help` — list the commands below.
- `/history` — show every completed turn, oldest first.
- `/clear` — forget the Conversation, including any Conversation Summary
  and failed-turn continuation (recorded in the Call Log, so Resume does not restore
  them); keeps the submission count, configuration, Run spend and Background Jobs.
- `/jobs` — list this Run's Background Jobs; `/jobs stop <id>` stops one.
- `/fork` — branch the Conversation at its latest closed turn: stops Background
  Jobs, ends the parent's Run (`session_end` reason `fork`) and continues at once
  in a new child Session whose Call Log copies the turns, Conversation Summary and
  Todo List, so it resumes even without the parent's file. The parent is
  otherwise unchanged; resume it with `--resume <id>`. The child starts with `$0`
  Run spend, ordinal 1, an empty `/report` and a fresh file checkpoint, and keeps
  the Agent Mode, active Skills, Memory and configuration. Both Sessions share the
  Workspace Root (no worktree, no file restore), so file changes from either branch
  affect both. Refused while a failed or interrupted turn awaits `/retry`, while
  file recovery is unresolved, or when the Conversation is empty.
- `/model` — show the Provider/model, its catalog limits or local rejection
  reason, and the catalog fetch time (no API keys).
  `/model <provider> <exact-model-id>` checks the catalog and that Provider's
  key, then saves `PA_PROVIDER` and `PA_MODEL` together in one atomic write to
  `~/.personal_agent/.env` and uses the pair from the next task or `/retry`.
  An invalid pair, missing key or save failure changes nothing. Model IDs are
  exact and case-sensitive; catalog admission does not prove account access.
- `/models [provider] [query]` — search eligible offerings; `/models refresh`
  refreshes the catalog only.
- `/mode [plan|build|auto]` — show or change the Agent Mode for later tasks in this
  Run. Every Run, including Resume, starts in `build`: `write`, `edit`,
  `apply_patch` and `shell` are available with Tool Confirmation. In `plan`, those Tools are
  neither offered nor executed; workspace inspection, `calculator`,
  `current_time`, `todo` and `webfetch` remain available, and `webfetch` still
  requires Tool Confirmation. In `auto`, the same Tools as `build` run without
  confirmation, including `webfetch` and `websearch`; only `shell` commands
  matched by the Dangerous Command rules require Strong Confirmation (`yes`).
  Automatic calls show their normal Tool results, not confirmation previews.
  Shift+Tab changes the running turn at subsequent Tool boundaries and Provider
  exchanges; an operation already running finishes normally. A pending approval
  still needs an explicit answer after switching to auto; switching to plan
  blocks a pending mutation even after `y`. `/mode` also works with piped input.
  The mode is independent of the configured model.
- `/config` — in an interactive terminal, show the configured pair; `reasoning`
  edits the ChatGPT reasoning preference, `model`
  selects a pair with the same validation as `/model`, `models` searches the
  catalog, `context` edits the total context budget and the current pair's
  exact capacity override, and `key` enters Provider API keys in a hidden prompt. Accepted changes
  apply to later tasks and save to `~/.personal_agent/.env`; exported variables
  and the current-directory `.env` still take precedence on the next Run.
- `/undo` — remove the most recent turn from the Conversation (a turn is only
  ever there because it succeeded), recorded in the Call Log as a
  `turn_undone` entry so a Resume does not bring it back; the original
  `turn_end` stays in the Call Log for audit. With no turn to remove, prints a
  local error and writes nothing. Repeat it to back up further, one turn per
  call.
- `/retry` — continue a failed or interrupted task with its completed questions,
  answers and Tool results, including after `--resume`. Completed Tools are not
  automatically repeated. Each explicit retry uses the current pair, configuration,
  Agent Mode and confirmations, with a fresh Tool-round allowance and the original
  submission ordinal. Provider-specific replay is reused only on the same pair.
  A new task receives bounded recorded progress/error context; `/clear` discards
  it. Only `/retry` resumes pending execution. Config/mode changes, a
  changed pair and Compression keep it.
  A successful task is intentionally rerun and can execute Tools again; its turn
  is Undone first if still last. Without a retryable task, sends nothing. Old logs
  without explicit continuation retain their completed history without inventing
  pending work from Attempts.
- `/recover` — preview the latest execution changed by `write`, `edit` or
  `apply_patch`, then type literal `yes` to restore, even in `auto` or piped input.
  `plan` permits preview only. A changed file, permission or link refuses the whole
  set. Recovery preserves Conversation; it resets only the matching failed task's
  continuation, including inherited Retry prefixes, to a fresh Retry. A successful restore consumes this checkpoint;
  subsequent calls never walk older history. Snapshots live in owner-only
  `recovery-<session id>/` beside the Call Log, outside reports/model input.
  Images are limited to `min(PA_MAX_WRITE_BYTES, 4 MiB)`, with 64 canonical paths,
  16 MiB combined snapshots, 24 MiB per manifest and 80 MiB per Session.
- `/compress` — replace older turns and any previous summary with a new
  Conversation Summary, keeping the two most recent turns intact. Large
  sources are split into labeled blocks that fit the configured pair; their
  summaries are combined through further bounded calls. Every Attempt,
  including local transient retries, counts toward Run spend;
  Compression uses the current pair and never starts another task. One final
  `conversation_compressed` entry is saved before live state changes.
  Failed, interrupted, empty, truncated or non-reducing construction leaves
  the Conversation unchanged. An observed partial append failure restores
  the prior log prefix; failed restoration stops the Run. The summary travels in the System Prompt
  of every later request (never as a message), `/history` prints it first as
  `summary: ...`, `/undo` never removes it, and only `/clear` drops it. With
  two or fewer turns and no previous summary, prints a local error and makes
  no call. A previous summary can be compressed again on its own.
- `/remember <text>` — record one Memory Note (see Memory above), confirmed
  with `Remembered.`. With no text, prints a local error and saves nothing.
- `/memory` — list every Memory Note as `<index>. <text>`, 1-based, in stored
  order. With none, prints `No Memory Notes.`.
- `/forget <index>` — remove the Memory Note at that position, confirmed with
  `Forgot: <text>`. A missing, extra, non-numeric, zero, negative or
  out-of-range index prints a local error naming the valid range and changes
  nothing.
- `/usage` — show the current configured budget and the last ordinary
  exchange's task snapshot, route, assessed outcome, effective limits,
  approximate local input estimate and Provider-reported usage when
  available, plus spend and retained/sent turns. Manual Compression adds
  spend without replacing that exchange's diagnostics. It also shows the access
  method, current input occupancy (unknown once the route, context or
  Conversation changes), Run API cost with reported/estimated/unknown coverage
  including earlier routes and Subagents, observed ChatGPT plan tokens with
  unknown cost and `Manage usage`. No Provider call or
  Call Log read is made; before any exchange is assessed, it reports that fact.
- `/exit` — leave the REPL.

### Reports and streaming

`/report` reads the current project's current Session Call Log locally, including
prior Runs after Resume and activity retained after Clear/Undo. It separates
execution and Compression; outcomes, technical retries and
explicit Retry; recorded duration, tokens/cache and cost with sample coverage.
Reported, estimated and unknown-provenance spend are distinct recorded subtotals,
not a bill. ChatGPT plan Attempts are grouped by opaque account label with cost
unavailable; API cost subtotals exclude plan use. Missing samples stay unknown; damaged or bounded scans are labeled
partial. Provider duration excludes Tools, human waiting and backoff, and cannot
separate network/generation time. First-text latency is unavailable in old logs.
Run spend and `/usage` still reset on Resume. `/report` accepts no arguments.
After the aggregates, it lists the latest 20 explicitly opened executions with
Run/opening identity, original ordinal, submission/Retry, outcome and recorded
Provider/model routes. Maintenance stays separate. Details retain at most
16 consecutive route groups per execution; the report is bounded to 16 KiB,
with omission notices. Cache-read fractions use compatible known samples only.
Adjacent cache observations and route changes do not establish cache loss or savings.

Ordinary tasks stream Markdown blocks in color terminals and flushed plain text
otherwise, including Tool follow-ups. Known keys and terminal controls are filtered before display. If
output becomes incomplete, automatic retries stop; use `/retry` to continue
from completed Tool results. First-text latency measures local dispatch through
safe text delivery, including filtering and output delay. Compression calls
remain buffered and do not display their content. OpenAI keeps
Chat Completions, Anthropic keeps Messages `2023-06-01`, and Gemini keeps `v1beta`
GenerateContent with native Tool signatures. No streaming setting is required.

### Context budgeting

`PA_CONTEXT_BUDGET_TOKENS` defaults to 250000 total tokens.
`PA_CONTEXT_CAPACITY_OVERRIDES` supplies exact Provider/model limits (see
[examples](ENV_VARS.md#context-capacity-overrides)); `/config` → `context`
edits both persistently. Each task keeps its starting configuration, including
Tool follow-ups and summaries; changes affect the next task.
Each limit field has its own source, shown by `/usage`: an exact manual
override first, then the selected offering's Models.dev `limit.context`
(total), `limit.input` and `limit.output`, then local LiteLLM metadata for a
field Models.dev omits (its input limit also stands in for a missing total),
then `unknown; assumed 128000`. Limits are frozen with each task or explicit
Retry; a refresh only affects later ones. Models.dev prices are never used for
cost. OpenRouter model-wide metadata does not prove the capacity of its
unpinned upstream.

The effective total is the smallest configured/route/published total bound.
Output reserve is `min(16000, known output limit)`; the mandatory input ceiling
is `min(effective total - output reserve, known input limit) - 10000`.
For a 250000 effective total with no tighter restrictions, prevention triggers
at **200000 estimated input**, aims for **150000 input**, and independently
enforces the **224000 input ceiling**. Reserve/margin are not added to the
80% input trigger: 174000 does not trigger it. Assumed 128000 gives a 102000
ceiling. Output caps include reasoning where the Provider shares that allowance.

Every initial exchange, transient retry and Tool follow-up measures
the complete prepared input: instructions, Memory, summary, Todos, Skills,
retained history, task, full Tool schemas and active calls/results/signatures.
Local LiteLLM JSON-input token estimates are approximate, labeled with the
encoding and generic fallback when used; they are not Provider-reported usage
or guaranteed upper bounds. Only bundled/cached tokenizer assets are used:
no implicit download, paid counting endpoint or byte/character proxy. If no
local tokenizer can measure input, dispatch stops visibly. Cached input still
occupies context; `/usage` distinguishes estimates, reported counts and outcomes.

Automatic Compression reduces eligible older turns and the prior summary in
paid, fitting blocks on the configured pair, preserving the latest two complete turns and
the entire pending turn. Its 60% target is best-effort; the mandatory ceiling
is not. It commits only the final safe summary, then continues the pending
exchange, never a synthetic task. The 80% trigger needs eligible older turns; a
summary with none is reduced only above the ceiling or in overflow recovery. If
Compression fails at the 80% trigger within the ceiling, the failure is shown
and the unchanged pending exchange is sent. Above the ceiling or in recovery,
failed Compression or unfittable protected content stops visibly without
silently dropping data. `/compress` uses
the same bounded construction without starting another task.

A positive Provider-specific input/context overflow rejection allows one
same-Provider/model retry after strict measured reduction and a fresh budget
check, without repeating executed Tools. A second rejection, failed reduction
or any retry failure stops; summarization never recursively recovers. All
summary/recovery Attempts count toward Run spend. Failed/interrupted turns do
not become replayable successful turns; earlier committed Compression and
Tool execution evidence remain in the Call Log.

### Errors and interruption

An unrecognised `/command`, or arguments to a command that does not take them,
prints a local error instead of being sent anywhere. `/mode`,
`/remember`, `/forget` and `/skill` accept arguments as described above.

A blank line is ignored. Type `exit`, `quit`, `/exit`, or press Ctrl-D to
leave.

A call that fails transiently — a network timeout, or HTTP 429/500/502/503/504
— is retried automatically, up to 3 Attempts on the same Provider/model,
with a growing pause between them (0.5s, then 1s). A permanent failure —
a bad key, a bad request, a malformed response — fails on the first Attempt
instead of burning the other two.

When retries are exhausted or a permanent failure occurs, the task stops on
its configured Provider/model and displays the original error. Use `/retry` to
try again; to use another model, select it first with `/model <provider> <model-id>`.
There is no evaluator, automatic route change or monetary cap.

Ctrl-C during a call or a retry wait aborts the whole task — it prints a notice
and returns you to the prompt. A dispatched interrupted Attempt is logged;
no Attempt is invented for a local check or wait. Ctrl-C at an idle prompt
ends the session.

### Call Log

A new Session mints one Session Id — a sortable UTC timestamp plus a
short random suffix, e.g. `20260922T142233Z-3f9a2c`. Resume reuses that Id.
The Session's Call Log is written to `~/.personal_agent/logs/<flattened-absolute-path>--<12-hex-hash>/pa_log-<session id>.jsonl`.
The project id is the flattened absolute Workspace Root (up to 96 ASCII
characters), followed by `--` and 12 hex SHA-256 characters of its original
path. The home and project are captured once; later directory changes do not
redirect logs. Parent folders are created on demand. Direct Call Log callers
capture cwd on first use. Start/resume records include the original
`workspace_root`, `project_id` and fresh `run_id`, plus `log_version: 3`.
Old flat logs are neither discovered nor migrated.

A Session's file opens with one `session_start` line, and each Run of it
closes with one `session_end` line; a resumed Run opens with a
`session_resumed` line carrying the Provider/model configured for that Run.
Every other line is one of:
`attempt`; `tool_execution`; `turn_end` (one per routed task, `status` `ok`
with the turn's `messages`, `error` with its `error` text, or
`interrupted`); `conversation_cleared` (one `/clear`); `turn_undone` (one
`/undo`, or the Undo `/retry` performs); `conversation_compressed` (one
successful `/compress`, carrying `summary`); `routed_task_submitted` (positive
consecutive `ordinal`, exact accepted `task` and the task's `provider`/`model`,
persisted before dispatch); `routed_task_retried` (the retried `ordinal` and the
Retry's `provider`/`model`, written before its Attempts); `conversation_forked`
(only as line 2 of a `/fork` child whose `session_start` names
`parent_session_id`, carrying the copied `turns`, `summary` and
`todo_baseline`). An execution is
identified by Run, opening line and ordinal; Attempts never open one.
`file_recovery_started` and `file_recovery_finished` carry only execution
Run/opening/ordinal and outcome; exact snapshot bytes remain in the companion.
`session_start` and `session_resumed` carry `provider` and `model` (no API keys).
Recorded routes are evidence; Resume uses current settings. Openings and Clear
are saved before live mutation; observable partial appends restore the prior
prefix, and write/restoration failures stop the Run. Malformed or contradictory
openings fail Resume.
`session_end` carries `reason` —
one of `exit_command` (bare `exit`/`quit` or `/exit`), `eof` (input
exhausted), `interrupt` (Ctrl-C at an idle prompt), `fork` (with
`child_session_id`), or `error` (an unhandled exception) — and `total_cost`, the sum of that Run's Attempt costs
(`0.0` when it made none). `total_cost` is computed by the Call Log itself
from what it logged, and mixes real and estimated cost without distinguishing
them; each Attempt retains its cost provenance. A
Session that only ran local commands still has a `session_start` and
`session_end` line — "commands are free" means zero `attempt` lines, not a
missing file. `/clear` never starts a new Session: Attempts before and after
it land in the same file under the same `session_id`, and `total_cost` still
includes what was spent before it.

Every Attempt is appended as one JSON line to the Session's Call Log file,
carrying `session_id` and `type: "attempt"` alongside the task,
provider, model, latency, the Provider's usage, whether its cost is
estimated, and `attempt` — a 1-based count that keeps incrementing across
every Provider exchange within a routed task (the first request and any
Tool follow-ups). Retried or Tool-using tasks show several lines sharing the same
`task`, with `ok: false` and the error text on each failed Attempt. It also
carries `answer` — the assistant's text for that exchange, `null` on a
failed Attempt or a response with no text — and `tool_calls`, the ordered
list of Tool calls that response requested (each with `id`, `name`,
`arguments`, and `arguments_raw` — set only when the Provider's arguments
were not valid JSON); `tool_calls` is `[]` when none were requested and
`null` on a failed Attempt.
`upstream_provider` names the OpenRouter endpoint when diagnostics are enabled
and its metadata lookup succeeds; otherwise it is `null`. This differs from
`provider`, which names the configured API (`openrouter`, `openai`, etc.).
Attempts retain supplied `cached_tokens` and `cache_write_tokens` for API-key
Providers; unavailable evidence is `null`, while reported zero remains `0`.
OpenRouter/OpenAI/Gemini cache reads are subsets of `prompt_tokens`; Anthropic
normalized prompt includes noncache input plus cache reads and writes.
OpenRouter retains its Provider-reported cost.

Each locally executed Tool call gets its own `tool_execution` line, written
after the batch runs and before the follow-up Attempt, so reading a file top
to bottom replays the real sequence: the requesting Attempt, then its
`tool_execution` line(s) in execution order, then the follow-up Attempt.
It carries `tool_call_id` (matching an `id` in the requesting Attempt's
`tool_calls`), `name`, `arguments` (the object passed to the Tool, `null`
when the Tool boundary rejected the call before running it — unknown name,
invalid arguments, wrong types, extra keys), `ok`, `result` (the Tool's
returned object when `ok`, else `null`) and `error` (the error text when not
`ok`, else `null`). A batch rejected wholesale for a missing or duplicate
Tool call id runs nothing and writes no `tool_execution` line — the
requesting Attempt line already records what was asked. Tool execution is
never an Attempt: it advances neither the Attempt counter nor Run spend.

OpenRouter's reported cost has `cost_estimated: false`. Anthropic, OpenAI, and
Gemini report tokens rather than a bill, so their cost is estimated from those
tokens and has `cost_estimated: true`. Local LiteLLM pricing includes measured
cache reads/writes and reported Anthropic write TTLs, billing each token once.
Unsupported prices or incomplete/invalid required usage leave cost `null`.
Missing cache counters remain unknown in reports, including when a Provider
contract permits omitted-zero for calculation. Historical costs are unchanged.

### Detailed audit (opt-in)

Set `PA_DETAILED_AUDIT=1` before a Run to append a sensitive companion JSONL
trace for that Session; unset or `0` leaves it off. Other values fail startup.
Its companion is `~/.personal_agent/logs/<flattened-absolute-path>--<12-hex-hash>/pa_log-<session id>.audit.jsonl`,
in the same fixed project folder as the Call Log.

The Call Log marks every Run with `audit_coverage_start` and
`audit_coverage_end`, a fresh `run_id` and `enabled` flag. Earlier logs without
markers have unknown coverage. The enabled companion pairs `run_start` and
`run_end` by `run_id`, records `attempt_start` (System Prompt, ordered messages,
Tool definitions and replay input) before each Provider exchange, and
`attempt_end` (normalized answer or error) afterward. `attempt_id` links these
to each other and the Call Log Attempt. `action_start` precedes a REPL Command
or Tool request, and its `action_id` links the outcome in the Call Log's
`audit_event` or `tool_execution`; `action_end` follows the recorded outcome.
`local_outcome` copies safe local decisions; `/remember` text may appear in a
redacted `command_detail`, but `/config` secret entry is never recorded there.
Companion records carry a timestamp, Session Id and Run Id. A missing end,
unmatched start or truncated line means incomplete evidence, not success. A failed
companion write stops the Run with a fatal error; Resume still reads only the
Call Log, and disabled Runs never need the companion.

The companion is created owner-only (0600). An existing symlink, permissive
file or malformed tail is refused when detail is enabled. It can contain
private conversation, Memory, Skill, Tool and command data: known Provider
keys (including earlier keys entered this Run) and Tavily keys are redacted,
but unknown secrets are not detected. Restrict local access and backups. Keep or
delete the Call Log and companion together under your own retention policy;
neither is automatically pruned.

## Session discovery

The read-only `session_logs` Tool is available in every mode without confirmation:

```json
{"action": "list"}
{"action": "read", "session": "previous"}
{"action": "search", "query": "deployment decision", "project": "all"}
{"action": "read", "session": "20260922T142233Z-3f9a2c", "project": "/original/project", "source": "audit"}
```

`action` is `list`, `read` or `search`. Omitted `project` uses the captured launch
root; `all` explicitly spans projects, or supply an absolute original directory
(no `.`/`..`, even if it no longer exists). `session` is required for read,
optional for search and forbidden for list: use an id or `last`/`previous`, which
selects the most recently started/resumed Run excluding the current Session.
List/search and explicit-id reads include the current Session. Ambiguous ids
across projects require a project selector. List order is project id ascending,
then Session id descending. `query` is required only for literal case-insensitive
search (nonblank, maximum 500 characters). `source` defaults to `call_log`;
`audit` is explicit and unavailable without recorded enabled coverage and a safe
companion. Mixed, disabled and incomplete audit coverage remains visible.

`limit` is 1–100, default 20 for list/search and 100 for read. Results contain
`content`, `has_more` and `next_cursor`; continue with the same selectors/query
and `cursor: next_cursor`. Aliases stay bound to the Session selected on page one.
An empty search page can still have more data to inspect. Changed catalogs,
replaced/truncated files or changed selectors require restarting; append growth
is allowed. Cursors are valid only within the current Run/process; a cursor from
an earlier process returns a restart error. No extra arguments are accepted.

Every row identifies its validated original project, Session, source filename,
physical line and recorded timestamp. Timeline reads preserve submissions,
assistant answers/intents, actual Tool results/errors, Run/Turn outcomes and
clear/undo/compression activity; saved Conversation snapshots are omitted.
Intent is not execution. Malformed records and interrupted/unclosed activity are
visible evidence; strict Resume still rejects malformed logs. History is untrusted
data, never executed or restored by this Tool. Current/protected known keys are
redacted before matching and output; unknown old credentials are not detected.

The existing `PA_MAX_READ_BYTES` bounds text, including diagnostics. Oversize
rows are visibly truncated and advanced. Each invocation inspects at most 4,096
catalog entries, consumes 8 MiB and examines 8,192 records, parsing at most 256 KiB
per record. Read/search continue on scan exhaustion, including while discarding
oversize lines; selecting last errors when a complete recency scan cannot fit.
Cursors are bounded separately to 8,192 characters and contain only control
metadata. Old flat logs are ignored.

## Tools

Every request offers the model a set of built-in Tools, so any request can
turn into a short back-and-forth before the final answer. Two are always
offered, `calculator` and `current_time`; see Workspace Tools, Mutating
Tools, Network Tools, Skills and Todo List above for the rest. `shell` is enabled
by default; `websearch` and MCP Resources require their opt-in configuration.

- `calculator` — evaluates a plain arithmetic expression (numbers,
  `+ - * /`, parentheses, unary `+`/`-`). No variables, functions, or
  code — expressions are parsed into a restricted syntax tree, never
  `eval`'d. Bounded to 256 characters, 64 syntax-tree nodes, and values up
  to `1e100`; division by zero and anything else out of bounds comes back
  as a Tool error the model can see and correct.
- `current_time` — takes no arguments and returns the current UTC time as
  an ISO-8601 timestamp with an explicit UTC offset.

The selected model must support Tool calling — the same two Tools are
offered regardless of which Provider answers. If a Provider's API rejects Tool support for
a model, the REPL prints one readable `Error:` naming the Provider and
model; that failure never retries.
Invalid Tool schemas retain the Provider's request-error diagnostics.

A request can go through at most 50 Tool rounds by default; set
`PA_MAX_TOOL_ROUNDS` to a positive decimal integer to change this limit.
Questions, rejected operations and Tool errors count as rounds. After the
last permitted round, the model can give a final answer; another Tool round
fails before execution. The independent limit is 16 Tool calls per round.
The configured Provider/model
captured at the start of a request answers all of it — a Tool
follow-up always goes back to the same Provider/model, with its own
transient retry allowance. Like any other
request, a Tool round that fails or is interrupted stays outside completed
Conversation/history, while its completed prefix is saved for explicit `/retry`.
Unfinished batch calls are marked interrupted or not executed; earlier completed
turns, Call Log entries and spending remain intact. `/history` shows completed
turns with their Tool calls and results.

As each Tool call executes, the REPL prints one line for it before the
answer, e.g. `tool> calculator(expression="2+2") -> 4`, colored yellow on
success and red on error when color is enabled, plain otherwise (including
piped mode) — cut to 120 characters for a large result. The model's
intermediate text sent alongside a Tool call is not printed live; it still
shows up in `/history` and the Call Log.

### Local MCP Resources

Set `PA_MCP_SERVER` to one JSON server definition, for example:

```sh
export PA_MCP_SERVER='{"name":"notes","command":"/path/to/server","args":["--stdio"]}'
```

Unset or blank disables MCP and launches nothing. The model can call
`mcp_list_resources`, `mcp_list_resource_templates`, and `mcp_read_resource`
for a URI, including one built from a listed template. Each approved operation
starts a fresh server process and closes it afterward. Plan and build confirm
every operation before launch; auto validates and runs without a prompt.
Reads accept text only. Lists stop at 100 entries, 10 pages, or the deadline
once a page arrived (partial, marked truncated), and every result is capped at
32 KiB of JSON within a 30-second operation deadline. The SDK
passes only available `HOME`, `LOGNAME`, `PATH`, `SHELL`, `TERM`, and `USER`
values on POSIX by default; use a user-owned wrapper if the server needs a
custom environment. The server runs under your account with its own host
access. Built-in Workspace Root file checks do not confine it, and exposing
only Resource operations does not make the executable itself read-only.
