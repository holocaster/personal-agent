# 01: Edit tier routing configuration in the interactive REPL

**What to build:** Make `/config` a guided interactive REPL Command for
inspecting and changing the model and Provider of each Complexity Tier. Persist
accepted values in the existing home `.env`, keep the active Runtime
Configuration valid, and use an accepted change for subsequent routed tasks in
the current Run. Preserve startup validation and source precedence, and show
when a higher-precedence source overrides a saved tier value.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0024-runtime-config.md` (R1, R2, R5, R6, R7, R8);
**ADRs:** none.

- [x] Add `/config` to REPL command handling, completion, and `/help`. With no
      arguments, it opens a guided menu only in the existing interactive mode;
      reject extra arguments. In piped mode, explain that an interactive
      terminal is required, leave active/saved configuration unchanged, and
      continue the REPL.
- [x] Show the current model and Provider for `easy`, `medium`, and `complex`;
      allow editing each tier's model and Provider independently. Accept only a
      non-empty model and one of `openrouter`, `anthropic`, `openai`, or
      `gemini`; preserve every unselected setting.
- [x] Persist tier edits only to their existing `TIER_<TIER>_MODEL` and
      `TIER_<TIER>_PROVIDER` entries in `~/.personal_agent/.env`. Create the
      parent directory/file when needed, preserve unrelated entries, and
      ensure the resulting file is owner-only (mode `0600` on POSIX).
- [x] Until ticket 02 adds hidden API-key entry, refuse a Provider selection
      when that Provider has no effective API key. Explain that the setting
      was not changed; do not alter the tier, active config, or home `.env`.
- [x] Use a new valid active `TierConfig` after a successful save so later
      routed tasks and Compression calls use it. A task already in progress
      retains the config snapshot with which it started. Do not apply or report
      a change as successful when validation or persistence fails.
- [x] Keep startup loading/validation and precedence unchanged: exported
      environment, current-directory `.env`, then home `.env`. Indicate when a
      tier model/provider value saved in the home file is overridden by a
      higher-precedence source, naming the variable and source without
      exposing any Provider key.
- [x] Test the command through `run_repl` and the fake Provider transport:
      inspect and edit all tiers, verify only the selected setting changes and
      the next routed task uses the change, verify extra arguments and piped
      input do not mutate configuration, and verify missing-key refusal.
- [x] Test the home `.env` boundary with temporary files: unrelated entries
      survive, tier settings round-trip, failed persistence does not activate
      the candidate, owner-only permissions are set on POSIX, and startup
      precedence and override reporting are correct.
