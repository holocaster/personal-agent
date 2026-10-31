# Tickets: 0050-project-session-discovery

Spec: [0050-project-session-discovery](../../docs/specs/0050-project-session-discovery.md). ADR: [0008](../../docs/adrs/0008-project-scoped-session-discovery.md).

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Keep each Run's logs in its starting project and Resume the latest Run | none | done |
| 02 | Discover, read and search recorded Sessions through one bounded Tool | 01 | done |
| 03 | Offer Other and reject invalid Question option numbers | none | done |

Ticket 01 independently delivers correct project storage and CLI Resume. Ticket 02 delivers the model's complete historical discovery flow. Ticket 03 independently corrects user-facing answers. Their dependency graph is acyclic; 03 does not depend on discovery.

| Spec requirements | Ticket coverage |
|---|---|
| R01–R05 | 01 |
| R06–R08 | 01 (storage/recency seam), 02 (Tool/tolerant reader integration) |
| R09–R15 | 02 |
| R16–R19 | 03 |
| R20 | 01 (storage/isolation/docs), 02 (discovery/docs), 03 (Question/docs) |

All tickets approved (02 at `0983b8f`, 03 at `9c4cb57`); full suite 2265 passed at `9c4cb57`.
