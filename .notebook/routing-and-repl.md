# Routing and REPL

Entry: `src/personal_agent/__main__.py:main()` loads settings, validates the route
and enters `terminal/repl.py:run_repl()`. API-key routes use Models.dev;
`chatgpt` uses `routing/runtime_config.py:admit_chatgpt()` and the connected
account's model choices. An unready route keeps setup available but blocks tasks.

`RuntimeConfig.snapshot()` fixes Provider/model, account binding, ChatGPT reasoning
and context limits for each task or explicit Retry. Tool follow-ups, transient
retries and automatic Compression reuse it; manual `/compress` snapshots current
settings. Agent Mode can still change at later exchange/Tool boundaries.
`routing/config_store.py:save_settings()` persists accepted configuration atomically.

`call_log.py` owns Session identity and log v3 replay, including submission ordinals,
Conversation, Summary, Todo and pending work. Resume keeps the Id and uses current
configuration. `/fork` creates a self-contained child log and switches the REPL;
both Sessions share files. See [decisions](../docs/CONTEXT.md#decisions) and
[session usage](../docs/USER_GUIDE.md#terminal-and-sessions).

`providers/registry.py` registers five Providers. OpenRouter diagnostics are
optional asynchronous generation-metadata lookups, recorded separately by Attempt
timestamp; the terminal shows the selected Provider/model rather than the upstream host.

Input: `terminal/input_box.py:InputBox` owns interactive multiline editing; non-TTY
input is one task per line. Enter submits, Alt+Enter inserts a newline, Tab completes
commands, and Shift+Tab cycles modes. Ctrl+C interrupts work or exits at an idle prompt.

Tests: `tests/conftest.py` supplies synthetic API catalogs; `test_catalog_selection.py`
and `test_direct_route.py` cover admission and routing. ChatGPT account selection,
usage and reasoning have dedicated `test_chatgpt_*.py` suites. Question labels accept
strings or text-only objects; `test_question_tool.py` covers unchanged arguments,
Other/custom text and follow-up/Resume behavior.

Updated: 2026-10-27
