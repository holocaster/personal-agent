# 0024 - Runtime Configuration

Brief: `docs/briefs/0024-runtime-config.md`. The brief settles product scope and
configuration precedence. This feature uses the existing Runtime Configuration,
Tier Config, Provider, Run, REPL Command, and Terminal vocabulary from
`docs/CONTEXT.md`. No existing ADR requires amendment; no new ADR is needed.

## Problem Statement

The user's provider and model choices, and provider API keys, are currently
selected before the Run starts. Changing them requires editing environment
configuration and restarting the Personal Agent, interrupting an otherwise
active REPL session.

## Solution

Add an interactive-only `/config` REPL Command that lets the user inspect and
change the model and Provider for each Complexity Tier and set API keys for the
four supported Providers. Each accepted change is persisted in
`~/.personal_agent/.env`, takes effect on the next routed task in the current
Run, and does not alter a routed task already in progress. API key input is
hidden; API key values are never displayed or logged. Startup validation and the
existing environment precedence remain unchanged.

## User Stories

1. As a user, I want `/config` to show each Complexity Tier's current model and
   Provider, so that I can inspect the routing configuration without editing
   files.
2. As a user, I want to change the `easy` tier's model while the REPL is
   running, so that later tasks can use a different model without restarting.
3. As a user, I want to change the `medium` tier's model while the REPL is
   running, so that I can tune its routing independently.
4. As a user, I want to change the `complex` tier's model while the REPL is
   running, so that I can tune its routing independently.
5. As a user, I want to choose a supported Provider independently for each
   tier, so that tiers can use different APIs.
6. As a user, I want an accepted change to affect the next routed task, so that
   I can immediately try the new configuration.
7. As a user, I want a task that has already started to keep its original
   Runtime Configuration, so that a change cannot alter an in-flight Provider
   exchange.
8. As a user, I want accepted changes to remain available on a later Run, so
   that I do not have to re-enter them each time.
9. As a user, I want to set an API key for any of the four supported Providers,
   so that I can configure a Provider before selecting it for a tier.
10. As a user, I want API key entry to be hidden and the key never shown after
    entry, so that people looking at the terminal cannot read it.
11. As a user, I want to be prompted for a missing API key before switching a
    tier to that Provider, so that the next routed task will not fail for a
    missing credential.
12. As a user, I want cancelling a missing-key prompt to leave the old tier
    Provider and all saved configuration unchanged, so that an incomplete
    change is not partially applied.
13. As a user, I want unrelated entries in my home `.env` file preserved, so
    that `/config` does not overwrite settings it does not own.
14. As a user, I want the home `.env` file to be private after a configuration
    save, so that its API keys are not readable by other local users.
15. As a user, I want to know when an exported environment value or the
    current-directory `.env` overrides a value saved in the home `.env`, so
    that I understand which setting a later Run will use.
16. As a user, I want a deliberate `/config` change to control later tasks in
    the current Run even when the saved home value is overridden, so that I can
    try the change immediately.
17. As a user, I want shell exports, the current-directory `.env`, and the
    home `.env` to retain their current precedence on a later Run, so that
    existing launch configurations continue to work.
18. As a user piping input to the REPL, I want `/config` to explain that the
    guided menu requires an interactive terminal, so that I know why the
    command is unavailable without the REPL interpreting arguments as a
    scripted configuration interface.
19. As a user, I want `/help` to list `/config`, so that I can discover the
    command from the REPL.

## Requirements

- **R1 Interactive command.** `/config` with no arguments opens a guided menu
  only in the existing interactive REPL mode. In piped/non-interactive mode it
  reports that an interactive terminal is required, does not change active or
  saved configuration, and continues the REPL. No command-argument or scripted
  form is added. `/help` lists the command. Arguments to `/config` are rejected
  as unsupported.
- **R2 Inspection and tier edits.** The menu shows the current model and
  Provider for `easy`, `medium`, and `complex`, and allows each tier's model
  and Provider to be edited independently. A Provider choice must be one of
  `openrouter`, `anthropic`, `openai`, or `gemini`; a model cannot be empty.
  Changing one setting leaves every other tier setting unchanged.
- **R3 Provider keys.** The menu allows setting an API key for each supported
  Provider, including Providers not currently selected by a tier. Key entry is
  hidden and the entered value is not retained in REPL input history. A
  standalone key update requires a non-empty value; cancellation or an empty
  response leaves the existing key unchanged. The key value is never displayed
  in menu output or success/error messages and is never written to the Call Log
  or application logs. The menu may indicate whether a key is available, but
  must not reveal its value.
- **R4 Missing-key gate.** Before applying a tier's Provider change, the menu
  checks whether that Provider has an effective API key. If none is available,
  it prompts for one using hidden input. Cancellation or an empty response
  leaves that Provider selection, the active Tier Config, and the saved home
  `.env` unchanged. A supplied key and Provider change are saved and activated
  together; there is no partially applied Provider change.
- **R5 Persistence.** Accepted tier model/provider edits and API-key changes
  are written to `~/.personal_agent/.env`, creating the parent directory or
  file when needed. The update changes only the feature's tier model, tier
  Provider, and four Provider API-key entries; all unrelated entries in that
  file are retained. The resulting `.env` file has owner-only access (mode
  `0600` on POSIX). A setting is not reported as saved or activated if its
  persistence operation fails.
- **R6 Runtime application.** A successful change updates the Runtime
  Configuration used for subsequent routed tasks and Compression calls in the
  current Run. A routed task uses the Tier Config snapshot it received when it
  started and is not changed by a later configuration update. The selected
  change is activated only after its persistence succeeds. No other runtime
  setting is changed.
- **R7 Precedence and override visibility.** Startup continues to resolve
  configuration in this order: exported environment, current-directory `.env`,
  then `~/.personal_agent/.env`; existing startup validation is retained. The
  menu identifies a managed variable whose saved home value is overridden by
  an exported or current-directory value and names the winning source. This
  notice may name the variable and source but must not reveal an API key. A
  deliberate menu change takes effect in the current Run; on a later Run,
  existing higher-precedence sources still override the saved home value.
- **R8 Scope boundary.** `/config` changes only per-tier model/provider values
  and the four Provider API keys. It does not change other `PA_*` settings,
  `NO_COLOR`, or other environment variables; it does not add a first-run
  wizard, relax startup validation, add keyring support, or add non-interactive
  configuration syntax.

## Implementation Decisions

- The Terminal REPL owns `/config` dispatch and presentation, using the
  existing interactive input path. The command is added to command completion
  and `/help`; piped mode receives an explanatory message rather than a
  different interface.
- The active Runtime Configuration is represented by a new valid `TierConfig`
  after each accepted change, rather than mutating a configuration snapshot
  already passed to a routed task. The existing routing API remains the seam
  used by the REPL.
- The configuration persistence path owns reads and updates to the existing
  home `.env`. It edits only the supported Tier Config and Provider-key
  variables, retains unrelated content, and ensures owner-only file
  permissions. Startup loading and `tier_config.validate()` remain in force.
- Override reporting uses configuration-source provenance for the managed
  variables. API-key presence/source may be shown; API-key contents may not.
- API keys are entered through a hidden prompt, not the normal echoed REPL
  input or retained in REPL input history. The active config and saved `.env`
  are updated only after the complete candidate change has passed validation
  and persistence.
- No new configuration format, environment-variable names, Provider, CLI
  option, or dependency is introduced.

## Testing Decisions

- Good tests assert externally observable behavior: menu/REPL output, the
  Provider and model used by the next routed task, unchanged configuration
  after cancellation or save failure, `.env` contents and permissions, startup
  precedence, and absence of secrets from output and logs. Tests should not
  assert private menu helpers or internal representation details.
- **Seam 1: `run_repl` with the existing fake Provider transport** and a
  scripted interactive input adapter. Exercise command discovery, edits to
  each tier, next-task behavior, task snapshot behavior, missing-key prompt
  cancellation, and non-interactive refusal. Prior art:
  `tests/test_repl.py`, `tests/test_input_box.py`, and
  `tests/fakes.py`.
- **Seam 2: the configuration file boundary** with a temporary home and
  current-directory `.env`. Verify that managed keys round-trip, unrelated
  lines/values remain, a failed save does not activate a candidate, file mode
  is owner-only on POSIX, and exported/current-directory/home precedence is
  unchanged. Prior art: `tests/test_dotenv.py` and
  `tests/test_tier_config.py`.
- **Secret handling** is checked at the interactive seam: the entered value is
  persisted and used where appropriate, while captured terminal output,
  application logs, and Call Log entries contain no key value. The actual
  prompt must suppress typed characters and not expose the value through REPL
  input history. Empty/cancelled standalone key input leaves the prior value
  unchanged.
- The full offline test suite must pass.

## Out of Scope

As in the brief: changing non-routing environment variables; a first-run setup
wizard; starting without valid required configuration; OS keyring integration;
non-interactive or scripted configuration syntax; changing configuration in
the middle of a routed task; adding another configuration format; changing
startup source precedence; and changing Providers or their authentication
contracts.

## Further Notes

- The four Provider API-key variable names and the per-tier model/provider
  names are the existing names documented in `docs/ENV_VARS.md` and consumed
  by `tier_config`; this feature does not rename them.
- The brief has no unresolved product questions. The ticket sequence below
  delivers tier editing first, then hidden API-key management and the missing
  key flow; each ticket is user-observable and end-to-end.
