# 0008 - Agent UX: System Prompt, Tool Registry, Input Box

## Goal

Make the agent use Tools reliably and make the REPL feel like a modern
agent CLI. Evidence: in Session `20260922T202452Z-u4j5dy` the model
invented a date ("24 de novembro de 2025") in the same message where it
called `current_time`, because the System Prompt is only
"You are a helpful assistant." and carries no date and no Tool guidance.

## Scope

1. **System Prompt**, rebuilt for every Provider exchange:
   - current local date, time and UTC offset (e.g. `2026-09-22 17:30 -03:00`);
   - rule: use Tools for arithmetic and time, never guess;
   - rule: answer in the user's language.
   - `current_time` stays as a Tool.
2. **Tool Registry**: one declaration per Tool (name, description,
   JSON Schema, function), replacing today's three parallel structures
   (`TOOL_DEFS`, `_SCHEMAS`, `_TOOL_FUNCTIONS`). Argument validation uses
   the `jsonschema` library against that schema, so non-string, optional
   and nested arguments work. `jsonschema` is already in `uv.lock` via
   `litellm`; declare it explicitly in `pyproject.toml`. Existing
   per-call error behavior (unknown Tool, invalid arguments, execution
   error returned to the model as an error result) is preserved.
3. **Live Tool display**: while a routed task runs, each executed Tool
   call prints one line: `tool> calculator(expression="2+2") -> 4`,
   yellow on success, red on error, truncated to 120 characters. The
   assistant's intermediate text sent alongside Tool calls is not
   printed (it stays in `/history` and the Call Log).
4. **Input Box + Status Footer** (interactive terminal only), built on
   `prompt_toolkit` in inline mode (no alternate screen; finished output
   goes to the terminal's scrollback, like Codex CLI):
   ```
   ────────────────────────────────────────
   > type here
   ────────────────────────────────────────
    easy · minimax/minimax-m3 · $0.0009 / $1.00 · /help
   ```
   - Footer: last answer's tier and model, Session spend, Budget
     Guardrail limit when configured, `/help` hint.
   - Input history with arrow up, in memory only.
   - Tab/autocomplete for REPL Commands starting with `/`.
   - Enter submits; Alt+Enter inserts a newline.
   - While a request runs, the Input Box is replaced by the spinner; no
     type-ahead. Ctrl+C still interrupts the request.

## Out of scope

- New Tools (file, web, memory, shell) - separate features.
- Persisted input history or Conversation resume.
- Full-screen TUI, full `╭─╮` border, type-ahead during a request.
- Streaming answers.
- Parallel Tool execution, Tool result size limits.

## Settled decisions (from discovery)

- One feature, independent tickets for items 1-4.
- `prompt_toolkit` over Textual (full screen, loses scrollback) and over
  hand-rolled ANSI (fragile on resize/paste/UTF-8). New runtime
  dependency, accepted by the user.
- Piped / non-TTY input keeps today's plain line mode unchanged
  (existing tests rely on it).
- `jsonschema` over a hand-rolled validator.
- No emoji in output (user rule): Tool lines use the `tool>` prefix,
  matching `llm>`.

## Notes for the planner

- Whether the `prompt_toolkit` choice earns an ADR is the planner's call
  (the project so far prefers hand-rolled code - see ADR-0002).
- The Status Footer needs the Session spend; today it exists twice in
  memory (`BudgetGuardrail` and `call_log._total_cost`). Pick one source,
  do not add a third.
- The Tool display must not break the existing non-TTY tests; decide
  whether piped mode prints Tool lines (plain, uncolored) or not.

## Added after review (routed as new ticket 06)

Ticket 03's review found model-controlled text reaches the terminal
unescaped. Proven: `format_tool_line` passes ESC/BEL/CR/LF raw, so
`\x1b[2K\rllm> forged answer` in a model's raw arguments erases the line
and shows a forged answer. Same root cause in `llm>` answer printing,
`/history` and `Error:` lines. User decided: fix it in this feature.
Scope: one sanitizer in `tty.py` that removes or escapes C0/C1 control
characters and DEL (keeping `\n` and `\t` in multi-line text; escaping
`\n` in the one-line `tool>` line), applied at every REPL write of
model- or Provider-controlled text. The Call Log is already safe
(`json.dumps`).

## Known issues (accepted, out of scope)

- `litellm` downloads its model cost map from the network at import. The
  remote map changed on 2026-09-22 and two pricing tests in
  `tests/test_provider.py` now fail unless `LITELLM_LOCAL_MODEL_COST_MAP=True`
  (proven: same failure at 612dbe1, passes with the local map). Estimated
  Cost at runtime can also silently become `None`. Fix as its own change.

## Open questions

None.
