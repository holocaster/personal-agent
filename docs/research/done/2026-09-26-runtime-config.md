# Runtime configuration research

**Status (2026-09-29):** feature `0024-runtime-config` is delivered on `main`; both tickets were approved. The `/config` command is available in the current REPL.

**Update (2026-10-04):** feature 0037 also added persistent context-budget and exact Provider/model capacity settings to `/config`; see [ENV_VARS](../../ENV_VARS.md#context-capacity-overrides). `/model` now selects a durable Session tier under features 0039/0041, not a Run-local pin.

**Evidence basis:** repository source and documentation at checkpoint `91dd777` (`main`) inspected for this feature. The discovery notes below record that checkpoint, not the current checkout.

## Before this feature

- `__main__.py` loads dotenv files, builds `TierConfig`, validates required models and provider keys, then starts the REPL. Invalid startup configuration exits before a REPL command can run.
- The dotenv loader uses `setdefault`, preserving precedence: exported environment, `.env` in the process start directory, then `~/.personal_agent/.env`.
- `/models` displays the loaded tier mapping. `/model` pins a tier for the current Run; neither command edits model/provider settings.
- The REPL receives the loaded `TierConfig`; provider adapters read API keys from the process environment when calls are made. There is no supported configuration reload command.
- `docs/ENV_VARS.md` lists the three tier model variables, three provider variables, four provider API key variables, and other process settings.

## Discovery outcome

Feature `0024-runtime-config` adds an interactive `/config` menu for per-tier model/provider settings and provider keys. Changes are intended for the next routed task and are persisted in the existing home `.env`; the feature preserves current environment precedence and startup validation. Non-routing process settings, first-run setup, keyring support, and piped configuration are out of scope.

Planning checkpoint: the spec and two dependent tickets were committed in `0c5a6f0`. Ticket 01 implementation is committed in `452c7a5` and approved. Ticket 02 implementation is committed in `b95ee91`, with redaction corrections in `1ff14ae` and `96473da`; the final review approved the full range. The live command edits per-tier model/provider and Provider keys, saves to the home `.env`, and preserves startup precedence.
