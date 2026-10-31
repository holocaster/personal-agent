# Tickets: 0020-auto-compress

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Auto-Compress a turn that nears the Context Limit | none | done |
| 02 | Continuation Turn after Auto-Compress, with notice and one-cycle cap | 01 | done |

Linear chain; 01 is a standalone checkpoint (the Conversation is already
protected from oversized requests), 02 adds the user-visible continuation.
Both may be run as one implementer + reviewer batch.

Requirement coverage: R1-R5 -> 01; R6-R8 -> 02; R9 -> 01 (always on, README
trigger) and 02 (README continuation and notice).
