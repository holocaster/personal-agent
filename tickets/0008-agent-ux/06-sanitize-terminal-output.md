# 06: Sanitize model- and Provider-controlled terminal output

**What to build:** Control characters in text a model or Provider controls never reach the terminal raw. A Tool call whose raw arguments are `\x1b[2K\rllm> forged` shows a `tool>` line with visible escapes instead of erasing itself and forging an answer; the same holds for Tool names, `llm>` answers, `Error:` lines and `/history`. Normal multi-line answers keep their line breaks and tabs, and the REPL's own colors and spinner still work.

**Blocked by:** None (can start immediately). Tickets 01-05 are done; this amends the display added by 03.

**Spec:** `docs/specs/0008-agent-ux.md` (R15, R14); brief section "Added after review (routed as new ticket 06)"; review `tickets/0008-agent-ux/03-live-tool-display.review.md`.

- [x] One pure sanitizer in the terminal module (`tty`) replaces every C0 control (U+0000-U+001F), DEL (U+007F) and C1 control (U+0080-U+009F) with a visible `\xNN` escape. Multi-line mode keeps `\n` and `\t`; one-line mode keeps `\t` and shows `\n` as `\n`; `\r` and every other control are escaped in both. Plain text is returned unchanged.
- [x] Unit tests in `tests/test_tty.py`: ESC, BEL, CR, DEL and a C1 character are escaped; `\n`/`\t` kept in multi-line mode; `\n` escaped in one-line mode; plain text unchanged.
- [x] `format_tool_line` sanitizes the assembled line in one-line mode before the 120-character cut; a test proves a line with escaped controls is still one line of at most 120 characters.
- [x] The REPL sanitizes (multi-line mode) the `llm>` answer, the `Error:` line text, and every model-controlled piece of `/history` (message contents, Tool call names and arguments, Tool result names and contents), before `colorize`. Configuration-derived and REPL-owned text (tier line, `/models`, Status Footer, help) is unchanged.
- [x] Driven REPL test through the `urlopen` fake, in piped mode: a scripted Tool call with `arguments_raw` `\x1b[2K\rllm> forged` (rejected, not a valid JSON object), a Tool call whose name contains ESC and BEL, and a final answer containing ESC and BEL. The captured output contains no raw `\x1b`, `\x07` or `\r` and does contain their visible escapes (`\x1b`, `\x07`, `\x0d`).
- [x] Same scenario with `_TTYOutputStream`: the REPL's own color codes are still present and the untrusted ESC/BEL are escaped.
- [x] `/history` after that turn, and an `Error:` line whose error text contains a control character, show visible escapes and no raw control characters.
- [x] Display only: the Conversation, the Tool results handed back to the model and the Call Log are unchanged. Full offline suite passes; existing piped tests pass unchanged.
