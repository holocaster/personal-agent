# The Call Log is the Conversation's durable record, and a Session spans Runs

Planned feature 0054 [ADR-0011](0011-direct-provider-model-selection.md) replaces tier/format compatibility with direct routes and independent execution identity. Durable Conversation ownership remains; pending plan review/delivery.

Extended by [ADR-0006](0006-persist-session-tier-and-remove-escalation.md) for feature 0039: the same Call Log also persists Session tier; the monetary Budget Guardrail is removed, while Run spend still resets on Resume. The text below records the original Resume decision.

Further extended by [ADR-0007](0007-periodic-session-tier-reevaluation.md), implemented in feature 0041: submission deltas and routing policy also restore evaluation progress and cumulative input independently of Conversation.

Until now the Conversation lived only in memory and was discarded when the process exited, and the Call Log was an after-the-fact record nobody read back. Session Resume needs a durable Conversation. We considered a separate conversation file per Session and rejected it: it would duplicate what the Call Log already holds and could drift from it. We considered rebuilding the Conversation heuristically from Attempt entries and rejected it: Attempts do not say which turn succeeded, failed, or was interrupted, or where `/clear` happened, so any rebuild would guess. Instead the REPL writes an explicit Turn End per routed turn (the `ok` one carries exactly the messages that entered the Conversation) and a `conversation_cleared` entry per `/clear`, and `session_start` declares `log_version: 2` so a reader can tell which files carry that record.

A Resume continues the same Session: same Session Id, same Call Log file, with a `session_resumed` entry opening each later Run and `session_end` closing each Run. We rejected minting a new Session that copies or links back to the old history, because both reference agents (Hermes `reopen_session`, DeepSeek Harness appending a `resume` header to the same log) continue the same session, and a chain of files would break ADR-0003's "one self-contained file per Session". This amends ADR-0003: one file per Session still holds, but a Session is no longer one process; it is one or more Runs.

## Consequences

The Call Log format now has readers inside the program, so its entry shapes are a contract: changing Turn End or `conversation_cleared` breaks Resume of existing files. Call Logs without `log_version: 2` cannot be resumed and no best-effort path is provided. The Budget Guardrail and Status Footer spend stay per Run and reset on Resume; the Router still never reads the Call Log to make a spending decision. Two concurrent Runs of one Session would interleave lines in one file and are unsupported, not guarded. Revisit if Resume must survive a format change, which would call for a migration, not a heuristic reader.
