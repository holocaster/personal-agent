# 0014 - Turn Controls

Brief: `docs/briefs/0014-turn-controls.md`. Extends `docs/specs/0012-session-resume.md`.
ADRs: ADR-0001 (Escalation on technical failure only), ADR-0005 (the Call Log
is the Conversation's durable record). Vocabulary (Tier Pin, Undo, Retry,
Compression, Conversation Summary) is in `docs/CONTEXT.md`.

## Problem Statement

Once a task is sent, the user has no say over how it is routed or what stays
in the Conversation. When the Classifier picks the wrong Complexity Tier, the
only fix is to reword the task. A bad answer stays in the Conversation and
keeps steering later turns. Re-asking the same task means retyping it. A long
Conversation silently loses its older turns at the Context Window cut, with no
way to keep their gist.

## Solution

Four new REPL Commands give the user direct control over routed turns:

- `/model <easy|medium|complex>` sets a Tier Pin for the rest of the Run, so
  routed turns skip the Classifier and start at that tier. `/model auto`
  removes it; `/model` shows it. The Status Footer shows an active pin.
- `/undo` removes the most recent successful turn from the Conversation.
- `/retry` re-sends the most recent routed task, first Undoing it if it
  succeeded.
- `/compress` replaces all but the two most recent turns with a Conversation
  Summary written by the easy tier. The summary travels in the System Prompt
  and `/history` shows it first.

Undo and Compression are recorded in the Call Log, so a Resume rebuilds the
same Conversation the live Run had. `/help`, Tab completion and the README
cover the new commands.

## User Stories

1. As a REPL user, I want to pin a Complexity Tier with `/model <tier>`, so that I can override a Classifier guess I disagree with.
2. As a REPL user, I want a pinned tier to apply to every later routed turn of the Run, so that I do not repeat the command per task.
3. As a REPL user, I want `/model auto` to remove the pin, so that the Classifier picks tiers again.
4. As a REPL user, I want `/model` with no argument to show the current pin or `auto`, so that I know how my next task will be routed.
5. As a REPL user, I want `/model` to reject anything other than a tier name or `auto`, so that I never pin a raw model id by mistake and Tier Config stays the only source of models.
6. As a REPL user, I want Escalation to still work when a pinned tier fails technically, so that a pin never makes me lose an answer the next tier could give (ADR-0001).
7. As a REPL user, I want the Budget Guardrail to still block Escalation from a pinned tier, so that pinning never bypasses my spend ceiling.
8. As a REPL user, I want the Status Footer to show an active pin, so that I do not forget it is on.
9. As a REPL user, I want the pin to reset when the Run ends, so that a Resume starts with the Classifier again.
10. As a Call Log reader, I want the pin not to be written to the Call Log as its own entry, so that the log keeps recording only Provider exchanges and Conversation changes; the Attempt entries already show the tier used.
11. As a REPL user, I want `/undo` to remove the most recent successful turn, so that a bad answer stops steering later turns.
12. As a REPL user, I want to run `/undo` repeatedly to remove several turns one by one, so that I can back up further without a multi-step command.
13. As a REPL user, I want a local error when there is no turn to undo, so that I know nothing changed.
14. As a REPL user, I want an Undo to survive a Resume, so that an undone turn does not come back in the next Run.
15. As a Call Log reader, I want a `turn_undone` entry for every Undo, so that I can see where the Conversation was trimmed while the original Turn End stays for audit.
16. As a REPL user, I want `/retry` to re-send my most recent routed task, so that I can get a fresh answer without retyping.
17. As a REPL user, I want `/retry` on a successful turn to replace that turn, so that the Conversation does not hold the same task twice.
18. As a REPL user, I want `/retry` on a failed or interrupted turn to simply send the task again, so that a transient problem is one command away from being fixed.
19. As a REPL user, I want the Classifier to run again on `/retry` unless a Tier Pin is set, so that I can combine `/model` and `/retry` to re-run a task at another tier.
20. As a REPL user, I want a local error when there is no previous task to retry, so that I know nothing was sent.
21. As a REPL user, I want `/compress` to replace all but the two most recent turns with a Conversation Summary, so that a long Conversation keeps the gist of older turns instead of losing them at the Context Window cut.
22. As a REPL user, I want the summary written by the easy tier, so that housekeeping stays cheap.
23. As a REPL user, I want the summary call to count toward my spend and appear in the Call Log as an Attempt, so that nothing I pay for is hidden.
24. As a REPL user, I want the summary call to retry transient failures but never escalate, so that housekeeping never jumps to an expensive tier.
25. As a REPL user, I want a failed summary call to leave my Conversation unchanged and show the error, so that a failure never costs me turns.
26. As a REPL user, I want `/compress` with two or fewer turns to print a local error and make no call, so that I do not pay for a no-op.
27. As a REPL user, I want the summary sent in the System Prompt, so that no fake user or assistant message breaks Provider role ordering.
28. As a REPL user, I want `/history` to show the Conversation Summary before the remaining turns, so that I see everything the model will receive.
29. As a REPL user, I want a second `/compress` to fold the previous summary into the new one, so that older context is never dropped by compressing twice.
30. As a REPL user, I want `/clear` to also drop the Conversation Summary, so that `/clear` still means a fresh Conversation.
31. As a REPL user, I want a Compression to survive a Resume, so that the next Run sees the summary plus the same remaining turns.
32. As a Call Log reader, I want a `conversation_compressed` entry carrying the summary, so that I can see where and how the Conversation was compressed while the original turns stay in the log for audit.
33. As a REPL user, I want `/help` to list `/model`, `/undo`, `/retry` and `/compress`, so that I can discover them.
34. As a REPL user, I want Tab to complete the new commands in the Input Box, so that they are as quick to type as the old ones.
35. As a README reader, I want the new commands documented, so that I can learn them without reading the code.

## Implementation Decisions

- **Router start tier.** `route()` gains an optional starting Complexity Tier.
  When given, the Classifier is skipped and the Escalation ladder starts at
  that tier; everything else (Attempts, Escalation, Budget Guardrail, Tool
  loop) is unchanged. When absent, behavior is exactly today's.
- **Tier Pin state.** Held by the REPL for the Run only, starting as `auto`
  (no pin). Never written to the Call Log and never restored on Resume.
- **`/model` command.** Accepts zero or one argument:
  - no argument: prints the current pin (the tier name) or `auto`;
  - `easy`, `medium`, `complex`: sets the pin and confirms it;
  - `auto`: removes the pin and confirms it;
  - anything else, or more than one argument: a local error naming the valid
    values; the pin is unchanged.
  `/model` is a separate command from the existing `/models`.
- **Status Footer.** `render_footer` gains the pin; when a pin is set the
  footer carries a segment naming the pinned tier. Without a pin the footer is
  exactly today's.
- **Undo.** `/undo` (no arguments) removes the last turn of the Conversation.
  A turn is only ever in the Conversation because its Turn End was `ok`, so
  the last turn is always the most recent successful one still present. With
  no turn, it prints a local error and writes nothing. It never removes the
  Conversation Summary. On success it writes a `turn_undone` entry (`type`,
  `timestamp`, `session_id`; no other field) and confirms.
- **Retry.** The REPL remembers the most recent routed task of the Run, its
  outcome, and (when `ok`) the turn it produced. `/retry` (no arguments):
  - with no routed task yet in this Run, prints a local error and sends
    nothing. A Resume starts with no previous task: restored turns are not
    retryable.
  - if that task ended `ok` and its turn is still the last turn of the
    Conversation, Undoes it exactly like `/undo` (same `turn_undone` entry),
    then routes the task;
  - otherwise (it ended `error` or `interrupted`, or its turn was already
    removed by `/undo`, `/clear` or Compression), routes the task without
    Undoing anything.
  The re-sent task is a normal routed turn: same spinner, Tool lines, Turn End,
  output and Status Footer update. It uses the current Tier Pin, so the
  Classifier runs again only when no pin is set. If the re-sent turn fails,
  the Undone turn stays undone.
- **Compression call.** A new Router-level housekeeping function produces the
  Conversation Summary: it calls the easy tier's Provider and model through the
  existing single-exchange Attempt path (local retries on retryable failures,
  every Attempt logged as a normal `attempt` entry, cost recorded in the Budget
  Guardrail), with no Tools advertised, no Escalation, and no Turn End. Its
  input is one user message holding a summarization instruction, the previous
  Conversation Summary if any, and the replaced turns rendered as plain text
  (user, assistant, Tool call and Tool result lines), so no Tool-message
  pairing rules apply. The Attempt entry's `task` is `/compress`. It returns
  the summary text or the error text; an empty answer counts as an error.
- **`/compress` command.** No arguments. With two or fewer turns, prints a
  local error and makes no call. Otherwise it summarizes the previous summary
  plus every turn except the two most recent (all of them, not only those
  inside the Context Window). On success the Conversation becomes the new
  summary plus the two most recent turns, a `conversation_compressed` entry
  (`type`, `timestamp`, `session_id`, `summary`) is written, and the REPL
  confirms how many turns were compressed. On failure the Conversation and
  summary are unchanged, no entry is written, and the error is shown like a
  routed-turn error. A spinner shows while the call runs, as for routed turns.
- **System Prompt.** Gains an optional Conversation Summary section, appended
  after the existing rules, present only when a summary exists. `route()`
  receives the current summary and passes it to every exchange of the turn,
  including Tool follow-ups and Escalation. The summary is never added as a
  message.
- **`/history`.** When a summary exists it is printed first as its own
  sanitized line (`summary: <text>`), then the remaining turns as today. With
  only a summary and no turns, only the summary line prints. With neither,
  today's "No completed turns yet." line.
- **`/clear`.** Also drops the Conversation Summary. Its entry is unchanged.
- **Resume rule.** The loader replays the Call Log in order, which keeps the
  rebuilt Conversation identical to what the live Run held:
  - `conversation_cleared`: no turns, no summary;
  - `turn_end` with `ok`: append its turn;
  - `turn_undone`: remove the last remaining turn (no-op when none);
  - `conversation_compressed`: the summary becomes the entry's `summary`, and
    only the two most recent remaining turns are kept.
  This is the brief's rule (latest summary; `ok` Turn Ends after the last
  clear or Compression; Undos applied in log order) made exact for the two
  turns a Compression keeps, whose Turn Ends precede the
  `conversation_compressed` entry. The loader returns the summary (or none)
  together with the turns; the resumed Session passed to `run_repl` carries
  it. The `Resumed session <id>: N turns.` line is unchanged (N counts turns,
  not the summary). `log_version` stays 2: the new entry types are additive,
  and a log without them resumes exactly as before.
- **Commands list.** `COMMANDS` (which feeds `/help`'s unknown-command check
  and the Input Box Tab completion) gains `/model`, `/undo`, `/retry`,
  `/compress`, and `HELP_TEXT` gains one line per command. The generic
  "takes no arguments" rule keeps applying to every command except `/model`.
- **README.** The REPL commands section documents the four commands; the
  Resume and Call Log sections mention `turn_undone` and
  `conversation_compressed`.
- **No ADR.** Every decision here is either settled in the brief and
  `docs/CONTEXT.md` or a local mechanism choice; ADR-0001 and ADR-0005 already
  cover Escalation and the Call Log as the Conversation record.

## Testing Decisions

- Good tests assert external behavior only: what the REPL prints, the Status
  Footer text, which tier and model reach the fake Provider and what request
  body it receives (System Prompt, messages), the lines in the Session's Call
  Log file, and the Conversation restored on Resume. No assertions on private
  helpers or module globals.
- Seams (existing, highest available; no new seam):
  - `run_repl` driven with an input stream and an output stream, the Provider
    faked at `urlopen` via the existing `install_fake_urlopen` fixture. Covers
    every command, the footer (through the Input Box footer callable or
    `render_footer`), the System Prompt carrying the summary, the Call Log
    entries, and a second `run_repl` with `resumed` for the Resume rule.
  - `main` with an explicit argument list for Resume end to end, as in 0012,
    where the loader's summary must reach the REPL.
  - `route()` directly for the start-tier behavior (Classifier skipped,
    Escalation and Budget Guardrail from the pinned tier), as the existing
    routing tests do.
  - `InputBox` with a pipe input for Tab completion of the new commands.
- Resume fixtures are built by running a real first Run through `run_repl`
  and resetting Call Log state with `call_log.reset_session`, never by
  hand-writing log entries.
- Prior art: `tests/test_repl.py` (`/clear`, `/history`, Turn End, Resume via
  `run_repl`), `tests/test_routing.py` (Escalation, Budget Guardrail, Attempt
  logging), `tests/test_main.py` (`--resume`), `tests/test_input_box.py` (Tab
  completion, footer), `tests/test_call_log.py`.

## Out of Scope

- Pinning a raw `provider:model`.
- Automatic Compression; the Context Window cut stays as it is.
- Undo of more than one turn per command.
- Redo.
- Persisting the Tier Pin across Runs, or writing it to the Call Log.
- Retrying a task from an earlier Run after a Resume.
- Choosing the summarizing tier or the number of kept turns.

## Further Notes

- `/retry` after a successful turn that was already removed (by `/undo`,
  `/clear` or Compression) re-sends the task without Undoing anything else;
  this keeps `/retry` from ever removing a turn other than the one it retries.
- A Compression can be Undone only turn by turn: `/undo` after `/compress`
  removes the newest kept turn, never the summary. Only `/clear` drops the
  summary.
- The summary call's Attempts land in the Call Log between Turn Ends like any
  other Attempt; Resume ignores Attempt entries, as in 0012.
