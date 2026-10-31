# Tickets: 0049-project-instructions

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Load recursive project instructions for ordinary task executions | none | done |

Execution prerequisite: feature 0048's traversal fix has passed independent review. This is an external feature prerequisite, not an additional ticket in this graph.

| Spec requirements | Ticket |
|---|---|
| R1–R9 | 01 |

One vertical slice covers loading, runtime use, repair/retry, budget protection and documentation; no layer-only ticket or new ADR is required.

Completed and independently approved after correction of exact hidden key filename exclusions. All 2079 tests passed; independent loader/integration checks: 69 passed. See [review](01-load-project-instructions.review.md). The user authorized commit and push on 2026-10-06.
