# 03: Live Tool display

**What to build:** While a routed task runs, each executed Tool call prints one line as it happens, e.g. `tool> calculator(expression="2+2") -> 4`, before the answer. On a color terminal the line is yellow on success and red on error and never garbles the spinner; in piped mode it is printed plain. The model's intermediate text beside Tool calls is not printed.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0008-agent-ux.md` (R05, R06, R07, R13, R14).

- [x] A pure function formats one Tool result per R05: JSON-encoded `key=value` args joined by `, `; empty parentheses for no args; `...` for a call rejected before execution; single-key success result shown as the bare value (strings unquoted); otherwise compact JSON; errors as `error: <message>`; lines over 120 characters cut to 117 plus `...`. Unit-tested case by case.
- [x] `route` gains one optional keyword callback, invoked with each Tool result after its batch executes and before the follow-up exchange, in execution order. Default none; direct callers unaffected.
- [x] The REPL passes a callback that prints the line, yellow/red when `color_enabled`, plain otherwise (piped mode prints them too).
- [x] When the spinner runs, the line is written through the spinner under a lock shared with its frame loop: frame cleared, line written, spinner resumes. Tested in `tests/test_tty.py` style.
- [x] Driven REPL with a scripted calculator round: the `tool>` line appears before `llm>`; colored with `_TTYOutputStream`, uncolored with `StringIO`; the assistant's intermediate text is not printed, while `/history` still shows it.
- [x] Call Log lines and `/history` rendering are unchanged; existing piped tests pass unchanged.
- [x] README documents the `tool>` line in one short paragraph.
