# Tickets: 0039-session-tier-selection

Spec: [0039-session-tier-selection](../../docs/specs/0039-session-tier-selection.md).

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Keep failed tasks on one route and display uncapped Run spend | none | done |
| 02 | Evaluate and persist Session tier across commands and Resume | 01 | done |

## Requirement coverage

| Spec requirement | Ticket |
|---|---|
| R1 | 02 |
| R2 | 02 |
| R3 | 02 |
| R4 | 02 |
| R5 | 02 |
| R6 | 02 |
| R7 | 02 |
| R8 | 01, 02 |
| R9 | 01, 02 |
| R10 | 02 |
| R11 | 02 |
| R12 | 01, 02 |
| R13 | 01, 02 |

Ticket 01 independently delivers predictable technical failures and spend-only monetary reporting. Ticket 02 depends on that single-route execution path and retained spend accumulator, delivering evaluation, replay and commands together rather than splitting state persistence from its users.
