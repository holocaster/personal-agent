# 0012 - Session Resume

Brief: `docs/briefs/0012-session-resume.md`. ADR: `docs/adrs/0005-call-log-is-the-conversation-record.md` (amends ADR-0003).

## Problem Statement

When the REPL exits, the Conversation is gone. The Call Log already records
every Provider exchange and Tool execution of the Session, but nothing reads it
back, and its Attempt entries cannot rebuild the Conversation exactly: they do
not say which turn ended well, which failed, which was interrupted, or where a
`/clear` happened. To pick up where they left off, the user has to retype
context by hand.

## Solution

The Call Log becomes the Conversation's durable record. Every routed turn ends
with a Turn End entry that states its outcome and, for a successful turn, holds
exactly the messages that entered the Conversation. `/clear` is recorded. New
Call Logs declare `log_version: 2`.

The user starts a new Run of an existing Session with `--resume <session-id>`
or `--resume last`. The REPL rebuilds the Conversation from the `ok` Turn Ends
after the last Conversation clear, prints `Resumed session <id>: N turns.`, and
keeps appending to the same Call Log file under the same Session Id. Anything
that prevents a Resume is reported on stderr with exit code 1 before the REPL
opens.

## User Stories

1. As a REPL user, I want to continue a previous Session after the process exits, so that I do not lose the context I built up.
2. As a REPL user, I want to name the Session to resume by its Session Id, so that I can pick any past Session.
3. As a REPL user, I want `--resume last` to pick the most recent Session, so that I do not have to look up an id for the common case.
4. As a REPL user, I want a single confirmation line naming the Session and how many turns came back, so that I know the Resume worked and what the model will see.
5. As a REPL user, I want a resumed Conversation to contain exactly the turns that succeeded, so that the model sees the same history the live REPL would have kept.
6. As a REPL user, I want failed turns to stay out of a resumed Conversation, so that errors never become model context, matching the live REPL.
7. As a REPL user, I want interrupted turns to stay out of a resumed Conversation, so that a half-finished turn never becomes model context.
8. As a REPL user, I want turns I cleared with `/clear` to stay cleared after a Resume, so that `/clear` means the same thing across Runs.
9. As a REPL user, I want `/history` after a Resume to show the restored turns, so that I can see what the model will receive.
10. As a REPL user, I want the Context Window rule (20 most recent complete turns) to apply to restored turns too, so that a resumed Session behaves like a live one.
11. As a REPL user, I want Tool calls and Tool results of restored turns to come back intact, so that the model sees complete turns and Provider requests stay valid.
12. As a REPL user, I want a Resume to use my current Tier Config, so that model changes I made since the last Run take effect.
13. As a REPL user, I want the Budget Guardrail and the Status Footer spend to start at zero on each Run, so that spend matches the documented per-Run window.
14. As a REPL user, I want a clear error and a non-zero exit when the Session Id I gave does not exist, so that I do not start chatting in an empty Conversation by mistake.
15. As a REPL user, I want a clear error when I use `--resume last` and there are no Sessions, so that I know there is nothing to resume.
16. As a REPL user, I want a clear error when I try to resume a Call Log written before Resume existed, so that I am never handed a guessed Conversation.
17. As a REPL user, I want Resume errors reported before the REPL opens, so that I never see a prompt for a Session that could not be loaded.
18. As a REPL user, I want to resume the same Session more than once, so that one Session can span many Runs.
19. As a REPL user, I want starting without `--resume` to behave exactly as today, so that the flag is opt-in.
20. As a Call Log reader, I want every routed turn to end with a Turn End entry, so that I can tell what each turn's outcome was without inferring it from Attempts.
21. As a Call Log reader, I want an `ok` Turn End to carry the turn's messages, so that the log alone reconstructs the Conversation.
22. As a Call Log reader, I want an `error` Turn End to carry the error shown to the user, so that I see what the user saw.
23. As a Call Log reader, I want an `interrupted` Turn End when the user interrupts a turn, so that interruptions are explicit.
24. As a Call Log reader, I want Attempt entries after the last Turn End to mean the process died mid-turn, so that crashes are recognizable.
25. As a Call Log reader, I want a `conversation_cleared` entry for every `/clear`, so that I can see where the Conversation was reset.
26. As a Call Log reader, I want `session_start` to declare `log_version: 2`, so that I can tell which files support Resume.
27. As a Call Log reader, I want a `session_resumed` entry opening each later Run with the tier mappings in effect, so that I know which models each Run used.
28. As a Call Log reader, I want a `session_end` closing each Run with that Run's spend, so that per-Run cost stays visible.
29. As a Call Log reader, I want every Run of a Session in one file, so that a Session's full flow stays self-contained (ADR-0003).

## Implementation Decisions

- **Call Log format version.** `session_start` gains `log_version: 2`. A file
  whose first entry is not a `session_start` with `log_version: 2` cannot be
  resumed. There is no fallback reconstruction from Attempt entries.
- **Turn End entry.** `type: "turn_end"`, with the usual `timestamp` and
  `session_id`, and `status`:
  - `ok`: plus `messages`, the exact normalized messages the REPL appends to
    the Conversation for that turn (user message, assistant messages with Tool
    calls, Tool results, final assistant message). These are already
    JSON-serializable dicts and hold no Provider-owned replay data.
  - `error`: plus `error`, the error text shown to the user (the Router
    result's error, before terminal sanitization).
  - `interrupted`: no extra field.
  The REPL writes it at the point it decides the turn's outcome. REPL
  Commands and blank lines are not routed turns and write no Turn End.
- **Conversation clear entry.** `/clear` writes `type: "conversation_cleared"`
  after emptying the in-memory Conversation.
- **Session resumed entry.** `type: "session_resumed"` carries the current
  Tier Config mappings in the same `tiers` shape as `session_start`. It does
  not repeat `log_version`.
- **Call Log module.** Owns reading as well as writing. It gains:
  - a way to write Turn End and Conversation clear entries for the current
    Session;
  - a Resume loader that, given a Session Id, returns the rebuilt Conversation
    as a list of turns (each turn the tuple of messages from one `ok` Turn End
    after the last `conversation_cleared`), or raises a single Resume error
    type whose message is what the user sees;
  - a "most recent Session" lookup for `last`: the highest Session Id among
    Call Log files in the directory of the configured base path that match the
    base path's naming (`<root>-<session-id><ext>`);
  - a resume counterpart to `start_session` that sets the current Session Id
    to the resumed one, resets the per-Run spend to zero, and writes
    `session_resumed`.
  `session_end` is unchanged and closes every Run.
- **Session Id validation.** A `--resume` value that is not `last` and does
  not have the Session Id shape (sortable UTC timestamp plus short suffix) is
  reported as an unknown Session; it is never used to build a path. This keeps
  the value from escaping the Call Log directory.
- **Resume errors.** One line on stderr, exit code 1, before the REPL opens:
  unknown Session Id (no such Call Log file, or bad shape); `last` with no
  Session files; a Call Log without `log_version: 2`; a Call Log line that is
  not valid JSON. No best-effort recovery.
- **Startup.** `main` parses arguments with stdlib `argparse`, one optional
  `--resume SESSION`. It accepts an explicit argument list (defaulting to the
  process arguments) so tests can call it without pytest's own argv leaking
  in. Resume resolution and loading run after `.env` loading, Workspace
  configuration, Tier Config validation and Budget Guardrail loading, and
  before the Input Box is created and the REPL starts.
- **REPL.** `run_repl` accepts an optional resumed Session (its Session Id and
  restored turns). When given, it seeds the Conversation with those turns,
  calls the Call Log resume counterpart instead of `start_session`, and prints
  `Resumed session <id>: N turns.` (N is the number of restored turns, printed
  literally even when 1 or 0) before the first input. Without it, behavior is
  unchanged.
- **Per-Run spend.** The Budget Guardrail is already created per process, so it
  resets by construction. The Call Log running total that feeds the Status
  Footer and `session_end.total_cost` resets on Resume.
- **Tier Config.** Resume uses the current Tier Config; the tiers recorded in
  earlier entries are informational only.
- **Recorded decisions.** The durable-record and same-file choices are recorded
  in ADR-0005, which amends ADR-0003. Vocabulary (Session, Run, Resume, Turn
  End) is in `docs/CONTEXT.md`.

## Testing Decisions

- Good tests assert external behavior only: the lines written to a Session's
  Call Log file, what the REPL prints, what reaches the Provider, stderr and
  exit code. No assertions on private helpers or module globals.
- Seams (existing, highest available; no new seam):
  - `run_repl` driven with an input stream and an output stream, the Provider
    faked at `urlopen` via the existing `install_fake_urlopen` fixture. Covers
    Turn End, `conversation_cleared`, `log_version`, restored Conversation,
    `session_resumed`, the Resume line, and what the next Provider request
    contains after Resume.
  - `main` called with an explicit argument list and `sys.stdin` replaced.
    Covers `--resume <id>`, `--resume last`, and every Resume error (stderr
    text and exit code 1, REPL never entered).
- Tests build a resumable Call Log by running a real first Run through
  `run_repl`, then reset the in-process Call Log state (existing
  `call_log.reset_session`) and resume, so fixtures never hand-write the log
  format. Legacy and malformed logs are the exception and are written directly.
- Prior art: `tests/test_repl.py` (session_start/session_end line order,
  `/clear`, `/history`, interrupt handling), `tests/test_call_log.py` (per-Session
  file paths, running total), `tests/test_main.py` (startup errors before the
  REPL, stderr and non-zero exit). `tests/conftest.py` already isolates the log
  base path per test.

## Out of Scope

- A `/resume` REPL command or a Session listing command.
- Forking a Session into a new Session.
- Best-effort Resume of Call Logs without `log_version: 2`.
- Guarding against two concurrent Runs of one Session.
- Summarizing or compacting old turns.
- Log rotation or pruning.

## Further Notes

- A Session that died mid-turn leaves Attempt (and maybe Tool execution)
  entries with no Turn End; Resume simply ignores them, like any non-`ok` turn.
- A Run that is itself a Resume can be resumed again; the loader treats
  `session_resumed` and `session_end` entries as neutral.
