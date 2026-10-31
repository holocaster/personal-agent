# Environment variables

Every environment variable the project reads, in one place. Set them by hand
or via a `.env` file (loaded automatically on startup, gitignored). Precedence:
shell export, then `./.env` in the current directory, then
`~/.personal_agent/.env`.

Run `/config` in an interactive terminal to change the Provider/model pair,
ChatGPT reasoning, a Provider API key or context settings. Accepted changes take
effect for later tasks in the current Run and save to `~/.personal_agent/.env`
(owner-only permissions). Keys are entered without echo and never displayed.
An exported or current-directory value still overrides the saved home value
on the next Run; `/config` shows the winning source without showing a key.
Piped input cannot use the guided menu.

## Required

| Variable | Purpose |
| --- | --- |
| `PA_PROVIDER` | The Provider for every task and Compression: `openrouter`, `anthropic`, `openai`, `gemini` or `chatgpt` (trimmed, case-insensitive). No default. |
| `PA_MODEL` | The exact, case-sensitive model ID for that Provider; list them with `uv run personal-agent --models <provider>`. No default. |

Missing settings, credentials or catalog admission leave the REPL open for setup
while model-backed tasks stay blocked. API-key routes require an eligible offering
in the cached Models.dev catalog (one bounded fetch only when no usable cache
exists). ChatGPT uses connected-account model choices instead; run
`/connect chatgpt` in an interactive local terminal to connect and select a model.
In a Session, `/model <provider> <model-id>` or `/config` validates and saves the
pair for the next task or `/retry`.

### Required for the selected Provider

Only the selected API-key Provider's key is required. ChatGPT uses the connected
account instead of an API key.

| Variable | Required when |
| --- | --- |
| `OPENROUTER_API_KEY` | `PA_PROVIDER` is `openrouter`. |
| `ANTHROPIC_API_KEY` | `PA_PROVIDER` is `anthropic`. |
| `OPENAI_API_KEY` | `PA_PROVIDER` is `openai`. |
| `GEMINI_API_KEY` | `PA_PROVIDER` is `gemini`. |

## Optional

`PA_CHATGPT_REASONING_EFFORT` defaults to `auto` (omit the request effort and use
the service default). For the ChatGPT subscription Provider, set an exact level
advertised by the selected account model, or use `/reasoning high` / `/config`
to save it. `/reasoning` lists available levels; `/reasoning auto` recovers an
incompatible selection. API-key Providers ignore this preference.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PA_MAX_TOOL_ROUNDS` | `50` | Maximum Tool rounds per routed task; a positive decimal integer. Questions, rejected operations and Tool errors count as rounds. A final answer is still allowed after the last permitted round; an additional Tool round fails before execution. Empty, zero, negative, fractional and nonnumeric values fail startup. |
| `PA_CONTEXT_BUDGET_TOKENS` | `250000` | Total context token budget; a positive decimal integer. Includes input and reserved output. Actual route restrictions can reduce the effective allowance. |
| `PA_CONTEXT_CAPACITY_OVERRIDES` | `[]` | JSON array of exact Provider/model capacity records; edit through `/config`'s `context` choice. See below. |
| `PA_MAX_READ_BYTES` | `32768` (32 KiB) | Tool Output Cap: the most UTF-8 bytes `read_file` or `search_text` hands back in one call, and (unless overridden) `shell`'s output cap. `read_file` has no whole-file size limit; a window over the cap is cut at the last whole line that fits. |
| `PA_MAX_WRITE_BYTES` | `1048576` (1 MiB) | Mutating File Limit for existing/resulting UTF-8 content in `write`, `edit` and `apply_patch`; recovery limits each image further to `min(PA_MAX_WRITE_BYTES, 4 MiB)`. Oversized/non-UTF-8 content fails before confirmation. |
| `PA_DETAILED_AUDIT` | unset (`0`, disabled) | `1` enables the per-Run owner-only JSONL companion. Only unset, `0` and `1` are accepted; invalid values fail startup. |
| `PA_OPENROUTER_PROVIDER_DIAGNOSTICS` | unset (disabled) | Set to `1` to look up the upstream provider in a daemon thread after each successful OpenRouter exchange. Retries temporary 404 responses with up to 60 seconds of backoff (each GET has a 3-second socket timeout). The answer and Attempt latency do not wait; the lookup appends an `upstream_provider` event linked by `attempt_timestamp` to the Attempt, carrying the host name or, on failure, an `error` reason. A prompt process exit may leave the lookup unfinished. |
| `PA_MEMORY_PATH` | `~/.personal_agent/memory.jsonl` | Memory file path. Global, not tied to any Workspace Root or session. |
| `PA_ENABLE_SHELL` | unset (enabled) | Set to `0` to not register the `shell` Mutating Tool. Unset, empty, or `1` enables it; any other value is a configuration error at startup. |
| `PA_SHELL_TIMEOUT_SECONDS` | `30` | A `shell` command past this is sent SIGTERM, then SIGKILL after a short grace period. Ignored while `shell` is disabled. |
| `PA_SHELL_MAX_OUTPUT_BYTES` | effective `PA_MAX_READ_BYTES` (`32768`) | Independent cap on `shell`'s stdout and stderr; a capped stream ends with `[...truncated]`. Ignored while `shell` is disabled. |
| `TAVILY_API_KEY` | unset (`websearch` disabled) | Enables basic Tavily web searches in `plan`, `build` and `auto`; `plan`/`build` confirm each query, `auto` does not. Independent of Provider API keys and `/config`; one executed basic query costs one Tavily API credit. |
| `PA_MCP_SERVER` | unset (MCP disabled) | JSON object for one local stdio server: required `name` and `command`, optional string-array `args`. Resource operations confirm in `plan`/`build` and run without a prompt in `auto`; see [MCP Resources](USER_GUIDE.md#local-mcp-resources). |
| `NO_COLOR` | unset (color on) | Any non-empty value disables color and the spinner, same as piped output. Standard convention, see [no-color.org](https://no-color.org). |

`PA_BUDGET_USD` was removed in feature 0039. Old exported or dotenv values are
ignored; Run spend is tracked without a monetary cap.

## Context capacity overrides

Each record requires `provider`, `model`, and positive integer `total_tokens`;
optional `input_tokens` and `output_tokens` must be positive integers no
greater than that total. Unsupported Providers, duplicate identities,
unknown fields and boolean limits are rejected.

```dotenv
PA_CONTEXT_BUDGET_TOKENS=250000
PA_CONTEXT_CAPACITY_OVERRIDES=[{"provider":"openai","model":"exact-model-id","total_tokens":250000,"input_tokens":230000,"output_tokens":16000}]
```

Overrides match the exact Provider/model identity; route changes preserve
inactive records. A manual field replaces that metadata field; unspecified
input/output fields retain valid metadata restrictions. `/config` can remove
one record or clear all with `[]`. Each task keeps its starting settings;
changes apply to later tasks and Resume uses current settings. A published input
limit is the known (lower-bound) total when no total is published or overridden.
Per field, precedence is manual override, the selected offering's Models.dev
limit, local LiteLLM metadata, then `unknown; assumed` (128000 total), each
labeled in `/usage` and frozen with the task; the configured budget is unchanged. Cached input still occupies context.

For an effective total of 250000, ordinary exchanges reserve up to 16000
output tokens plus a 10000 estimation margin: the mandatory input ceiling is
224000 (or smaller with a separate input limit). Automatic Compression
triggers at 200000 estimated input (only with eligible older turns; a lone
summary is reduced only above the ceiling or in recovery) and targets 150000
best-effort; 174000 is not the 80% trigger. A failed soft-trigger Compression
within the ceiling is reported and the pending exchange proceeds. Assumed 128000 total gives a 102000 ceiling.
Complete input uses approximate local LiteLLM token estimates with encoding
and generic-fallback labels, never reported usage minus cached tokens. Only
bundled/cached tokenizer assets are used; unavailable local counting stops
visibly, with no download, paid counting or byte proxy. Older-context summaries
use paid Attempts on the selected pair; positive input/context overflow permits one
reduced same-exchange retry without Tool reruns. See
[context budgeting](USER_GUIDE.md#context-budgeting) for preservation and stops.

The Workspace Root is the resolved absolute process working directory captured
at startup. Call Logs always live under
`~/.personal_agent/logs/<flattened-absolute-path>--<12-hex-hash>/pa_log-<session id>.jsonl`;
the optional companion uses the same folder and replaces the final extension
with `.audit.jsonl`. There is no workspace or log-path override. Disabled Runs
write coverage markers only to the Call Log, never to the companion. Both files
are operator-retained (no automatic pruning); the opt-in file is sensitive and
owner-only. See
[Detailed audit](USER_GUIDE.md#detailed-audit-opt-in) for JSONL record types,
links, incomplete coverage and local access considerations.

File recovery uses owner-only `recovery-<session id>/` in the same project folder.
Exact snapshots include content and permissions, outside logs/audit/Provider input.
Only the latest changed execution is retained; shell effects and earlier Retry
executions are excluded. Fixed bounds are 64 canonical paths, 16 MiB combined
snapshot bytes, 24 MiB per manifest and 80 MiB per Session, including staging/temp.
Would-exceed mutations fail before writing. No recovery configuration is needed.
