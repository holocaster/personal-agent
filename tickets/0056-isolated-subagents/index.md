# Tickets: 0056-isolated-subagents

| # | Title | Blocked by | Status |
|---|-------|------------|--------|
| 01 | Read bounded Skill resources and expose installed SDD dependencies | none | done |
| 02 | Execute named native Subagents with isolated state and parent boundaries | 01 | done |

## Coverage

| Spec requirements | Ticket |
|---|---|
| R01-R03 | 01 |
| R04-R21 | 02 |

The graph is `01 -> 02`. Ticket 01 makes global Skill support files usable independently. Ticket 02 keeps a runnable child path together with its permission, confirmation, persistence, accounting and cleanup guarantees; splitting those boundaries would create incomplete execution checkpoints. Implementation remains incremental within each ticket.
