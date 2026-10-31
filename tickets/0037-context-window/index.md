# Tickets: 0037-context-window

Spec: `docs/specs/0037-context-window.md`. Brief: `docs/briefs/0037-context-window.md`.

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Configure and enforce complete exchange budgets | none | done |
| 02 | Make manual Compression bounded and transactional | 01 | done |
| 03 | Compress preventively without losing pending Tool exchanges | 02 | done |
| 04 | Recover one rejected exchange and verify final observability | 03 | done |
| 05 | Reject context-truncated summaries without changing Conversation | 04 | done |
| 06 | Use published input limits as capacity and make soft-trigger Compression optional | 05 | done |
| 07 | Never continue after an unlogged summarization Attempt | 06 | done |

Tickets 01-05 and the earlier whole-feature review (`feature.review.md`) are approved, including reported error usage and Anthropic context-truncated summary rejection. A later review found two defects (brief settled decisions 13-15), corrected by 06; the fresh whole-feature review after 06 is approved. 07 is a small orchestrator-written correction of a pre-existing R6/R9 defect that review surfaced. Numeric blocking edges refer to this directory. No prior fast-path ticket exists for this feature; none is orphaned or superseded.

## Why these slices

- **01:** A user can persist a budget/route override, inspect honest usage, send all retained history within the complete-request ceiling, or receive a visible local stop. It includes the Provider Contract change, not a standalone metadata/refactor ticket. It removes legacy post-success Auto-Compress/Continuation behavior; automatic prevention arrives in 03. Until then, oversize input stops rather than being silently omitted or sent unchecked.
- **02:** `/compress` can handle older context larger than the easy route through multiple fitting requests and a single replay-safe commit. This manual checkpoint isolates paid summarization and persistence failure behavior before inserting them into a live Tool loop.
- **03:** Ordinary tasks and Tool follow-ups gain automatic prevention, exact two-complete-turn protection and Gemini replay rebasing. This is independently useful even without recovery for uncertain upstream limits.
- **04:** Provider-specific overflow recovery adds one same-exchange retry without Tool reruns, and final user documentation/usage regressions make the complete behavior reviewable. Not a tests-only or generic polish ticket.
- **05:** A narrowly scoped Provider-to-REPL correction rejects unfinished Anthropic summaries for all existing Compression callers and proves failure preserves live/replayed state. This pre-existing R6 defect was discovered outside 04's verdict; the separate checkpoint avoids reopening approved work or mixing it into 04's accounting correction.
- **06:** One small correction for two defects in already-approved behavior. Real metadata never produced a known total, so the 250000 default never applied. A soft-trigger Compression failure, or re-summarizing a summary-only Conversation, blocked or charged exchanges that fit the mandatory ceiling. Both changes touch only limit resolution and the existing preventive gate and share the same test fixtures, so they ship as one ticket rather than two.

## Requirement coverage

| Requirement | Owning tickets | Evidence expected |
|---|---|---|
| R1 | 01 | Config/default/precedence/save failures; immutable task snapshot; Resume settings |
| R2 | 01, 06 | Identity overrides; metadata normalization; known/manual/unknown/assumed provenance; published input limit as known total with real-metadata resolution (06 AC1-2) |
| R3 | 01, 02, 06 | Formula boundaries and explicit four-Provider caps; smaller summarization caps; 200000→174000 and 250000→224000 real-route values (06 AC2) |
| R4 | 01, 02, 03, 04 | Complete local LiteLLM token estimate; encoding/generic-fallback labels; offline assets and visible measurement failures; no byte proxy/paid counting; no 20-turn cut; summaries/rebased replay/recovery measured once |
| R5 | 03, 06 | Initial/retry/Escalation/Tool follow-up preflight; input-only 80% trigger/60% target; independent mandatory ceiling; soft trigger only with eligible older turns, soft failure proceeds within ceiling (06 AC3-5) |
| R6 | 02, 03, 05, 06 | Manual and preventive multi-block construction; no-progress/failure preservation; context-truncated block/combination rejection across manual/preventive/recovery callers (05 AC1-3); soft-only failure exception (06 AC4-5) |
| R7 | 01, 03, 04, 05, 06 | Local hard stop, preserved Tool evidence, no automatic task/Tool rerun; unfinished summary stops pending follow-up above the ceiling or in recovery (05 AC3, 06 AC5); soft-failure Tool follow-up keeps once-only evidence (06 AC4) |
| R8 | 04, 05, 06 | Positive overflow taxonomy; one reduced same-exchange retry or visible error; unfinished recovery summary prevents retry (05 AC3); summary-only recovery still reduces and recovery failure still stops (06 AC3, AC5) |
| R9 | 02, 03, 04, 05, 06 | Atomic final-summary commit; legacy two-turn replay; pending-turn/error ordering; no commit and unchanged live/Resume state on context-truncation (05 AC2-3); no commit on soft failure, persistence failures still stop (06 AC4) |
| R10 | 01, 02, 03, 05, 06 | No post-success Continuation; manual and automatic notices/pending continuation; visible summary failure without success notice (05 AC2-3); soft-failure proceed notice (06 AC4) |
| R11 | 01, 02, 03, 04, 05, 06 | Honest usage across failures/config changes; cache-inclusive counters and all costs; truncated-summary usage/cost retained normally (05 AC4); resolved published capacity label; soft-failure summary Attempt charged once (06 AC1, AC4) |

## Planning validation

The dependency order is `01 → 02 → 03 → 04 → 05 → 06`; each blocker exists and no cycle is possible. All R1–R11 requirements map to ticket acceptance criteria; the explicit R6 context-truncation clarification maps to 05 AC1-3, with regression validation in AC5. The token-counting correction preserves the original four slices and blockers; it changes the shared estimator and its cross-slice checks, not product scope or calling architecture. Ticket 05 appends only the review-discovered summary-validation correction, without replanning 01-04. Ticket 06 appends only the post-review capacity and soft-trigger correction (brief decisions 13-15), superseding the earlier R2 `max_input_tokens` prohibition and R5 summary-only soft reduction in the spec. It updates the affected approved-ticket tests to the new rule without editing tickets 01-05 or their reviews. ADR-0002 has a concise feature 0037 amendment authorizing local LiteLLM counting alongside existing cost/metadata utilities; no new ADR, dependency or external issue mirror is required. Planning changes do not modify production code, `docs/CONTEXT.md` or `.ai/PROJECT_STATE.md`.
