# 04: Input Box

**What to build:** In an interactive terminal the user types into an Input Box: a horizontal rule, a `> ` input line, and a second rule, built on `prompt_toolkit` in inline mode so finished output stays in the terminal's scrollback. Arrow up recalls earlier inputs from this Session, Tab completes REPL Commands, Enter submits and Alt+Enter inserts a newline. While a request runs the spinner replaces the box. Piped and non-TTY input keep today's plain line mode.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0008-agent-ux.md` (R08, R09, R10, R11, R13, R14); **ADRs:** `docs/adrs/0004-prompt-toolkit-input-box.md`.

- [x] `prompt_toolkit` is declared in `pyproject.toml`; `uv.lock` updated. Only one new input module imports it.
- [x] The input module wraps one `PromptSession` per Session (inline, not full screen), accepts optional `input`/`output` for tests, and exposes one read operation returning the submitted text; `KeyboardInterrupt` (Ctrl+C) and `EOFError` (Ctrl+D) propagate.
- [x] Layout: rule of `─` across the terminal width, `> ` input line (the prompt message), then a second rule in the bottom toolbar, supplied as a callable. The toolbar callable is the hook ticket 05 extends with the Status Footer.
- [x] History is in memory only (`InMemoryHistory`); nothing written to disk.
- [x] Tab completes REPL Commands from the REPL's command list, only when the input starts with `/`.
- [x] Enter submits; Alt+Enter (Escape then Enter) inserts a newline, via custom `KeyBindings` that override the defaults; a multi-line submission is one task.
- [x] Pipe-input tests (`create_pipe_input()`, `DummyOutput()`): Enter submits, Escape+Enter yields a multi-line string, `/he` + Tab gives `/help`, arrow up recalls the previous input, Ctrl+C raises `KeyboardInterrupt`, Ctrl+D raises `EOFError`.
- [x] `run_repl` gains an optional Input Box parameter; with one, it reads through it and handles the text exactly like a plain-mode line; without one, behavior is unchanged, including `user> ` for a TTY input stream.
- [x] `__main__` builds the Input Box only when both stdin and stdout are TTYs.
- [x] During a request the existing spinner runs and output goes to stdout; Ctrl+C during a request prints `Interrupted.` and returns to the box. Ctrl+C / Ctrl+D at the box end the Session with Call Log reasons `interrupt` / `eof` (driven `run_repl` tests).
- [x] Existing piped and fake-TTY-input REPL tests pass unchanged; full offline suite passes.
- [x] Manually checked in a real terminal: framing looks like the brief's sketch (tune `reserve_space_for_menu` so the lower rule sits under the input), output stays in scrollback, resize and paste behave.
- [x] README documents the Input Box and its keys briefly.
