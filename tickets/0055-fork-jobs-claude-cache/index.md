# Tickets: 0055-fork-jobs-claude-cache

[Spec](../../docs/specs/0055-fork-jobs-claude-cache.md), [ADR-0013](../../docs/adrs/0013-fork-copies-into-a-new-session.md).

| # | Title | Blocked by | Status |
| --- | --- | --- | --- |
| 01 | [Activate Claude prompt caching](01-claude-prompt-caching.md) | none | done |
| 02 | [Run and control Background Jobs](02-background-jobs.md) | none | done |
| 03 | [Fork the Session into a self-contained child](03-fork-session.md) | 02 | done |
| 04 | [Fork seed-failure cleanup and honest /jobs stop message](04-review-follow-ups.md) | 02, 03 | done |

What each ticket delivers:

- Ticket 01 is a small, independent payload change in the adapters.
- Ticket 02 delivers Background Jobs end to end:
  - `shell` `background: true`;
  - the `job_status`/`job_stop` Tools;
  - `/jobs` and `/jobs stop`;
  - stopping jobs at Run end.
- Ticket 03 adds `/fork`, which must stop Background Jobs at the fork, so it builds on ticket 02's registry.

Ticket 01 has no edge to 02 or 03. It can be batched with them or run alone. Tickets 02 and 03 form a linear chain and can be implemented as one Batch. Each ticket ends fully green.

## Requirement coverage

| Requirements | Ticket |
| --- | --- |
| R1-R3: prompt cache activation | 01 |
| R12-R15: start, limits, inspect/stop, `/jobs` | 02 |
| R16: lifecycle (Run end and `/clear`) | 02; Fork stop in 03 |
| R4-R11: Fork | 03 |
| R17: docs and fixtures | 01 (cache docs), 02 (job docs, prompt fixture regeneration), 03 (Fork docs, `.notebook`, research status) |

The graph `02 -> 03`, with 01 standalone, is acyclic, and every blocker exists. This index alone owns ticket status. Main owns `docs/CONTEXT.md`, `.ai/PROJECT_STATE.md` and final feature verification.
