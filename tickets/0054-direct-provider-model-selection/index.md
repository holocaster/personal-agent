# Tickets: 0054-direct-provider-model-selection

All three tickets are implemented and independently approved. The complete feature passed [final verification](feature.review.md). [Spec](../../docs/specs/0054-direct-provider-model-selection.md), [ADR-0011](../../docs/adrs/0011-direct-provider-model-selection.md), [ADR-0012](../../docs/adrs/0012-models-dev-selection-catalog.md).

| # | Title | Blocked by | Status |
| --- | --- | --- | --- |
| 01 | [Browse and refresh the local Models.dev catalog](01-browse-and-refresh-model-catalog.md) | none | done |
| 02 | [Run every Session on one configured direct pair](02-direct-route-cutover.md) | 01 | done |
| 03 | [Select, validate and size the pair from the catalog](03-catalog-validated-selection.md) | 02 | done |

Ticket 01 gives credential-free bounded catalog search/refresh without changing current routing. Ticket 02 removes tiers and the evaluator. Every Session then runs on the env-configured pair, and the Call Log v3, Resume, reports, discovery and recovery follow it. Ticket 03 adds in-session catalog-validated selection, refresh invalidation and Models.dev capacities. Each ticket ends working and fully green. Ticket 01's mentions of "ticket 02" as the catalog consumer now mean tickets 02-03; ticket 01 is intentionally unchanged.

Result: `PA_PROVIDER` + `PA_MODEL` + selected key; `/model <provider> <exact-model-id>` atomically saves the pair; `/models [provider] [query]` searches and `/models refresh` refreshes. Cache-first offline startup has no automatic expiry/request. Failed refresh keeps cache/settings. Successful refresh removing the current offering preserves the selected pair and running snapshot but blocks future dispatch with a local reason. Old Sessions are refused without migration/deletion.

## Seam choice (plan review 2026-10-15)

The brief suggested putting Call Log v3, Resume, reporting and recovery in the last ticket. The code does not allow that without shims:

- The v2 Call Log is defined by tier state. `session_start` carries `session_tier`, `routing_policy` and a per-Tier `tiers` map. Attempt records take a `tier`, Resume replay returns `SessionRouting`, and the REPL writes tier-change/migration records. Removing Tier while still writing v2 would need fabricated tier fields.
- In-Run behavior reads the log. Every task reads the latest execution through the version-gated reader. `/recover` derives a pre-Attempt route from `tiers.easy`, and `/report` and the `session_logs` Tool reject anything other than log_version 2 on line 1. So the writer and these readers must change together.
- Refusing Resume in between would break too much. Resume (`load_conversation`, `--resume`, `run_repl(resumed=...)`) seeds most Compression, context-recovery, file-recovery, Project Instructions and Skills tests. An interim refusal would delete that coverage in 02 and rebuild it in 03, which is more review, not less.

So the split is by selection capability instead. 02 is the forced Tier removal with persistence moved along. 03 is the catalog-dependent selection and limits, which build on 02's Runtime Configuration and ticket 01's catalog interface. The interim state (spec "Interim state after ticket 02"): restart-only pair changes, `/model` read-only, no in-session `/models`, no catalog admission or catalog limits yet.

## Original ticket 02 criteria mapping

Original ticket 02 (plan ddec366) had 12 criteria. Each atomic criterion lands in exactly one ticket:

| Original criterion | New ticket |
| --- | --- |
| 1 Runtime Configuration, PA_PROVIDER/PA_MODEL, selected key, TIER_* ignored | 02 |
| 2a Footer/piped behavior | 02 |
| 2b `/model`, `/models`, refresh, `/config`, help/completion; catalog+key validation, atomic save; refresh/removal blocking | 03 |
| 3 Evaluator/Tier deletion, one snapshot, Retry identity, preserved gates | 02 |
| 4 Per-field limits provenance and accounting semantics | 03 |
| 5 Strict log_version 3 and execution identity | 02 |
| 6 New-Session Resume/discovery and old-version refusal | 02 |
| 7 REST adapters and OpenRouter affinity | 02 |
| 8 Usage/report/audit/discovery route display and bounds | 02 |
| 9 Exact recovery and lineage | 02 |
| 10 Prompts/fixtures/agent features | 02 |
| 11a Matrix: first/5th/15th, changed-route Retry, Compression paths, version refusal, ordinal/execution identity, cache metrics, recovery faults/lineage | 02 |
| 11b Matrix: catalog invalidation, pair-save faults, limits/provenance, unknown pricing | 03 |
| 12a README/ENV_VARS/CLAUDE/pyproject/`.notebook` removal truth and stale tier/evaluator search | 02 |
| 12b Test guidance, research delivery status, Main CONTEXT/state coordination | 03 |

Each ticket's complete `.venv/bin/pytest` gate is a per-ticket requirement. It is not a split criterion. Ticket 02 adds interim command criteria (read-only `/model`, removed tier `/models`/`/config` editing). Ticket 03 adds startup admission (from spec R7) and a final stale-reference re-check.

Risks to validate: conservative unknown capability/schema handling, cache/pair atomic persistence, the broad 02 cutover, and retained Retry/recovery identity. Models.dev admission guarantees neither account access nor complete runtime compatibility. Main arranges final independent feature verification after ticket 03.

## Requirement coverage

| Requirements | Ticket |
| --- | --- |
| R1-R4: fixed Providers, admission/cache | 01; 03 integrates startup/dispatch |
| R5: explicit pair and credentials | 02 |
| R6-R7: commands/atomic settings, catalog changes | 03; 01 supplies listing/lookup |
| R8, R10-R12: one route, identity, v3, Resume | 02 |
| R9: immutable snapshots | 02 (configuration/instructions, Resume-changed pair); 03 (catalog capacities, in-session change) |
| R13: capacity and counting | 03 (02 keeps existing resolution unchanged) |
| R14-R16: Providers/accounting/prompts | 02 |
| R17-R18: recovery and contributor lineage | 02 |
| R19: docs/removal proof | 01 catalog CLI; 02 removal and current truth; 03 selection docs and research status |

Graph `01 -> 02 -> 03` is acyclic; all blockers exist. This index alone owns ticket status. Main owns CONTEXT/state and the approval checkpoint.
