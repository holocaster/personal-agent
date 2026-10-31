# Contributing

Bug reports and focused pull requests are welcome. For vulnerabilities, follow
[SECURITY.md](SECURITY.md) rather than posting technical details publicly.

## Development setup

Requires Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).
Fork the repository, clone your fork and run from its root:

```bash
uv sync --locked --group dev
uv run --locked personal-agent --help
```

For interactive use, follow the [README setup](README.md#setup). Real API keys
and a ChatGPT account are not required for the test suite. Use your own
credentials for any live checks; model calls can incur charges or consume your
account's allowance.

## Project layout and conventions

- `src/personal_agent/`: CLI, Providers, routing, terminal, Tools and Subagents.
- `tests/`: pytest suite, synthetic Providers and offline fixtures.
- `docs/USER_GUIDE.md` and `docs/ENV_VARS.md`: user behavior and configuration.
- `docs/CONTEXT.md`: terminology and architectural decisions.
- `docs/briefs/`, `docs/specs/` and `tickets/`: feature plans and reviews.

Repository conventions and the feature workflow are documented in
[AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md).
The [project state](.ai/PROJECT_STATE.md) records ongoing feature work.

## Validation

Run the relevant tests while working, then the full suite before submitting:

```bash
uv run --locked pytest tests/test_main.py
uv run --locked pytest
```

Replace `tests/test_main.py` with the tests relevant to your change. For prompt
or Tool schema changes, follow [fixture regeneration](tests/README.md) and
review the generated diffs. Documentation-only changes need link and command
checks rather than new tests.

## Issues and pull requests

For bugs, include the commit or version, Python version, operating system,
steps to reproduce, and expected versus actual behavior. Include the Provider
and model when relevant. Redact credentials, personal data and conversation
content from examples and logs.

For larger changes, open an issue to discuss the problem and proposed approach
first. Keep each pull request focused, explain the behavior change, include
tests for changed behavior and list the checks you ran. Update user-facing
documentation when commands or configuration change.

Do not include `.env`, API keys, account credentials, private session logs or
recovery data. For configuration examples, use placeholders in `.env.example`.

## License

Contributions are submitted under the project's [MIT license](LICENSE).
Keep third-party license and attribution notices when reusing code.
