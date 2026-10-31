# Tickets: 0005-agentic-repl

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Session Conversation, Context Window, and local commands | none | done |
| 02 | Safe calculator and clock Tool loops across all Providers | 01 | done |
| 03 | Isolate the offline test suite from ambient environment values | none | done |

Spec: `docs/specs/0005-agentic-repl.md`
Brief: `docs/briefs/0005-agentic-repl.md`
ADRs: `docs/adrs/0001-escalate-on-technical-failure-only.md`, `docs/adrs/0002-hand-rolled-provider-contract.md`.

## Coverage

| Spec requirements | Tickets |
|---|---|
| R01 | 01 |
| R02 | 01, 02 |
| R03 | 01, 02 |
| R04 | 01, 02 |
| R05 | 01, 02 |
| R06 | 01, 02 |
| R07 | 02 |
| R08 | 02 |
| R09 | 02 |
| R10 | 02 |
| R11 | 02 |
| R12 | 02 |
| R13 | 02 |
| R14 | 02 |
| R15 | 02 |
| R16 | 01, 02 |

Ticket 03 maps to no spec requirement by design: it is a no-spec fast-path ticket for a pre-existing test-isolation defect surfaced by ticket 01's review, outside the scope of `docs/specs/0005-agentic-repl.md`. Its own acceptance criteria are normative; the spec and brief were deliberately left untouched.

Ticket 01 delivers useful session behavior and context independently of Tools. Ticket 02 uses that Conversation boundary for a complete Tool path, including all four thin REST translations and its safety/reliability acceptance tests. Splitting ticket 02 by Provider or technical layer would leave the shared contract partially integrated and add reload/review overhead without a necessary checkpoint; it is one bounded implementation context.

Only edge: 01 -> 02. Ticket 03 is unconnected: it changes test infrastructure only, so it neither gates nor is gated by 01 and 02, and it can be picked up in any order. The frontier is now 02 and 03. No pre-existing fast-path ticket exists for this feature. Status lives only in this index.
