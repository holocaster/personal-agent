# personal-agent

A Python terminal agent that runs tasks, Tools and Compression on one explicitly
selected Provider/model pair. Supports OpenRouter, Anthropic, OpenAI, Gemini and
your own ChatGPT subscription.

## Setup

Requires Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).
From the repository root:

```bash
uv sync --locked
```

Choose one connection method below. Without valid settings, the REPL stays open
for setup and blocks model-backed tasks.

### API key

List eligible models, choose an exact ID, then start the agent:

```bash
uv run personal-agent --models openrouter
export PA_PROVIDER="openrouter"
export PA_MODEL="replace-with-exact-model-id"
export OPENROUTER_API_KEY="replace-with-your-api-key"
uv run personal-agent
```

API-key Providers are `openrouter`, `anthropic`, `openai` and `gemini`; only the
selected Provider's key is required. `/config` can enter keys without displaying
them and save your model selection for later tasks.

Settings load from exported variables, then `./.env`, then
`~/.personal_agent/.env`. See [environment variables](docs/ENV_VARS.md) for key
names, optional settings and defaults. Catalog listing does not prove account access.

### ChatGPT subscription

Start the agent:

```bash
uv run personal-agent
```

In the interactive local terminal, run `/connect chatgpt` to connect your own
account, acknowledge plan use and choose an account model. Eligibility and usage
allowance depend on your account. Credentials stay outside `.env` in a private
store. `/disconnect chatgpt` revokes the connection.

`/reasoning` shows the selected model's supported levels. `/reasoning high`
saves an advertised level; `/reasoning auto` restores the service default.
This setting applies only to ChatGPT. See [account details](docs/USER_GUIDE.md#chatgpt-account-and-reasoning).

### Run from another directory

Install the editable command from this repository:

```bash
uv tool install --editable .
```

Then run `personal-agent` from the project you want it to work on. That starting
directory is the Workspace Root. Code changes apply without reinstalling; after
dependency changes, rerun `uv tool install --force --editable .`.

## Daily use

Type a task and press Enter. Alt+Enter inserts a newline; Tab completes commands.
Shift+Tab cycles modes:

| Mode | Behavior |
| --- | --- |
| `plan` | Inspect and plan; file mutation and shell Tools are disabled. Network and MCP operations still require confirmation. |
| `build` | Default on every start or Resume; file changes, shell, network and MCP operations require confirmation. |
| `auto` | Run available Tools without routine confirmation; recognized dangerous shell commands still require exact `yes`. |

| Command | Purpose |
| --- | --- |
| `/model <provider> <model-id>` | Select and save the pair for later tasks or explicit Retry. |
| `/models [provider] [query]` | Browse models; `/models refresh` refreshes the API catalog. |
| `/config` | Edit model, keys, ChatGPT reasoning and context settings. |
| `/reasoning [<level>\|auto]` | Show or save ChatGPT reasoning. |
| `/retry` | Continue failed/interrupted work; retrying a successful task can execute Tools again. |
| `/undo`, `/clear` | Remove the last completed turn or clear Conversation; neither restores files. |
| `/recover` | Preview and restore the latest file-changing execution with explicit `yes`; excludes shell effects. |
| `/compress` | Summarize older context on the selected model, keeping the latest two turns. |
| `/fork` | Continue in a new child Session copied from the latest closed turn. |
| `/usage`, `/report` | Inspect current usage or recorded activity across the Session's Runs. |
| `/help` | List all commands, including Memory, Skills and Background Jobs. |
| `/exit` | Exit; `exit`, `quit` and Ctrl+D also work. |

Ctrl+C during work interrupts the task and returns to the prompt. At an idle
prompt, it exits. A new Session gets a new ID; Resume reuses the existing ID:

```bash
uv run personal-agent --resume last
uv run personal-agent --resume <session-id>
```

Resume stays within the starting project and uses current model settings.
Forks share workspace files with their parent; Subagents have their own linked
Sessions and use the parent's selected model.

Project instructions load from `AGENTS.md`, falling back to `CLAUDE.md`.
[Skills](docs/USER_GUIDE.md#skills) and [Subagents](docs/USER_GUIDE.md#subagents)
provide reusable instructions and named delegated roles.

## Costs and local data

API calls, retries and Compression can incur charges; there is no monetary cap.
ChatGPT uses the connected account's allowance. `/report` distinguishes reported,
estimated and unknown costs.

Shell is enabled by default and runs under your account without a sandbox.
Dangerous-command detection is pattern matching, not confinement. Set
`PA_ENABLE_SHELL=0` to disable it. Local MCP servers also run with your account's access.

Conversations and Tool results are stored under `~/.personal_agent/logs/`, grouped
by project and Session. Optional detailed audit (`PA_DETAILED_AUDIT=1`) records
additional sensitive input/output. Known keys are redacted; arbitrary secrets
are not guaranteed to be detected. Logs are not automatically pruned.

## Documentation

- [User guide](docs/USER_GUIDE.md): full commands, Tools, context management, logs and audit.
- [Environment variables](docs/ENV_VARS.md): configuration reference.
- [Project context](docs/CONTEXT.md): terminology and architectural decisions.
- [Project state](.ai/PROJECT_STATE.md): current feature and next action.
- [Research status](docs/research/README.md): delivered proposals, deferred work and historical research.
- [Testing guidance](tests/README.md): offline prompt/schema fixtures and regeneration.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, tests and pull requests.
Report vulnerabilities using the instructions in [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Third-party dependencies retain their own licenses.
