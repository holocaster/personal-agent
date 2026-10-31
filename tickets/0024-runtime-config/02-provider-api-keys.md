# 02: Set Provider API keys and complete missing-key Provider changes

**What to build:** Complete `/config` with an option to set an API key for any
of the four supported Providers. Hide secret entry and keep key values out of
terminal output and logs. When a tier is switched to a Provider without an
effective key, prompt for one and save the key and Provider selection together;
cancellation must leave the existing active and saved configuration unchanged.

**Blocked by:** 01 — Edit tier routing configuration in the interactive REPL.

**Spec:** `docs/specs/0024-runtime-config.md` (R3, R4, R5, R6, R7, R8);
**ADRs:** none.

- [x] Add a guided menu action to set a key for each of `openrouter`,
      `anthropic`, `openai`, and `gemini`, including a Provider not currently
      selected by a tier. Show only whether a key is available and its source,
      never its value.
- [x] Read API keys through hidden input. After entry, never echo, display,
      interpolate into a success/error message, or write the value to
      application logs or the Call Log; do not retain it in REPL input history.
- [x] A standalone key update accepts only a non-empty value. Cancellation or
      empty input leaves the active key and saved `.env` unchanged.
- [x] When a tier's selected Provider has no effective API key, prompt for it
      before applying the Provider change. On cancellation or an empty entry,
      leave the Provider selection, active `TierConfig`, and saved home `.env`
      unchanged. On acceptance, validate and persist the key and Provider
      selection together, then activate the new Runtime Configuration for
      subsequent routed tasks and Compression calls.
- [x] A standalone API-key update changes the in-memory key used by subsequent
      tasks in the current Run and writes only the matching existing Provider
      API-key variable to the home `.env`; other tiers and entries remain
      unchanged. A save failure does not activate the new key.
- [x] Preserve the existing source precedence on a later Run. When an exported
      or current-directory key overrides the saved home key, the menu names
      the variable and winning source but never reveals either key value.
- [x] Test the actual secret prompt behavior and `/config` interactions with a
      scripted input adapter. Verify a key can be saved and used, an absent-key
      Provider change prompts first, cancellation/empty input has no side
      effects, the key is absent from REPL input history, save failure does not
      activate, and terminal output, application logs, and Call Log entries
      contain no entered key value.
- [x] Run the full offline test suite after the end-to-end key flow is complete.
