# 0024 — Runtime Configuration

## Goal

Let users inspect and change the model and provider for each tier, and set API keys for providers, with `/config` while the REPL is running, without restarting the app.

## Scope

- `/config` opens a guided configuration menu in an interactive terminal.
- Users can change the model and provider for each tier and set the API key for a provider.
- Changes take effect on the next routed task. An in-progress task continues with the configuration it started with.
- Persist changes to `~/.personal_agent/.env`; keep unrelated entries and make the file private. Never display or log API key values.
- If a selected provider has no API key available, prompt for it before applying the change. Cancelling leaves the existing configuration unchanged.
- Keep the existing startup configuration validation and precedence: exported environment, current-directory `.env`, then `~/.personal_agent/.env`. Show when a higher-precedence source overrides a saved value.
- In piped/non-interactive mode, `/config` reports that the guided menu requires an interactive terminal. No direct command-argument form is added.

## Out of scope

- Changing other `PA_*` settings, `NO_COLOR`, or any non-routing environment variable.
- A first-run setup wizard or allowing startup with missing required configuration.
- OS keyring integration or non-interactive/scripted configuration syntax.
- Changing configuration in the middle of a routed task.

## Settled decisions

1. Configuration covers per-tier models and providers plus API keys for the four supported Providers.
2. Persist configuration in the existing home `.env` file; do not introduce a second configuration format.
3. Preserve existing environment precedence. A deliberate `/config` change controls later tasks in the current Run, while shell exports or the current-directory `.env` can override the saved home value on a later Run.
4. Prompt for a missing API key before applying a Provider change; cancellation does not partially change the active or saved configuration.
5. Secret entry is hidden, and secret values are never printed or logged.
6. The menu is interactive-only. Startup still requires a valid configuration.

## Open questions

None for product scope. The planner owns implementation decomposition and detailed acceptance criteria.
