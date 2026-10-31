# 01: System Prompt with the current date, time and Tool rules

**What to build:** Every Provider exchange carries a System Prompt that tells the model today's local date, time and UTC offset, that arithmetic and time must come from Tools rather than guesses, and that it should answer in the user's language. A Session left open past midnight sends the new date on its next exchange. `current_time` stays a Tool.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0008-agent-ux.md` (R01, R02, R13, R14).

- [x] The Router's fixed System Prompt constant is replaced by a builder run on every exchange (every Attempt, including retries and Tool follow-ups).
- [x] The prompt contains a date line in the exact form `YYYY-MM-DD HH:MM +HH:MM` from the process's local timezone (e.g. `2026-09-22 17:30 -03:00`), a rule that arithmetic uses the calculator Tool and time comes from Tools or the date line and is never guessed, and a rule to answer in the language the user wrote in.
- [x] The local clock is read through one module-level swappable function in the Router, mirroring the Tool module's clock seam.
- [x] Test through the `urlopen` fake with a fixed clock: the `system` content sent to a Provider contains the date line and both rules.
- [x] Test that two exchanges in one request (initial plus Tool follow-up) with different clock values carry different date lines.
- [x] `current_time` behavior and every other routing behavior are unchanged; the full offline suite passes.
- [x] README gets one or two sentences on what the System Prompt now carries.
