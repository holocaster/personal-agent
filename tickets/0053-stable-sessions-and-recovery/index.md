# Tickets: 0053-stable-sessions-and-recovery

Canonical spec: [0053](../../docs/specs/0053-stable-sessions-and-recovery.md). Status lives only here. All tickets are independently executable; sequential implementation/review is the approved orchestration policy, not a blocking edge.

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Stable selection with historical replay | none | done |
| 02 | Durable OpenRouter affinity | none | done |
| 03 | Stable prompt prefix and reviewed surface fixtures | none | done |
| 04 | Recorded task routes and cache-aware accounting | none | done |
| 05 | Recover the latest file-changing execution | none | done |

Recommended sequence: 01 → 02 → 03 → 04 → 05. Each completed ticket has standalone value and must be independently reviewed. Ticket 05 is isolated: do not batch its implementation or review with another ticket. Final feature verification covers all six priorities after the five ticket reviews. No prefactoring-only ticket or artificial schema/API dependency is needed.

Resumed on 2026-10-15. All five tickets are independently approved with exact-range BRANCH security and Standards/Spec evidence in their `.review.md` files. Ticket 05 passed after its independently reproduced recursive-alias privacy finding was corrected at `0f5b674`; final full suite: 2757 passed. User authorized remaining local commits. Independent final feature verification passed all six priorities and R1–R32; the pre-existing Gemini thought-token limitation is accepted and logged in the brief.

## Requirement coverage

| Spec requirement | Ticket |
|---|---|
| R1, R2, R3, R4, R5, R6, R7 | 01 |
| R8, R9, R10 | 02 |
| R11, R12, R13, R14, R29, R30, R31 | 03 |
| R15, R16, R17, R18, R19, R20 | 04 |
| R21, R22, R23, R24, R25, R26, R27, R28 | 05 |
| R32 | 01, 02, 03, 04, 05 |

Priority 1 maps to 01; priority 2 to 02; priorities 3 and 6 to 03; priority 4 to 04; priority 5 to 05. Prompt ordering and production snapshots form one complete surface change; keeping them together avoids an artificial dependent reload. No existing 0053 fast-path ticket is superseded or orphaned.

## Verification contract

Run focused offline checks incrementally, then `uv run --offline pytest -q` for each completed ticket. The full suite needs `require_escalated` execution because existing tests bind local sockets/start MCP processes; sandbox permission failures are environmental and must not be masked by test edits. No paid model/API call, package installation, sudo or push. Local commits are authorized for this feature. Preserve others' edits, stage only the ticket's intended files and never stage `.env`/secrets.

Independent review uses the exact ticket implementation range and repository-required branch security review. Reviewers verify stored-log compatibility and documented behavior as well as tests; recovery specifically requires file-state and failure-injection evidence. The orchestrator updates CONTEXT/PROJECT_STATE from implementer handoff. Actual implementation/review outcomes must replace ready status as work progresses.

## Final feature verification

Verified against all six priorities and R1–R32: [record](../../.ai/0053-feature-verification.json). Fresh cross-feature integration: 756 passed. Matching frozen full-suite evidence: 2757 passed; no production changes after that run. Final README-only contradictions were corrected at `106b852` and independently rechecked. No open findings; the accepted pre-existing Gemini thought-token cost limitation remains in the brief and CONTEXT. Local commits only; no push or live Provider/cache measurements.
