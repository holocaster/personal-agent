# personal-agent

A terminal LLM agent: every task and Compression runs on one explicitly selected Provider/model pair.

## Language

**Model selection**:
The concrete Provider/model pair explicitly chosen by the user for later tasks and Compression. Selection never changes automatically.
_Avoid_: tier, automatic routing.

**Router**:
The function that runs a task through the Provider/model in its immutable Runtime Configuration snapshot. It does not select models or own Session lifetime.
_Avoid_: agent, orchestrator (the agent is the whole system; the Router is one function inside it).

**Model catalog**:
Cached Models.dev metadata associating API-key Provider model IDs with declared capabilities and limits. ChatGPT uses its connected-account model listing. Neither catalog proves successful inference or complete runtime compatibility.
_Avoid_: account entitlement, model benchmark.

**Runtime Configuration**:
The selected Provider/model pair, credentials or ChatGPT account binding, ChatGPT reasoning preference, context settings and Tool-round allowance currently used by a Run. Changes apply to later tasks or explicit Retry; an in-progress task retains its configuration and catalog-capacity snapshot.
_Avoid_: environment (the process environment is only one source of configuration).

**Provider**:
An external API the Router can call to run a model, reached through the Provider Contract. Five exist today: OpenRouter, Anthropic, OpenAI, Gemini and ChatGPT. The user selects one Provider/model pair; a routed task stays on it through retries and Tool follow-ups.
_Avoid_: backend, endpoint.

**ChatGPT plan**:
The individual user's ChatGPT subscription and associated usage allowance that they authorize Personal Agent to use. Each user connects their own account; the maintainer's subscription is not shared with other users.
_Avoid_: shared application quota, API credit balance.

**Provider Contract**:
The common exchange shape every Provider implements: prepare complete model-facing input, then `call(model, system, messages, ..., max_output_tokens, prepared_input, session_id=None) -> (AssistantMessage, usage)`. Optional Tools and replay accompany the bounded request; optional `session_id` is metadata outside prepared input/token counting, transmitted by OpenRouter and accepted/ignored by other Providers, while translation, termination/error classification, retryability and reported usage stay inside the Provider and normalized usage survives failed Attempts.
_Avoid_: adapter, SDK wrapper (no vendor SDKs are used - see Decisions).

**Estimated Cost**:
A Call Log Attempt's `cost` computed from locked local LiteLLM pricing and normalized input/output/cache evidence rather than reported by the Provider, marked `cost_estimated: true`; OpenRouter's reported cost remains authoritative. Invalid, unsupported or incomplete required pricing evidence leaves cost unavailable, and Run spend charges each available physical Attempt once without rewriting historical costs.
_Avoid_: actual cost, billed cost (when the flag is true, it's neither).

**Session cache affinity**:
The best-effort association between requests from one Session and a Provider's processing location to improve reuse of matching prompt content. It is per model and guarantees neither cache hits, survival after idle time nor reuse across models.
_Avoid_: model cache, guaranteed cache hit.

**Prompt cache activation**:
The request marker asking Claude models to cache the reusable prompt prefix. It is always on for Claude routes and guarantees no cache hit or saving.
_Avoid_: Session cache affinity (OpenRouter routing hint), guaranteed cache hit.

**File checkpoint**:
One private exact before/after restore set for the latest Session/Run/opening execution changed by `write`, `edit` or `apply_patch`, including failed/interrupted work, coalescing canonical paths to first before-state and final after-state with bytes, absence, modes and link identity. `/recover` previews and requires literal `yes` outside plan, refuses whole-set conflicts and consumes availability after durable success; shell effects and earlier Retry executions are outside the set.
_Avoid_: Conversation checkpoint, full workspace backup.

**Prompt surface snapshot**:
A deterministic offline fixture of complete System Prompt text and ordered canonical Tool schemas captured through production Router/Provider requests for plan/build/auto. It uses isolated synthetic context and blocked network, complements behavioral tests, and measures neither quality nor cache savings.
_Avoid_: Session snapshot, Provider replay, benchmark.

**Attempt**:
One try to call the selected Provider/model. The Router retries transient failures up to a fixed budget on that same pair; the Call Log records each Attempt separately.
_Avoid_: call, request, retry (retry is the act; Attempt is the thing being retried).

**Run spend**:
The Call Log's in-memory sum of available recorded API Attempt costs during the current Run, including estimates, failed Attempts and Compression. Missing costs and ChatGPT plan costs stay unknown; Resume resets the sum. There is no monetary cap.
_Avoid_: Context Budget (token allowance).

**Fork**:
A new child Session started from the latest closed turn of the current Session, carrying a copy of its Conversation, Conversation Summary and Todo List and naming its parent. The REPL continues in the child; the parent stays unchanged and resumable. The child's spend starts at zero.
_Avoid_: branch, clone, Resume (a Resume never creates a Session).

**Session**:
One conversation with the agent, identified by a Session Id generated when it first starts. It spans one or more Runs: the first starts it fresh, each later one Resumes it. Owns exactly one Conversation and one Call Log file; both are scoped to it and named after it.
_Avoid_: invocation, process (a Session outlives any one process; see Run).

**Run**:
One REPL process execution within a Session, from start to exit. A Session's first Run starts it; every later Run is a Resume.
_Avoid_: session (a Session may span many Runs).

**Session Report**:
The bounded local `/report` view of recorded activity across the current Session's Runs, with Session/purpose aggregates before the latest 20 explicit submission/Retry executions and up to 16 purpose/route groups each. It preserves independent metric coverage and cost provenance, uses compatible same samples for cache fractions, and treats observed route/cache changes as evidence without claiming causality or savings.
_Avoid_: Run spend (the report spans Runs), benchmark (the report describes recorded activity).

**Streaming Output**:
Incremental ordinary assistant text shown before an exchange completes. Partial output remains provisional; Tool execution and completed Conversation state require a validated complete response. Compression content is internal maintenance output.
_Avoid_: completed answer (until the exchange succeeds).

**First-text latency**:
Elapsed time from Provider dispatch to the first non-empty safe ordinary text delivered to the terminal, excluding reasoning and Tool arguments and including local protection/output delay. A stream with no delivered assistant text has no first-text measurement; this is not a measurement of the Provider's first generated token.
_Avoid_: generation time, total latency.

**Resume**:
Starting a new Run of an existing Session, named by its Session Id or `last` for the most recent one. The Conversation is rebuilt by replaying the Call Log in order, so it equals the live Conversation at the end of the last Run: a clear empties it, a successful Turn End adds its turn, an Undo removes the latest turn, and a Compression sets the Conversation Summary and keeps the two most recent turns. Only Call Log version 3 can be resumed; older formats are refused before append and remain untouched.
_Avoid_: restore, reload, continue, fork (a Resume never creates a new Session).

**Turn End**:
The Call Log entry closing every routed turn, with a status: `ok` (the turn entered the Conversation, and its messages are recorded), `error` (the error shown to the user), or `interrupted`. Every routed turn is opened by an explicit record: `routed_task_submitted` for a new task, `routed_task_retried` (original ordinal and current Provider/model) for Retry. Only those records open a turn and only Turn End closes it; Attempts never open or close one, so maintenance Attempts (Compression) are never dangling turns. An opened turn without its Turn End before the next opening, Run boundary or end of log means the process died mid-turn.
_Avoid_: turn result, response.

**Session Id**:
The identifier generated once per Session: a sortable UTC timestamp plus a short random suffix, so listing a directory of Call Log files already shows session order. Names its Call Log file and supplies OpenRouter ordinary request affinity; auxiliary requests append deterministic purpose suffixes without creating another Session identity.
_Avoid_: request id, trace id (request IDs identify individual Provider requests, not the Session).

**Call Log**:
The JSONL record of one Session's activity across all its Runs: Session start/resume/end, Attempts, Tool executions, Turn Ends, Conversation changes, explicit submission/Retry openings and their Provider/model routes, plus compact Audit Events for local decisions and coverage markers for detailed tracing. It rebuilds Conversation, submission ordinals and pending continuation on Resume; compact `file_recovery_started`/`file_recovery_finished` records attribute recovery and invalidate matching continuation, while exact file images live solely in the private recovery companion and full model-facing exchange details in the optional audit companion.
_Avoid_: audit log, call history.

**Audit Event**:
A recorded action or state change observable by Personal Agent during a Run, including failures and rejected actions. It does not claim to capture effects inside an external process such as `shell` or provide tamper-proof evidence.
_Avoid_: filesystem snapshot, keystroke, replay.

**Detailed Audit Payload**:
The opt-in record of what a Provider exchange actually presented to the model (System Prompt, messages, and Tool definitions) and the returned answer, linked to its Call Log Attempt. It excludes HTTP headers and API credentials.
_Avoid_: raw HTTP dump, deterministic replay.

**Conversation**:
The ordered sequence of user, assistant, and Tool messages kept by one Session. It lives in memory during a Run and is rebuilt from the Call Log on Resume.
_Avoid_: session (Conversation is the message history; Session is the conversation that owns it — see Session).

**REPL Command**:
A local instruction beginning with `/` that the REPL handles rather than submitting its text as a task. Retry and Compression can run model inference; connection and model-catalog commands can also make network requests.
_Avoid_: tool call (which is requested by a model during a routed task).

**Tool**:
A named, allow-listed local function which a model may request during a routed task. Workspace Tools and path-based Mutating Tools remain confined to the Workspace Root; the `skill` Tool may also read validated user-global skills. The default-enabled `shell` Tool starts in the Workspace Root but is not sandboxed; Network Tools and configured MCP servers also reach beyond it. Every Tool remains explicit and allow-listed.
_Avoid_: plugin, command.

**Tool Registry**:
The single place that declares every Tool: its name, description, argument schema, and function. Argument schemas declare the shape advertised to Providers and validated locally. `skill` additionally requires exactly one of `name` or `names` before loading instructions.
_Avoid_: tool list, tool table.

**Skill**:
Reusable instructions in a workspace-local `.agents/skills/<name>/SKILL.md` or user-global `~/.agents/skills/<name>/SKILL.md` file; a valid workspace copy takes precedence. The user can activate multiple immutable snapshots for the current Run with `/skill <name>`, remove one with `/skill off <name>`, or remove all with `/skill off`. Their instructions accompany later routed requests without granting Tools or changing Tool Confirmation. A new Run, including Resume, starts without active skills.
_Avoid_: Tool (a Skill is instructions, not a callable function), Memory Note (a Skill is a reusable file, not a global fact).

**skill Tool**:
A read-only Tool that advertises effective Skill names, descriptions and origins and lets the model load one or several skills on demand as a Tool result. It does not change the Run's manually activated skills.
_Avoid_: `/skill` (a REPL Command that activates Skills for subsequent turns).

**Subagent** (feature 0056):
A named execution delegated by a parent task with its own Conversation, using the parent task's selected Provider/model and shared Workspace Root. Its declared Tool restrictions apply within the parent's Agent Mode and confirmation requirements; the first version runs one Subagent at a time.
_Avoid_: Fork (which copies an existing Conversation and switches the interactive Session), Background Job (a shell process, not a delegated model task).

**Workspace Root**:
The resolved process starting directory a Run's workspace Tools may inspect, captured once for the Run. Model-supplied paths are always relative to it.
_Avoid_: current directory, project root (the process can start in any directory).

**Workspace Tools**:
The three read-only built-in Tools: `list_files`, `read_file`, and `search_text`. They inspect only the Workspace Root and retain the Tool Registry's normal validation, logging, and result handling.
_Avoid_: filesystem access, shell access (neither is granted).

**Read Window** (feature 0021):
The contiguous range of lines one `read_file` call returns, chosen by a 1-based line `offset` and a line `limit` (default 500). Each returned line carries its line number as a prefix, which is not part of the file. A file of any size can be read one Read Window at a time; the model never receives a whole file unless it fits one window.
_Avoid_: chunk, page, partial file.

**Tool Output Cap** (feature 0021):
The most bytes one Tool call may hand back to the model, set by `PA_MAX_READ_BYTES` (default 32 KiB). It bounds what enters the Conversation, not the size of any file on disk. A Read Window or search result that would exceed it is cut short, never rejected.
_Avoid_: read limit, file size limit (the file itself is unbounded).

**Mutating File Limit** (feature 0021):
The largest file `write`, `edit`, or `apply_patch` may load or produce, set by `PA_MAX_WRITE_BYTES` (default 1 MiB). It applies to both the existing file and the result. It protects memory and the Tool Confirmation diff; nothing under it is sent to the model.
_Avoid_: write cap (it limits the existing file too), Tool Output Cap (a different limit).

**Mutating Tools**:
The four built-in Tools with a permanent side effect: `write` (creates a new file, or overwrites an existing one, with the full given content), `edit` (replaces the one exact occurrence of `old_string` with `new_string` inside an existing file, or every occurrence when `replace_all` is set), `apply_patch` (applies one Patch), and `shell` (runs one command string). `write`, `edit`, and `apply_patch` resolve their paths through the same bounds as Workspace Tools; `shell` always runs in the Workspace Root itself, with no path or `cwd` argument to resolve. Confirmation depends on Agent Mode.
_Avoid_: Workspace Tools (that term stays read-only), write access (too vague).

**Tool Confirmation**:
The REPL prompt shown in `build` before a Mutating Tool or a Network Tool executes (and in `plan` for Network Tools). It displays the diff (or, for a `write` creating a new file, the full content; for `apply_patch`, one combined diff for every file in the Patch; for `shell`, the exact command string; for `webfetch`, the URL; for `websearch`, the query) and asks the user to approve or reject. A Dangerous Command escalates to Strong Confirmation. In `auto` only recognized Dangerous Commands show a confirmation; other Mutating and Network Tools run after validation without prompting. Workspace Tools, `todo` and `question` run without Tool Confirmation in every mode. `question` collects answers, which never approve another Tool.
_Avoid_: permission, approval (generic elsewhere; this is the project's one specific gate).

**Question Tool**:
The model-facing way to ask the user for clarification during a routed turn and continue with the answers in that turn. Choice labels may be strings or text-only objects; both display and return as plain labels under the same bounds. A question answer is user input, not Tool Confirmation for any other Tool.
_Avoid_: REPL Command, Tool Confirmation, plan approval (answering does not authorize a workspace change).

**Patch** (feature 0028):
One `apply_patch` argument in the OpenAI/Codex patch envelope (`*** Begin Patch` ... `*** End Patch`) that adds, updates, or deletes one or more files. Update hunks are located by exact context lines and optional `@@` anchors, never by line numbers. A Patch applies whole or not at all.
_Avoid_: diff (a diff is what Tool Confirmation shows; a Patch is what the model sends), unified diff (not accepted).

**shell Tool** (feature 0018):
The Mutating Tool that runs one command string through `bash -c` (falling back to `sh -c` when `bash` is not on `PATH`), always in the Workspace Root, with no `cwd` argument and no stdin (`DEVNULL`). Registered by default; `PA_ENABLE_SHELL=0` keeps it out of the Tool Registry, so it is never offered to a Provider. A non-zero exit code is a normal result (`{stdout, stderr, exit_code}`), not a Tool error; only a timeout, a missing shell binary, or an internal failure raises one.
_Avoid_: Workspace Tools (shell is mutating, not read-only), sandbox (there is no sandboxing; the confirmation policy depends on Agent Mode).

**Background Job**:
A shell command started by the model that keeps running after its Tool call returns, owned by the current Session in the current Run and ended by an explicit stop, a Fork or the end of the Run. It is not persisted and never survives Resume.
_Avoid_: daemon, service, task (a task is a routed user submission).

**Dangerous Command** (feature 0023):
A `shell` command string that matches one of a fixed set of rules in the code: recursive `rm` on `/`, `~`, `$HOME`, `*`, `..` or an absolute path outside the Workspace Root; history-destroying Git (`reset --hard`, `clean -f`, `push --force`, `checkout -- .`); disk and filesystem writers (`mkfs`, `dd of=`, redirection to a block device); recursive `chmod`/`chown` on `/` or `~`; a fork bomb; `sudo`; or piping or evaluating data into a shell or interpreter (`| sh`, `| bash`, `| python`, `eval`, `bash -c "$(...)"`, `source <(...)`). Detection is a warning, not a block: it requires Strong Confirmation in `build` and `auto`. The rules cannot be changed by configuration.
_Avoid_: blocked command (nothing is blocked), blocklist (the list escalates confirmation; it does not deny).

**Strong Confirmation** (feature 0023):
The Tool Confirmation variant for a Dangerous Command: the rules that matched are shown in red, and only typing `yes` in full approves - `y` rejects. The same holds for piped input.
_Avoid_: double confirmation (there is still one prompt).

**Fetched-Content Warning** (feature 0023):
A line added to a Tool Confirmation of `shell`, `write`, `edit`, or `apply_patch` after a successful `webfetch` in the same turn, naming the fetched URL(s). Successful `websearch` results similarly add a warning identifying external search content. In `auto`, this appears only for recognized Dangerous Commands, since other calls skip confirmation. Rejected or failed calls do not add warnings; the warnings change what is shown, not what approves.
_Avoid_: taint (implies tracking data flow, which is not done).

**Network Tool** (feature 0022):
A built-in Tool that reaches outside the machine: `webfetch` reads one `http`/`https` URL, while opt-in `websearch` sends a query to Tavily and returns bounded source links and excerpts. Neither changes the workspace, but a URL or query can carry workspace content out, so `build` and `plan` require Tool Confirmation; `auto` skips it.
_Avoid_: Mutating Tool (neither changes the workspace), unrestricted browsing (each request is a bounded Tool call).

**Web Search**:
Discovering candidate web pages from a query and returning source URLs with short descriptions. Reading a selected page remains a separate `webfetch` action.
_Avoid_: webfetch (it reads a URL already known), browsing (implies navigation and interaction).

**Todo List** (feature 0022):
The model's own ordered checklist for the current task, written only through the `todo` Tool, which replaces the whole list on every call. Each item has content and a status: `pending`, `in_progress`, `completed`, or `cancelled`. It belongs to the Conversation: `/undo` restores the list as it was before the undone turn, `/clear` empties it, Resume rebuilds it from the Call Log, and Compression leaves it unchanged. While any item is `pending` or `in_progress`, it is sent in the System Prompt; a finished list is not.
_Avoid_: task list (a task is what the user types), plan, Memory (the Todo List is per-Session and written by the model).

**Terminal**:
The REPL presentation layer: line input, interactive Input Box, color and spinner rendering, command handling, and visible Tool results. It delegates routing and does not own Provider or Tool behavior.
_Avoid_: Router, UI framework (the terminal remains a line-oriented CLI).

**Personal Agent**:
The whole application: its terminal, Tools, routing policy, and Provider adapters. Its Python package name is `personal_agent`; Router is one capability within it.
_Avoid_: Router (the Router does not include the rest of the application).

**Project Instructions**:
Workspace-specific guidance from the root instruction file and its explicit file references. An ordinary task keeps one snapshot; changes take effect on the next task or Retry, beneath explicit user requests and application execution gates.
_Avoid_: Memory (global user facts), Skill (optional reusable guidance).

**System Prompt**:
The instruction text sent to the Provider ahead of the Conversation, rebuilt for every exchange: ordinary requests put application identity, fixed Tool/trust rules, current Agent Mode and language behavior before task Project Instructions, Memory, active Skills in activation order, Conversation Summary and unfinished Todo List. Variable context preserves preceding stable bytes; project/mode/catalogue changes may alter them, Compression offers no Tools, and current date/time come from `current_time`.
_Avoid_: preamble, persona.

**Input Box**:
The bottom-anchored area of an interactive REPL where the user types, framed by horizontal rules. Finished output scrolls above it into the terminal's own scrollback.
_Avoid_: prompt (the `user> ` text of the non-interactive mode), composer.

**Status Footer**:
The single line under the Input Box showing current Agent Mode, selected Provider/model, its access method (`API key` or `Assinatura ChatGPT`), current input occupancy over the effective input ceiling (unknown when stale or unassessed), Run API spend with coverage on API routes only, `Cota atingida` after plan exhaustion and a `/help` hint. ChatGPT routes never show a money counter.
_Avoid_: status bar, toolbar.

**Agent Mode**:
The user-selected `plan`, `build`, or `auto` setting for one Run. `plan` lets the agent investigate and discuss without changing the workspace; `build` permits Mutating Tools with Tool Confirmation; `auto` permits the same Tools without ordinary confirmation but keeps Strong Confirmation for recognized Dangerous Commands. Every Run starts in `build`. The mode is independent of Model selection.
_Avoid_: Model selection, automatic mode selection.

**Auto Agent Mode** (feature 0033):
The third user-selected Agent Mode, with the same Tool availability as `build`: ordinary Tool Confirmations are automatic, while recognized Dangerous Commands still require Strong Confirmation. Like the other modes, it is Run-local and independent of Model selection.
_Avoid_: automatic mode selection, Model selection.

**Undo**:
Conversation-only removal of the most recent successful turn with `/undo`, recorded so Resume does not bring it back. It does not restore workspace files or remove the latest File checkpoint.
_Avoid_: rollback, revert.

**Retry**:
Explicitly continuing a failed/interrupted routed task with its completed prefix, including after Resume, or intentionally rerunning a successful task with `/retry` (Undo first if still last), using current routing, configuration, mode and confirmation policy. Each Retry keeps the original ordinal in a distinct execution; matching recovery intent, including inherited Tool prefixes, replaces obsolete pending work with a fresh request while preserving unrelated pending work.
_Avoid_: regenerate, rerun.

**Context Overflow Recovery**:
One retry of the same rejected Provider/model exchange after safely reducing older context. Positive Provider-specific overflow evidence is required; a failed recovery stops the pending turn. This is separate from transient Attempts and explicit `/retry`, and never repeats already executed Tools.
_Avoid_: task retry, Escalation, partial-turn Resume.

**Compression**:
Replacing older complete turns and the prior Conversation Summary with one final summary while retaining the two most recent complete turns and the entire in-progress turn. The user invokes it with `/compress`, or budget pressure triggers it before a pending exchange. Bounded Attempts on the selected Provider/model count toward spend; failed construction retains the prior Conversation.
_Avoid_: compaction, truncation (Compression produces a summary rather than silently cutting content).

**Context Limit**:
A Provider/model route's supported total, input or output token capacity. Each field resolves from an exact manual override, then Models.dev, then local LiteLLM metadata, then a labeled assumption.
_Avoid_: Context Budget (the user's allowance), Context Window (Conversation content).

**Conversation Summary**:
The text a Compression produced. It is sent in the System Prompt, not as a message, and `/history` shows it before the remaining turns. A later Compression summarizes the previous summary together with the turns it replaces.
_Avoid_: memory, digest, Memory Note (Memory is global across every Session and written explicitly by the user; Conversation Summary is per-Session and produced automatically by Compression).

**Memory Note**:
One short fact, preference, or decision the user records explicitly with `/remember <text>`, stored with the timestamp it was added. Scoped globally, not to any Session or Workspace Root — it exists before, during, and after any particular Session.
_Avoid_: Conversation Summary (per-Session, produced automatically by Compression), Call Log entry (per-Session record of an Attempt or Tool execution).

**Memory**:
The full ordered set of Memory Notes for one installation, stored as one JSONL file (one `{"text": ..., "added": ...}` object per line) at `PA_MEMORY_PATH`, defaulting to a fixed path (`~/.personal_agent/memory.jsonl`) rather than one relative to the cwd or Workspace Root, so it stays the same across every Session and every directory the agent runs from. Injected into the System Prompt on every Run, ahead of the Conversation Summary. Written only through `/remember`; no Tool can write to it, so it carries no LLM curation and no extra Attempt cost. `/memory` lists its Memory Notes with a positional index; `/forget <index>` removes the one at that index. Unbounded — `/remember` prints a one-time REPL warning (never logged, never repeated on a later Run) when total Memory content passes roughly 2000 characters, but nothing is capped or truncated automatically. Memory Notes and their removal are never written to the Call Log; the JSONL file itself is Memory's only record.
_Avoid_: memory (generic; capitalized Memory is this specific concept), context (too broad), skill, learning (Memory stores facts the user chose to write down, not behavior the agent inferred or improved on its own).

**Context Window**:
All retained complete Conversation turns offered with a routed task, subject to the complete exchange's Context Budget. A model Tool request and its results remain together; there is no fixed 20-turn selection.
_Avoid_: history (the full session record).

**Context Budget**:
The persistent, user-configured total token allowance for a Provider exchange, including all model-facing input and reserved output. A task keeps the allowance and route overrides it started with; supported route capacities can reduce its effective budget.
_Avoid_: Context Limit (capacity), Run spend (money), history limit (only one part of the input).

## Decisions

- **Project log storage** (0050 ticket 01): Workspace Root is always the resolved starting cwd. `PA_WORKSPACE` and `PA_LOG_PATH` are removed. Call Logs and audit companions use `~/.personal_agent/logs/<readable-path>--<12-hex-hash>/`; the readable component is bounded to 96 characters and the hash derives from the full resolved path. Start/resume records carry project/root/Run identity. Safe descriptor-relative opens refuse directory/file links and nonregular targets. `--resume last` uses the latest valid physical Run boundary in the current project, not Session creation or file modification time; strict replay still validates the selected log. See ADR-0008.
- **Project Instructions** (0049): root `AGENTS.md` wins; `CLAUDE.md` is used only when AGENTS.md is absent. Explicit bare, bracketed and quoted `@file` references expand recursively from each resolved source's parent, within Workspace Root and existing secret/symlink exclusions. Code examples and emails remain literal; aliases contribute once and active cycles fail. Fixed bounded-read limits are 64 KiB per file, 256 KiB unique source bytes, 64 files, depth 16 and 512 KiB expanded text. Startup validates before Session activity; each task/Retry reloads, then keeps its snapshot through all exchanges. Invalid reloads stop before dispatch while preserving repairable pending work and attribution. Full instructions remain protected in ordinary context estimates and Compression candidates; summary calls omit them. Resume uses current files without a new persistence schema. Source paths are shown safely, never instruction bodies.
- **Provider scope**: five native Providers (OpenRouter, Anthropic, OpenAI, Gemini and ChatGPT) call REST APIs through stdlib `urllib`, without vendor SDKs. Delegation to full coding CLIs such as `claude exec` or `codex exec` remains outside this contract: those agents own their own Tools and execution loop. See ADR-0002/0015.
- **Provider authentication**: OpenRouter, Anthropic, OpenAI and Gemini use their own API keys. ChatGPT subscription access is implemented in feature 0057 through per-user browser authorization and explicit plan consent; it does not establish subscription access for other Providers. See ADR-0015.
- **ChatGPT Provider scope** (0057): one connected account per installation, switched by logout/login, with local browser authorization. Preserve registration identities internally, without an account selector. Plan exhaustion stops for explicit user action and `/retry`; no automatic waiting or Provider fallback. Remote/headless setup is outside this version's scope.
- **ChatGPT output and model discovery** (0057): follow the documented contract by omitting `max_output_tokens`; output reservation is an estimate without a guaranteed remote cap. The account model listing supplies ChatGPT choices independently of Models.dev admission; public metadata can complement capacities, with assumed limits identified. Neither listing nor public metadata proves successful inference.
- **Access-method visibility** (0057): the TUI explicitly identifies ChatGPT plan versus API-key use alongside the active Provider/model. The indication follows the selected route; merely connecting an account does not change it. Unconfigured or disconnected routes must not appear ready.
- **Plan footer** (0057): the active ChatGPT route shows no monetary counter. Earlier API costs remain recorded and available in usage/report views; missing plan cost is unknown, never evidence of zero billing.
- **Context visibility** (0057): both access methods show estimated complete input versus effective input allowance in the footer. This occupancy is distinct from accumulated token usage and accounts for the configured budget, route capacity and output reservation.
- **ChatGPT connection flow** (0057): `/connect chatgpt` authenticates locally and offers account model selection; `/disconnect chatgpt` disconnects, and `/config` shows connection status. The REPL remains accessible without a usable route. A model selection needing authentication offers connection before activating the route; cancellation or failure preserves the previous selection.
- **ChatGPT account changes** (0057): switching accounts preserves normalized Conversation text with an explicit notice before it is sent to the new account. Opaque replay stays bound to its originating registration; switching accounts does not require clearing the Conversation.
- **LiteLLM scope**: current code uses `cost_per_token()` for Estimated Cost, `get_model_info()` for route capacity fields absent from Models.dev and manual overrides, and its local token-counting utility for complete input estimates. Estimates use local tokenizer assets and are labeled approximate; unavailable counting stops visibly before dispatch. Its own `completion()` call/routing surface remains excluded — the Provider Contract and dispatch stay hand-rolled. See ADR-0002.
- **Selected Provider credentials**: require only the selected API-key Provider's key, or the connected account for ChatGPT. There is no default Provider/model pair. Exported settings override starting-directory settings, which override home settings; an unready route leaves the REPL available for setup while dispatch stays blocked.
- **hermes-agent relationship**: reference agents are inspiration only, not dependencies or forks of this codebase. Research snapshots live in `docs/research/`.
- **Direct Model selection** (0054/0057): `/model` and `/config` validate the exact pair against its API catalog and key, or connected ChatGPT account listing. Save both settings atomically before activation for later tasks/Retry; invalid input, cancellation and save failure retain the previous pair. No evaluator, tiers, automatic substitution or monetary cap remains. Task snapshots retain their pair through Tools, transient retries and automatic Compression; manual Compression snapshots the current pair. See ADR-0011/0015.
- **Catalog admission** (0054/0057): API-key routes use Models.dev (`google` maps to `gemini`), with an explicit refresh and a persistent cache used at any age. No usable cache permits one bounded fetch. Catalog failure or rejection keeps setup accessible but blocks dispatch. Failed refresh retains the cache and route; removal blocks subsequent tasks/Retry/manual-Compression without changing selection or in-flight snapshots. ChatGPT uses account listing independently; available Models.dev metadata can complement capacity. Catalog metadata proves neither account access nor full runtime compatibility. See ADR-0012/0015.
- **Call Log scope** (0054): one self-contained JSONL file per Session, using `log_version: 3`. Start/resume and explicit task/Retry openings record Provider/model and independent submission ordinals; execution identity remains `(run_id, opening position, ordinal)`. Attempts never open executions. Strict replay restores Conversation, Summary, Todo, pending work and submission count; current Runtime Configuration selects future work. Older versions are refused before append without migration/deletion. Durable-before-live/action ordering, fatal persistence failures and append-prefix restoration remain. See ADR-0003/0005/0011.
- **Prompt cache observability** (2026-09-29): the changing date/time line required by feature 0008 is removed from the System Prompt to keep its prefix stable; the `current_time` Tool supplies current date/time on demand. OpenRouter Attempts record its reported cache read/write token counts when available; missing metrics are `null`, not evidence of zero caching. The Provider-reported cost and Conversation replay stay unchanged.
- **Cache accounting/reporting** (0053 ticket 04): Anthropic normalized prompt includes disjoint input/read/write categories; OpenAI/OpenRouter/Gemini reads are subsets. Direct estimates pass inclusive prompt/cache and supplied Anthropic 5m/1h write detail to locked LiteLLM, validating applicable original local prices; absent/invalid required evidence yields unavailable cost. Omitted-zero rules affect calculation only, while report coverage retains absence; OpenAI requires both cache categories. Existing Gemini output still excludes separately reported thought tokens and can undercount cost (accepted pre-existing limitation). `/report` retains explicit Run/opening/ordinal/outcome identity, bounded details/omission notices, redaction and terminal sanitization; it changes only its existing Audit Event, with no remote call or routing/Conversation/pending/configuration/usage/spend mutation.
- **OpenRouter affinity** (0053 ticket 02): ordinary exchanges use the exact durable Session Id across turns, Tool follow-ups, retries and Resume. Compression uses `<Session Id>:compression`; standalone calls without identity omit it. The optional Provider keyword stays outside prepared input/token counting, and other Providers accept/ignore it. Existing host preferences and diagnostics remain; affinity is best effort per model and explicit selection/configuration may change the model.
- **Prompt surface** (0053 ticket 03): fixed rules and task Project Instructions precede variable context; effective Tool names/Skill descriptions sort deterministically while active Skill order and meaningful schema arrays retain semantics. Prepared-input budgets and Provider replay remain complete; stable prefix does not guarantee cache hits, savings or unchanged full-history input. Three production fixtures cover plan/build/auto; deliberate regeneration is `.venv/bin/python -m tests.prompt_surface tests/fixtures/prompt-surface`, followed by diff review.
- **Conversation lifetime**: the Call Log is the Conversation's only durable record; no separate conversation file exists. Resume continues the same Session and appends to its existing Call Log file rather than copying history into a new one. `/clear` empties the Conversation and is recorded, so a later Resume does not bring cleared turns back. Resume uses current Runtime Configuration, while recorded routes remain historical evidence. Two concurrent Runs of one Session are unsupported.
- **Tool boundary**: Tools are explicit built-ins. Workspace Tools and the `write`/`edit`/`apply_patch` Mutating Tools resolve paths only within the Workspace Root through the same bounded contract; the `shell` Mutating Tool (feature 0018) instead starts there, with no path to resolve or filesystem sandbox. Path-based Tools accept only relative paths, reject paths and symlinks outside the root, and exclude `.env`, `*.pem`, and `*.key`. Hidden and Git-ignored files otherwise remain readable. As of feature 0016, writing is in scope through Mutating Tools; as of feature 0018, so is running a shell command - this reverses the earlier "writing ... remain out of scope" line, not an addition beside it. Network Tools `webfetch` (feature 0022) and `websearch` (feature 0027) require Tool Confirmation in `plan` and `build`, but not `auto`. As of feature 0034, one opt-in local stdio MCP server (`PA_MCP_SERVER`) exposes only the read-only Resource operations (`mcp_list_resources`, `mcp_list_resource_templates`, `mcp_read_resource`) as Tools that require Tool Confirmation in `plan` and `build`, but not `auto`; the server process has its own host access and is not confined by Workspace Tool checks. MCP Tools, remote transports, multiple servers and OAuth remain out of scope. As of feature 0024, the local `/config` REPL Command can edit the selected Provider/model pair and Provider keys without exposing an environment-editing Tool to the model.
- **File recovery** (0053 ticket 05, ADR-0010): owner-only `recovery-<Session Id>/` companions (0700/0600) retain exact images; bounds are min(current `PA_MAX_WRITE_BYTES`, 4 MiB)/image, 64 canonical paths, 16 MiB combined images, 24 MiB/manifest and 80 MiB latest/active/temp per Session. Unsafe storage/path/link/owner/permissions, integrity mismatch, external edits and would-exceed operations refuse. Workspace read/list/search and Project Instructions references exclude same/cross-project recovery storage, including resolved aliases and recursive traversal. `/recover` previews identity/outcome/reverse diff and requires literal `yes` even auto/piped; plan permits preview only, with revalidation after confirmation. Partial restore rolls back where possible; failed persistence/rollback or mixed interrupted states remain explicitly unresolved and stop unsafe dispatch/mutation. Resume reconciles but never auto-restores. Recovery intent durably clears only matching contributor lineage (assistant/Tool prefix, Todo effects, fetched URLs and Gemini replay), preserving request/ordinal for fresh Retry and unrelated later pending work. Successful Conversation, Summary and submission ordinals remain intact; read-only/Clear/Undo/Compression retain the checkpoint, success consumes it, and there is no older-checkpoint stack or redo.
- **Mutating Tools scope** (feature 0016): `write` only creates a file inside a directory that already exists - no implicit parent-directory creation, unlike the reference project `opencode` (deliberately not replicated, to keep the change minimal). `write` and `edit` are bounded by the Mutating File Limit (feature 0021), not by the Tool Output Cap. `edit` requires `old_string` to match exactly and exactly once, erroring on zero or multiple matches, unless `replace_all` is set - no fuzzy/similarity-based matching (`opencode`'s multi-strategy Levenshtein matcher was evaluated and rejected as unneeded complexity for this project's size). Approved `write`/`edit`/`apply_patch` operations durably capture bounded intent before mutation and observed after-state before dependent dispatch, preserving single-file partial-write and patch rollback. New regular files use mode 0600; existing modes are preserved. File checkpoints allow latest-execution recovery without Git; shell effects remain outside the set.
- **shell Tool scope and opt-out** (feature 0018, default flipped 2026-09-24; mode policy updated by feature 0033): `PA_ENABLE_SHELL` gates registration, not just execution - `0` keeps `shell` out of the Tool Registry entirely. Originally opt-in (`1`); flipped to on-by-default because Tool Confirmation already gated every command at that time, and an agent without a shell could not do basic tasks (e.g. measuring disk usage). In `build`, Tool Confirmation shows the exact command string; recognized Dangerous Commands require Strong Confirmation in `build` and `auto`. In `auto`, unflagged commands run without a prompt, even with piped input; EOF rejects only a prompted Dangerous Command. Nothing is blocked outright and there is still no allowlist. A sandbox (`bwrap`, installed and working unprivileged on the user's machine) was considered in feature 0023 and deferred by the user: without one, an obfuscated command that matches no Dangerous Command rule runs without prompting in `auto`. The command runs via `bash -c` (`sh -c` fallback), always in the Workspace Root, with no `cwd` argument, no stdin (`DEVNULL`), and inherits the parent process's environment except `TAVILY_API_KEY` (removed from the `shell` subprocess in feature 0027). Other environment values remain inherited. `PA_SHELL_TIMEOUT_SECONDS` (default 30s) sends SIGTERM then SIGKILL on expiry, which is a Tool error; `PA_SHELL_MAX_OUTPUT_BYTES` (default equal to `PA_MAX_READ_BYTES`) truncates stdout/stderr with the same `[...truncated]` marker `read_file` uses. A non-zero exit code is a normal `{stdout, stderr, exit_code}` result, not a Tool error - only timeout, a missing shell binary, or an internal failure raise one.
- **Minimal model input** (feature 0021): the model receives only the parts of a file it asks for, never a whole file by default. `PA_MAX_READ_BYTES` stopped meaning "largest readable file" and became the Tool Output Cap, applied to `read_file`, `search_text` (whose per-match excerpts are also shortened) and, by default, `shell` output. Limits on what the model sees and limits on what `write`/`edit` may touch are separate knobs because they protect different things: context budget versus memory and the confirmation diff.
- **Package organization**: Source packages follow cohesive capabilities, not generic layers: `routing` owns Runtime Configuration and routed execution; `tools` owns Tool registry and implementations; `terminal` owns REPL presentation; `providers` owns external Provider adapters. Leaf modules without a cohesive sibling family remain at the package root. No `core`, `common`, or compatibility-shim layer is introduced for internal pre-1.0 imports.
- **Package identity**: Python source lives under `src/personal_agent`, while `src` is only the source-layout container and is never imported. The distribution and import package use the Personal Agent identity, not the narrower `model_router` name. Old internal `model_router` imports receive no compatibility shim.
- **Interactive vs piped REPL**: the Input Box and Status Footer exist only when input is an interactive terminal. Piped input keeps the plain line-oriented mode, with no framing. Input history (arrow up) lives only in memory for the Run and is never written to disk. Live Tool lines print in both modes (uncolored when piped). The Input Box is built on `prompt_toolkit`; see ADR-0004.
- **Agent Mode scope** (features 0025, 0033, 0047): `/mode` reports the mode and `/mode plan|build|auto` changes it for later routed turns without a Provider call. Shift+Tab cycles `plan → build → auto → plan` during task editing, Tool Confirmation, questions, preview inspection and Provider/Tool work, preserving drafts and answers. The current mode applies at subsequent Tool boundaries and Provider exchanges; already-running operations finish normally. Pending confirmations still require an explicit answer after switching to auto; switching to plan prevents a pending mutation even after approval. Busy input has one temporary keyboard owner, queues ordinary input for later prompts and stops before returning. Every Run, including Resume, starts in `build`; the mode is not persisted. In `plan`, the Router offers read-only Workspace Tools, `calculator`, `current_time`, `todo`, `question`, `webfetch`, and `websearch` when configured, while the Tool Registry rejects `write`, `edit`, `apply_patch`, and `shell` before validation or confirmation even if the model requests them by name. Network Tools still require Tool Confirmation. `build` keeps the existing Tool Registry and confirmations. `auto` has the same Tools as `build`, but skips ordinary confirmation for Mutating and Network Tools; recognized Dangerous Commands still require Strong Confirmation. A mode switch does not change Conversation, Todo or the selected Provider/model pair.
- **Context Window**: Every retained complete turn is available to an exchange. The Router measures the complete actual-route input before initial dispatch, retries and Tool follow-ups. Preventive Compression triggers at input reaching 80% of the effective total when older complete turns are eligible, or whenever input exceeds its independent mandatory ceiling, aiming for 60% input occupancy where preserved content permits. A failed soft-trigger Compression leaves the Conversation unchanged and still sends input that fits the ceiling. Unfittable protected input stops visibly; no silent omission, post-success trigger or synthetic Continuation Turn remains.
- **Compression**: Manual and preventive callers share fitting selected-route blocks and bounded combination of older turns/prior summary. Two latest complete turns, Todo state and the entire in-progress turn remain intact, including exact Gemini active replay/signatures. Automatic candidates are measured in the pending route before commit. Empty, malformed, non-reducing and output/context-truncated summaries fail without replacing prior state; returned usage still counts normally. Only the final summary is recorded before live state changes and the pending Turn End; failure later in that turn does not undo committed Compression. Observable partial append failure restores the prior log prefix; failed restoration stops the Run. This does not promise crash-proof storage.
- **Context Budget scope**: The persistent total defaults to 250000 tokens; capacity resolves per field from exact manual overrides, Models.dev, local LiteLLM and labeled assumptions, bounding the effective allowance. Each task keeps an immutable configuration snapshot. Ordinary exchanges reserve up to 16000 output tokens and a 10000-token margin, respecting separate input/output limits; a published input limit is a conservative known total, and only a route with no total or input metadata is visibly assumed to be 128000. No paid counting endpoint or implicit tokenizer download is used.
- **Tool round limit** (feature 0042): `PA_MAX_TOOL_ROUNDS` is a positive decimal integer, defaulting to 50, loaded at startup and preserved in each task's configuration snapshot. Every Tool round counts, including questions and rejected operations. A final answer remains allowed after the last round; excess Tool intent stops before execution. Each explicit Retry renews the allowance; the separate 16-call batch limit remains unchanged.
- **Pending turn continuation** (feature 0044): Error/interrupted Turn Ends explicitly save a validated, redacted pending prefix with submission attribution, fetched URLs and balanced Gemini replay. This stays outside completed Conversation and Compression; Retry rebases onto current older history/summary, restores Todos and commits one combined turn on success. Same-route Gemini retains original parts/signatures; route changes use normalized messages. Partial batches retain actual results and explicit unfinished outcomes. Failed pending writes stop the Run; only new-format Call Logs can Resume.
- **ChatGPT reasoning** (0058): `/reasoning` and `/config` save `PA_CHATGPT_REASONING_EFFORT`; explicit levels must be advertised by the account model, while `auto` omits the request effort. Task snapshots carry the preference through retries, Subagents and Compression; API-key Providers ignore it.
- **ChatGPT continuity** (0057 ticket 03): ChatGPT pending continuation is `version: 2` with `registration` (opaque 32-hex reference) and replay `{items, consumed, active_start: 0, active_items_start: 0}`; API/Gemini stay `version: 1`. Successful ChatGPT Turn Ends add `replay: {version: 1, provider, model, registration, items}`; Fork seeds add `replays` and `destination`. Items must correlate exactly with normalized messages or Resume is refused before append; a replay that cannot be validated at write time falls back to normalized text. Same model/registration reuses items per turn, anything else sends normalized messages. Run metadata, openings and Attempts carry `access_method` (`api_key`/`chatgpt_plan`) and ChatGPT `registration_ref`. The last ChatGPT Attempt's registration is the durable destination; sending retained text to another one prints an account notice first.
- **Context Overflow Recovery**: A positive ordinary-exchange overflow permits one same-route retry only after shared Compression produces strictly smaller complete input within the mandatory ceiling. Second rejection or unrelated recovery failure stops without another transient retry cycle. Each distinct Tool follow-up has its own allowance; summaries never recursively recover. Rejected partial answers/Tools are not accepted, while available reported usage/cost remains logged and charged once; missing counters remain unknown.
- **Memory scope and provenance**: `docs/briefs/0015-persistent-memory.md` scoped Memory down on purpose from a much bigger idea — loosely and unverifiably inspired by the kind of persistent, self-curated memory a project like `NousResearch/hermes-agent` advertises (never cloned, never a dependency, never trusted as fact; same posture as the hermes-agent relationship decision above). This feature deliberately excludes LLM-curated memory, autonomous skill creation, and any Tool-based write path for the model — those were explicitly rejected during discovery, not silently deferred. Revisit only as its own new feature or ADR; never fold into Memory's existing scope.
- **Workspace search** (feature 0022): `search_text` stays literal by default; `regex: true` switches to a regular expression, still case-insensitive. `list_files` takes an optional glob `pattern` and `search_text` an optional `glob` filter, with one shared case-sensitive semantics: a pattern without `/` matches a file name at any depth, one with `/` matches the path relative to the searched directory. A directory walk skips `.git`, `.venv`, `node_modules`, and `__pycache__` wherever it meets them below the requested path - a proven fix, since a root `list_files` returned 96 of 100 results from `.git/`. Naming one of those directories (or a path inside it) explicitly still works, so "Hidden and Git-ignored files remain readable" holds. `.gitignore` is not honoured. Shared traversal is lazy and globally POSIX-lexically ordered (0048): listings filter before their excess-match lookahead; search stops traversal when its result/output cap is established. Each visited directory still sorts its immediate children.
- **apply_patch scope** (feature 0028): `apply_patch` exists beside `write`/`edit` for every model, not swapped per model as `opencode` does, with the same availability across configured Providers. It accepts only the OpenAI/Codex envelope (Add, Update, Delete File); `Move to` and Git unified diffs are out. Context matching is exact, like `edit`: context that is missing, or repeated without a disambiguating `@@` anchor, is a Tool error. `Add File` on an existing file, `Update`/`Delete` on a missing one, the same path twice, and an empty Patch are Tool errors. Add File does not create parent directories, matching `write`. The whole Patch is validated before its single Tool Confirmation; if a write fails mid-apply, already-written files are restored from their in-memory originals, so a Patch is all-or-nothing. Deleting through `apply_patch` is included in latest-execution File checkpoint recovery, including exact original bytes and mode.
- **Skills scope** (features 0030, 0032): `/skills` lists valid effective skills from workspace-local `.agents/skills/<name>/SKILL.md` and user-global `~/.agents/skills/<name>/SKILL.md`, preferring a valid workspace copy of a duplicate name. `/skill <name>` adds an immutable snapshot to an ordered, Run-local active set; `/skill off <name>` removes one, and `/skill off` clears all. Resume starts empty. Skill content cannot grant Tools, alter Agent Mode, or bypass Tool Confirmation.
- **skill Tool scope** (features 0031, 0032): the model sees effective skill names, descriptions and origins in the Tool definition and can call `skill(name)` or `skill(names)` to load up to four instruction bodies into the current Conversation. It is available in `plan` and `build` without Tool Confirmation, revalidates files within their permitted roots, and never changes the Run's manually active set or grants Tools. Ordinary Workspace Tools remain confined to the Workspace Root.
- **Audit scope** (feature 0036): the Call Log keeps compact local-command, state-change and Tool Confirmation Audit Events in every Run; `PA_DETAILED_AUDIT=1` adds a separate, owner-only JSONL per Session with correlated Provider inputs/outcomes and local action intents for that Run. Runs with and without detail are marked independently. The companion is not read for Resume or routing. Failed detailed writes halt further actions visibly; neither file proves all external effects of `shell` or resists local tampering.
- **Claude prompt caching** (0055): one request-level cache marker with the default five-minute lifetime on the direct Anthropic Provider and on OpenRouter for `anthropic/*` models; no setting.
- **Fork** (0055): `/fork` refuses while a pending or failed turn awaits Retry. The child keeps the Run's Agent Mode and active Skills and records its parent Session Id. A failed child creation removes the child file and names the parent for Resume.
- **Background Jobs** (0055): `shell` with `background: true` keeps the same Tool Confirmation and plan refusal and returns a job id; `job_status` and `job_stop` Tools plus `/jobs` and `/jobs stop <id>`. At most four live jobs, each retaining only its latest 64 KB of output. `/clear` keeps jobs; Fork, `/exit` and Run end stop them.
- **Subagent direction** (0056): native execution through the existing Provider/Tool loop, one isolated Subagent at a time, with automatic discovery from workspace-local and user-global `.agents/agents`, `.claude/agents`, and `.codex/agents`. Each child keeps the parent task's Provider/model and inherits its Agent Mode and confirmations, narrowed by the role's Tool restrictions. Product questions return to the parent as a handoff.
- **Subagent definition and accounting direction** (0056): valid workspace definitions precede global definitions; within each scope `.agents/agents` precedes `.claude/agents`, then `.codex/agents`. Select one complete definition per name. Without a Tool allowlist, inherit the parent's available Tools; an explicit list only narrows them. Each child gets a linked Session/Call Log and contributes spend once to the parent's visible total. Parent cancellation stops the child and its jobs; interrupted children are not automatically resumed.
- **Project Session discovery** (0050): the read-only `session_logs` Tool lists, reads and searches recorded Sessions. It defaults to this project with explicit cross-project access. Last means latest Run start/resume, excluding the current Session for discovery. Interrupted Sessions remain discoverable. Reads show a historical timeline without duplicate Conversation snapshots; its Run/turn open/close state comes only from explicit records (see Turn End), and maintenance labeling (`purpose`, or task `/compress`) is stateless; literal case-insensitive search, bounded pagination and optional explicit audit access retain evidence provenance. No legacy migration or compatibility. Historical data never executes Tools or grants instructions. See `docs/briefs/0050-project-session-discovery.md`.
- **Question answers** (0050 ticket 03): choice questions append a local Other option for literal custom text. Invalid numeric selections reprompt; direct written answers and the `text: ` escape remain supported within existing bounds. Questions without choices remain free text.
