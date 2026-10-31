# 0008 - Agent UX: System Prompt, Tool Registry, Input Box

Brief: `docs/briefs/0008-agent-ux.md`
Vocabulary: `docs/CONTEXT.md`
Constraints: ADR-0001 (technical-failure Escalation), ADR-0002 (hand-rolled Provider Contract), ADR-0003 (one Call Log file per Session), ADR-0004 (prompt_toolkit for the Input Box, added by this feature).

## Problem Statement

The model does not use its Tools reliably. The System Prompt is the single sentence "You are a helpful assistant.", with no date and no guidance on Tools, so in Session `20260922T202452Z-u4j5dy` the model invented a date in the same message where it called `current_time`. Nothing tells it that arithmetic and time must come from Tools, or that it should answer in the user's language.

Adding Tools is also harder than it should be. A Tool is declared in three parallel structures (the advertised definitions, a hand-written type map, and a name-to-function map), and the hand-written validator only understands required string arguments. A Tool with a number, an optional or a nested argument cannot be declared correctly today.

The REPL also hides what the agent is doing and looks dated. While a routed task runs, the user sees a spinner and then an answer, with no sign of which Tools ran or what they returned. Input is a bare `user> ` line: no history on arrow up, no completion for REPL Commands, no way to type a newline, and no view of which model answered or what the Session has spent.

Model- and Provider-controlled text reaches the terminal unescaped (found in ticket 03's review, added to this feature afterwards; brief, "Added after review"). A model can put `\x1b[2K\rllm> forged answer` in a Tool call's raw arguments: the rejected call's `tool>` line then erases itself and shows a forged answer. The `llm>` answer, `/history` and `Error:` lines have the same root cause. The Call Log is already safe because it is written with `json.dumps`.

## Solution

The System Prompt is rebuilt for every Provider exchange and carries the current local date, time and UTC offset, the rule to use Tools for arithmetic and time instead of guessing, and the rule to answer in the user's language.

Tools move into a Tool Registry: one declaration per Tool with its name, description, JSON Schema and function. The schema is advertised to Providers and is also used, through the `jsonschema` library, to validate every call a model makes, so any argument shape JSON Schema can describe works. A rejected call still reaches the model as an error result, as today.

Each executed Tool call prints one line as it happens, e.g. `tool> calculator(expression="2+2") -> 4`, yellow on success and red on error on a color terminal, plain in piped mode.

In an interactive terminal the REPL reads input through an Input Box built on `prompt_toolkit` in inline mode, framed by horizontal rules, with a Status Footer showing the last answer's tier and model, the Session spend, the Budget Guardrail limit when set, and a `/help` hint. Arrow up recalls earlier inputs from this Session, Tab completes REPL Commands, Enter submits and Alt+Enter inserts a newline. While a request runs, the spinner replaces the Input Box. Piped and non-TTY input keep today's plain line mode.

Every REPL write of model- or Provider-controlled text goes through one sanitizer, so control characters are shown as visible escapes instead of being executed by the terminal. Multi-line text keeps its newlines and tabs; the one-line `tool>` line shows a newline as `\n`.

## User Stories

1. As a terminal user, I want the model to know today's date, so that it does not invent one.
2. As a terminal user, I want the model to know the current local time and my UTC offset, so that "what time is it" and "tomorrow" are answered against my clock.
3. As a terminal user, I want the date in the System Prompt to be current on every exchange, so that a Session left open past midnight does not use a stale date.
4. As a terminal user, I want the model told to use the calculator instead of doing arithmetic in its head, so that numeric answers are correct.
5. As a terminal user, I want the model told to use Tools for time instead of guessing, so that the time it reports matches the clock.
6. As a terminal user writing in Portuguese, I want answers in my language, so that I do not have to ask for a translation every time.
7. As a terminal user, I want `current_time` to stay available as a Tool, so that the model can get an exact timestamp when it needs one.
8. As a developer, I want each Tool declared in one place, so that adding a Tool means writing one declaration, not updating three structures that can drift apart.
9. As a developer, I want a Tool's JSON Schema to be the only definition of its valid arguments, so that what the Provider is told and what is accepted can never disagree.
10. As a developer, I want Tools with number, boolean, optional and nested arguments to validate correctly, so that future Tools are not limited to required strings.
11. As a developer, I want validation done by a maintained JSON Schema library, so that I do not maintain a partial validator by hand.
12. As a terminal user, I want a model's call to an unknown Tool returned to the model as an error, so that the model can recover instead of the request crashing.
13. As a terminal user, I want a call with invalid arguments returned to the model as an error that says what was wrong, so that the model can fix its call.
14. As a terminal user, I want a Tool that fails while running returned to the model as an error, so that the request continues.
15. As a terminal user, I want to see each Tool call as it runs, so that I know what the agent is doing while I wait.
16. As a terminal user, I want each Tool line to show the Tool name, its arguments and its result, so that I can check the agent's work.
17. As a terminal user, I want successful Tool calls in yellow and failed ones in red, so that failures stand out.
18. As a terminal user, I want long Tool lines cut to 120 characters, so that one large result does not flood my terminal.
19. As a terminal user, I want the model's intermediate text sent alongside Tool calls kept out of the live output, so that I only see the final answer as the answer.
20. As a terminal user, I want that intermediate text still in `/history` and the Call Log, so that nothing is lost.
21. As a terminal user, I want Tool lines and the spinner not to garble each other, so that the output stays readable.
22. As a script author piping input, I want Tool lines printed plainly with no color codes, so that my captured output is clean text that still shows what ran.
23. As a terminal user, I want my input framed by horizontal rules, so that the place I type is clearly separated from the output above.
24. As a terminal user, I want finished output to stay in my terminal's scrollback, so that I can scroll back and copy it as with any command.
25. As a terminal user, I want a footer showing which tier and model answered last, so that I know what I am paying for.
26. As a terminal user, I want the footer to show what this Session has spent, so that I can watch cost while I work.
27. As a terminal user with a Budget Guardrail set, I want the footer to show the limit next to the spend, so that I can see how close I am.
28. As a terminal user, I want a `/help` hint in the footer, so that I can find the REPL Commands.
29. As a terminal user, I want arrow up to recall earlier inputs from this Session, so that I can repeat or edit a task.
30. As a terminal user, I want input history kept in memory only, so that nothing I typed is written to disk.
31. As a terminal user, I want Tab to complete REPL Commands starting with `/`, so that I do not have to remember or type them in full.
32. As a terminal user, I want Enter to submit, so that the common case is one key.
33. As a terminal user, I want Alt+Enter to insert a newline, so that I can write a multi-line task.
34. As a terminal user, I want the spinner in place of the Input Box while a request runs, so that it is clear the agent is busy.
35. As a terminal user, I want Ctrl+C during a request to interrupt it and bring the Input Box back, so that a slow request never traps me.
36. As a terminal user, I want Ctrl+C or Ctrl+D at an empty Input Box to end the Session, as it does today, so that leaving works the way it always has.
37. As a script author, I want piped or non-TTY input to behave exactly as today, so that my scripts and the test suite keep working.
38. As a developer, I want the Session spend to come from one existing counter, so that the footer cannot disagree with the Call Log's `total_cost`.
39. As a reader of the README, I want the Input Box, footer, key bindings and Tool lines documented briefly, so that I know how to use them.
40. As a terminal user, I want control characters in a model's Tool name, arguments or result shown as visible escapes, so that a model cannot erase lines or forge output in my terminal.
41. As a terminal user, I want control characters in a model's answer shown as visible escapes, so that an answer cannot rewrite what is already on screen or change my terminal's state.
42. As a terminal user, I want `/history` and `Error:` lines sanitized the same way, so that replayed or Provider-supplied text is as safe as a live answer.
43. As a terminal user, I want multi-line answers to keep their line breaks and tabs, so that sanitizing does not wreck normal formatting.
44. As a terminal user, I want each `tool>` line to stay one line and within 120 characters even after escaping, so that the display stays readable.
45. As a terminal user, I want the REPL's own colors and spinner to keep working, so that sanitizing only touches untrusted text.

## Implementation Decisions

### System Prompt

- **R01 - Content.** The System Prompt keeps a short assistant line and adds, as separate lines: the current local date, time and UTC offset in the form `YYYY-MM-DD HH:MM +HH:MM` (e.g. `2026-09-22 17:30 -03:00`); a rule that arithmetic must use the calculator Tool and the current time must come from Tools or the date line, never guessed; and a rule to answer in the language the user wrote in. Exact wording is the implementer's, but those three elements must be present and the date line must use exactly that format. `current_time` remains a Tool, unchanged in behavior (brief, scope 1).
- **R02 - Rebuilt per exchange.** The Router builds the System Prompt from the local clock on every Provider exchange (every Attempt, including Tool follow-ups), replacing the module constant. The local clock is read through one module-level swappable function in the Router, the same seam style as the Tool module's clock, so tests can fix the time. Local time means the process's local timezone (Python's `datetime.now().astimezone()`); Python 3.12's `strftime` supports `%:z` for the `+HH:MM` form. No new configuration variable.

### Tool Registry

- **R03 - One declaration per Tool.** The Tool module holds a single registry: one declaration per Tool carrying `name`, `description`, `parameters` (a JSON Schema object) and `function`. The three parallel structures (advertised definitions, type map, function map) are removed. The Provider-facing `ToolDef` tuple the Router passes to Providers is derived from the registry, so the Provider Contract and all four Providers are unchanged (ADR-0002). The calculator and `current_time` keep their current names, descriptions, schemas and results.
- **R04 - Validation with `jsonschema`.** Each call's arguments are validated against the declared schema with the `jsonschema` library (`Draft202012Validator`; `iter_errors` or `validate`, verified against the library's current docs). Every registry schema must itself pass `Draft202012Validator.check_schema`. `jsonschema` is declared explicitly in `pyproject.toml` (already locked at 4.26.0 through `litellm`). Per-call error behavior is preserved: an unknown Tool name, arguments that are not a valid JSON object, a schema violation, and a `ToolExecutionError` raised while running each produce an error Tool result returned to the model, and the batch continues. A schema violation's error text starts with `invalid arguments:` followed by the library's message for the first error found; the exact wording of today's hand-written messages is not preserved. Batch-level correlation checks (missing or duplicate ids) are unchanged.

### Live Tool display

- **R05 - Line format.** One line per Tool result: `tool> <name>(<args>) -> <result>`. `<args>` is `key=value` pairs joined by `, `, each value JSON-encoded (`expression="2+2"`, `n=3`), empty for no arguments, and `...` when the call was rejected before execution and has no parsed arguments. On success, `<result>` is the value itself when the Tool returned an object with exactly one key (strings unquoted, e.g. `-> 4`, `-> 2026-09-22T20:30:00+00:00`), otherwise the compact JSON of the whole object. On error, `<result>` is `error: <message>`. A line longer than 120 characters is cut to 117 characters plus `...`. Formatting is a pure function with no terminal access.
- **R06 - Live, in order, spinner-safe.** `route` gains one optional keyword parameter, a callback invoked with each Tool result right after its batch executes and before the follow-up exchange, in execution order. Default is no callback, so direct callers are unaffected. The REPL passes a callback that prints the formatted line: yellow on success, red on error, when color is enabled (`tty.color_enabled`). When the spinner is running, the line is written through the spinner so the two never interleave: the spinner clears its current frame, writes the line, and resumes on the next frame, guarded by one lock shared with the frame loop. The model's intermediate text sent alongside Tool calls is not printed; it stays in `/history` and the Call Log, which are unchanged.
- **R07 - Piped mode prints Tool lines.** In piped / non-TTY mode the same lines are printed without color, before the answer. Decided because the lines are useful in captured output and existing piped tests assert substrings, not whole output.

### Input Box and Status Footer

- **R08 - Activation.** The Input Box is used only when both standard input and standard output are interactive terminals; `__main__` decides this and passes an Input Box into `run_repl` through a new optional parameter. With no Input Box, `run_repl` behaves exactly as today, including printing `user> ` when its input stream is a TTY. Piped / non-TTY mode is unchanged (brief, settled decisions; `docs/CONTEXT.md`, Interactive vs piped REPL).
- **R09 - Input Box.** A new small input module owns the only `prompt_toolkit` usage: one `PromptSession` per Session in inline mode (not full screen), exposing one read operation that returns the submitted text and lets `KeyboardInterrupt` (Ctrl+C) and `EOFError` (Ctrl+D) propagate, which is `prompt_toolkit`'s documented default. It accepts optional `input`/`output` objects so tests can drive it with `create_pipe_input()` and `DummyOutput()`. Layout, top to bottom: a horizontal rule of `─` across the terminal width, the input line prefixed `> `, a second rule, and the Status Footer. The top rule and `> ` are the prompt message; the second rule and the footer are the bottom toolbar, supplied as a callable so it is re-rendered every time the prompt draws. Tune `reserve_space_for_menu` so the lower rule sits directly under the input; confirm the final look manually.
- **R10 - Input behaviors.** History: the session's in-memory history (`InMemoryHistory`, the `PromptSession` default); arrow up recalls earlier inputs; nothing is written to disk. Completion: Tab completes REPL Commands from the REPL's existing command list, offered only when the input starts with `/`. Keys: Enter submits; Alt+Enter (Escape then Enter) inserts a newline; a submitted multi-line task is sent as one task. Implement the keys with custom `KeyBindings` that take precedence over the defaults. Submitted text is handled exactly like a plain-mode line (stripped, empty ignored, `exit`/`quit`, REPL Commands, routed tasks).
- **R11 - During a request.** After submit, `prompt_toolkit` is not running: the REPL routes the task with the existing spinner in place of the Input Box, prints Tool lines and the answer to stdout so they land in scrollback, then shows the Input Box again. No type-ahead is supported; keys typed during a request are not specially handled. Ctrl+C during a request keeps today's behavior (print `Interrupted.`, return to input). Ctrl+C or Ctrl+D at the Input Box ends the Session with the Call Log reasons `interrupt` and `eof` respectively (spec 0007, R08).
- **R12 - Status Footer.** One line: `<tier> · <model> · $<spent> / $<limit> · /help`, e.g. ` easy · minimax/minimax-m3 · $0.0009 / $1.00 · /help`. `<tier>` and `<model>` are those of the last successful answer in this Session and the segment is omitted before the first one. `<spent>` has 4 decimals; ` / $<limit>` (2 decimals) appears only when a Budget Guardrail is configured. Rendering is a pure function of those values. The spend source is the Call Log's existing running total of this Session's Attempt costs, exposed through one public read function on `call_log`; it is the same number `session_end` reports as `total_cost` and it exists whether or not a Budget Guardrail is set. The Budget Guardrail keeps its own counter for its Escalation decision, unchanged (`docs/CONTEXT.md`, Budget Guardrail window). No third counter is added.

### Terminal output safety

- **R15 - One sanitizer for untrusted text.** The terminal module (`tty`) gains one pure sanitizer that replaces every C0 control character (U+0000-U+001F), DEL (U+007F) and C1 control character (U+0080-U+009F) with a visible escape of the form `\xNN` (e.g. ESC becomes `\x1b`), so nothing is silently dropped and a forgery attempt is visible. It has a multi-line mode that keeps `\n` and `\t` as they are, and a one-line mode that keeps `\t` and escapes `\n` as `\n` (all other controls, including `\r`, are escaped in both modes). It is applied to untrusted text only, before `colorize`, so the REPL's own color codes, spinner frames and line clears are untouched. Applied at every REPL write of model- or Provider-controlled text:
  - the `tool>` line (Tool name, arguments, result or error message, including a rejected call's raw arguments): sanitized in one-line mode by `format_tool_line` on the assembled line before the 120-character cut, so the displayed line is always one line of at most 120 characters;
  - the `llm>` answer: multi-line mode;
  - the `Error:` line (`result.error`, which can carry Provider-supplied text): multi-line mode;
  - `/history` rendering (message contents, Tool call names and arguments, Tool result names and contents): multi-line mode on each rendered piece.
  Text that comes only from configuration or the REPL itself (tier line, `/models`, Status Footer, help text) is not changed. The Call Log is unchanged (already `json.dumps`), and what is sent to the model and stored in the Conversation is unchanged: sanitizing is display only.

### Cross-cutting

- **R13 - Dependencies and docs.** `pyproject.toml` declares `jsonschema` (ticket for R04) and `prompt_toolkit` (ticket for R09) as runtime dependencies, and `uv.lock` is updated. ADR-0004 records the `prompt_toolkit` choice. The README briefly documents the System Prompt's date/rules, the Tool line, and the Input Box with its keys and footer, each in the ticket that adds it.
- **R14 - Unchanged behavior.** The Classifier, tier ladder, Escalation (ADR-0001), retries and backoff, each Provider's implementation, the Tool loop limits, the Budget Guardrail, the Call Log line types and fields (ADR-0003), the Context Window, `/history` rendering (apart from the R15 sanitizing), and all REPL Commands keep their current behavior. The only change to `route`'s signature is the optional callback in R06.

## Testing Decisions

A good test asserts what the user sees or what the Provider receives: the request body captured by the existing `model_router.providers.http.urlopen` fake, the text written to the REPL's output stream, the Tool result handed back to the model, or the string `prompt_toolkit` returns. Do not assert private helpers where a driven REPL or Router already proves the behavior; pure formatting functions (Tool line, footer) are tested directly because their output is the contract.

**Seams.** Existing: `install_fake_urlopen` for Provider traffic, `run_repl` with injected input/output streams, `tools.execute_batch`. Added: one swappable local-clock function in the Router (R02), mirroring `tools._clock`; the optional Input Box parameter of `run_repl`, driven in tests by a real Input Box built on `create_pipe_input()` and `DummyOutput()` (the pattern from `prompt_toolkit`'s unit-testing docs). No mock of `prompt_toolkit` itself.

**Prior art.** `tests/test_routing.py` (request bodies through the fake), `tests/test_tools.py` (execute_batch results), `tests/test_repl.py` (driven REPL, `_TTYOutputStream` for color), `tests/test_tty.py` (spinner and colorize), `tests/test_call_log.py` (total_cost).

- System Prompt: with a fixed clock, the `system` content sent to a Provider contains the formatted date line and both rules; two exchanges with different clock values carry different date lines (rebuilt, not cached), including a Tool follow-up exchange.
- Tool Registry: the Provider-facing definitions equal the registry's names, descriptions and schemas; every schema passes `check_schema`; unknown Tool, non-object arguments, missing required, unexpected key, wrong type, and a runtime `ToolExecutionError` each yield an error result and the rest of the batch still runs; a test-only Tool with a number, an optional and a nested argument validates accepted and rejected inputs correctly. Update the two existing assertions on the old hand-written error texts.
- Tool display: pure-function cases for args rendering, single-key result, multi-key result, error, no arguments, rejected call, and the 120-character cut. Driven REPL: a scripted calculator round prints the `tool>` line before the answer, uncolored in piped mode, yellow/red with `_TTYOutputStream`; intermediate assistant text is not printed. Spinner: a written line appears with the frame cleared and no frame text inside it.
- Input Box: through pipe input, Enter submits, Escape+Enter yields a multi-line string, `/he` plus Tab completes to `/help`, arrow up recalls the previous input, Ctrl+C raises `KeyboardInterrupt` and Ctrl+D raises `EOFError`. Driven `run_repl` with an Input Box: a routed task and a REPL Command work, Ctrl+D and Ctrl+C at the box end the Session with reasons `eof` and `interrupt`.
- Status Footer: pure-function cases for before the first answer, after an answer, with and without a limit; driven REPL shows the footer value tracking `call_log`'s total after an answer.
- Output sanitizing (R15): pure-function cases in `tests/test_tty.py` for ESC, BEL, CR, DEL, a C1 character, `\n`/`\t` kept in multi-line mode, `\n` escaped in one-line mode, and plain text unchanged. Driven REPL through the existing `urlopen` fake: a scripted Tool call whose `arguments_raw` is `\x1b[2K\rllm> forged` (rejected as invalid JSON), a Tool call whose name contains ESC and BEL, and a final answer containing ESC and BEL; assert the captured output contains none of the raw `\x1b`, `\x07` or `\r` characters from that text (in piped mode, where the REPL itself writes no escape codes) and does contain their visible escapes; assert with `_TTYOutputStream` that the REPL's own color codes are still present. A `format_tool_line` case proves an escaped line is still at most 120 characters. `/history` after such a turn and an `Error:` line with a control character in the error text show the escapes.
- Piped mode: the existing `tests/test_repl.py` piped and fake-TTY-input tests pass unchanged.
- Run the full offline suite after each ticket. No live credentials or paid calls. The final visual look of the Input Box is checked manually in a real terminal.

## Out of Scope

New Tools (file, web, memory, shell). Persisted input history or Conversation resume. Full-screen TUI, a full `╭─╮` border, and type-ahead during a request. Streaming answers. Parallel Tool execution and Tool result size limits (the 120-character cut is display only; the model still receives the full result). Changing the Call Log schema, the Budget Guardrail, or any Provider. Sanitizing what is sent to the model, stored in the Conversation or written to the Call Log; filtering non-control Unicode (e.g. bidirectional overrides); sanitizing configuration-derived text.

## Further Notes

ADR-0004 is added because the `prompt_toolkit` choice is surprising next to ADR-0002's preference for hand-rolled code and carries a real trade-off. `jsonschema` gets no ADR: it is already in the lock file, and the brief settles it over a hand-rolled validator.

`prompt_toolkit` facts used here were checked against its documentation: `PromptSession` keeps an `InMemoryHistory` by default; `bottom_toolbar` accepts a callable re-evaluated on every render; `multiline=True` makes Enter insert a newline, so the reversed binding needs custom `KeyBindings`; Ctrl+C raises `KeyboardInterrupt` and Ctrl+D raises `EOFError`; tests use `create_pipe_input()` and `DummyOutput()`. The latest release is 3.0.53, requiring Python 3.10 or newer. `jsonschema` facts: `Draft202012Validator`, `iter_errors`, `check_schema` (raises `SchemaError`), and `ValidationError.message`.
