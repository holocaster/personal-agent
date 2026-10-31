# Tickets: 0002-router-reliability

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | A transient failure is retried instead of losing the task | none | done |
| 02 | An exhausted tier escalates to the next one up | 01 | done |
| 03 | A session budget can stop an Escalation from running up the bill | 02 | done |

Spec: `docs/specs/0002-router-reliability.md`
Brief: `docs/briefs/0002-router-reliability.md`
ADRs: `docs/adrs/0001-escalate-on-technical-failure-only.md` (constrains ticket 02).

The three slices share one code path (the Router's `route()`) and land in a real
dependency order: retry introduces the Attempt and the per-Attempt Call Log entry,
Escalation consumes retry's "this tier is exhausted" signal, and the Budget Guardrail
gates the transition Escalation performs. The Call Log schema change is folded into
01 because that is where Attempts first exist.

Manual tier override in the REPL is out of scope for this feature — it gets its own
brief later and has no ticket here.
