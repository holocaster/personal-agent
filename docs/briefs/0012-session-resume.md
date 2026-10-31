# 0012 - Session Resume

## Goal

Let the user continue a previous Session after the process exits. Today the
Conversation is lost when the REPL ends, although the Call Log already records
every exchange. The Call Log becomes the Conversation's durable record, so a
new Run can rebuild it exactly, without heuristics over Attempt entries.

## Scope

1. Write a Turn End entry for every routed turn, at the point the REPL decides
   its outcome: `status: ok` with the turn's messages (exactly what entered the
   Conversation), `status: error` with the error shown to the user, or
   `status: interrupted`.
2. Write a `conversation_cleared` entry when `/clear` runs.
3. `session_start` records `log_version: 2`.
4. Add a `--resume <session-id>` startup flag; `--resume last` picks the most
   recent Session (highest Session Id in the Call Log directory).
5. On Resume, rebuild the Conversation from the messages of `ok` Turn Ends
   after the last `conversation_cleared`, append a `session_resumed` entry
   (current tier mappings, like `session_start`) to the same Call Log file,
   and keep appending there. `session_end` closes each Run.
6. Print one line on Resume: `Resumed session <id>: N turns.`
7. Resume errors (unknown id, `last` with no Sessions, a log without
   `log_version: 2`) print to stderr and exit 1 before the REPL opens.

## Out of scope

- A `/resume` REPL command, or a Session listing command (`ls logs/` covers it).
- Forking a Session into a new one.
- Best-effort resume of legacy logs.
- Guarding against two concurrent Runs of one Session.
- Summarizing or compacting old turns.

## Settled decisions

- Continue the same Session and Call Log file; no new Session Id, no copied
  history, no chain of files. Matches Hermes (`reopen_session`) and DeepSeek
  Harness (`request/header` with reason `resume` appended to the same log).
- Session now spans Runs; Run is one process execution (see `docs/CONTEXT.md`).
- Budget Guardrail and Status Footer spend are per Run and reset on Resume.
- Resume uses the current Tier Config.
- Failed and interrupted turns stay in the log but never re-enter the
  Conversation, matching the live REPL.
- This supersedes the prior "Conversation discarded at Session end" and
  "Call Log is only an after-the-fact record" decisions, and amends ADR-0003's
  one-file-per-process framing: warrants an ADR.

## Open questions

None.

## Known issues

- Pre-existing, out of scope: `tests/test_provider.py::test_call_anthropic_uses_messages_shape_and_normalizes_usage`
  and `::test_estimate_uses_real_litellm_pricing_and_tolerates_unknown_models`
  fail on the base before this feature (litellm pricing lookup returns None).
  Accepted and logged here; fixed in 0013-deterministic-cost-tests.
- Pre-existing, out of scope: `run_repl(output_stream=sys.stdout)` binds
  `sys.stdout` at import time, so later reassignments of `sys.stdout` (pytest
  capture) do not reach it. Harmless at runtime; affects tests only.
  Accepted and logged; a follow-up can default it to `None`.
