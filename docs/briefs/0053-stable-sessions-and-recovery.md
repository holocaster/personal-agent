# 0053: Stable sessions and file recovery

## Goal

Deliver all six priorities authorized by the user after the 2026-10-14 analysis: stable model selection, OpenRouter session affinity, a more stable prompt prefix, per-task/model cache reporting, recoverable file checkpoints, and deterministic offline prompt/schema snapshots. Execute through sdd-main with sequential implementation and independent review.

## Authorized scope

1. Remove scheduled evaluations at submissions 5 and 15 from normal operation. Preserve explicit manual model selection and an explicit one-shot re-evaluation. Maintain readable historical logs, submission identity, pending continuation, cancellation/fallback behavior and durable writes before dependent dispatch. Runtime Configuration changes remain explicit user choices.
2. Send a stable session affinity identifier to OpenRouter across ordinary turns, Tool follow-ups, retries and Resume. Distinguish auxiliary evaluator/compression requests where necessary so they do not compete with ordinary affinity. Preserve current host preferences. Affinity does not promise cache hits or cross-model reuse.
3. Put stable instructions before variable context and keep Tool ordering deterministic. Preserve immediate Memory changes, live Agent Mode gates, project-instruction reload, Skills, Todo, Compression and Provider replay. Improve reusable prefix without freezing legitimate state or claiming full-history reuse after system changes.
4. Extend the existing local `/report` with bounded per-task/model routing and cache observations around changes, using recorded evidence. Preserve unknown/partial coverage and distinguish reported from estimated cost. Correct cache token normalization and cache-aware direct-provider cost estimates where required for meaningful comparison. No model calls or metadata polling on the reporting path.
5. Persist before/after state for files touched by `write`, `edit` and `apply_patch`, covering creation and deletion. A separate local command recovers the latest routed task that changed files, leaving `/undo` Conversation-only. Offer preview and explicit confirmation before recovery; reject external edits/conflicts, unsafe paths and sensitive-file exclusions. Survive Resume, bound storage and preserve rollback/error handling. Shell side effects are outside the recovery guarantee.
6. Add deterministic reviewed fixtures of the production prompt plus Tool schemas for plan/build/auto using isolated fake configuration and workspaces. Preserve meaningful behavioral tests; fixtures contain no credentials, real user context or machine-dependent paths. Avoid extra runtime commands or model-family variants.

## Evidence and implementation reach

- Research: `docs/research/done/2026-10-14-cache-and-session-routing.md` and `docs/research/done/2026-10-14-reference-opportunities.md`; current official sources are linked there.
- Routing/persistence: `routing/session.py`, `routing/router.py`, `terminal/repl.py`, `call_log.py`, `routing/continuation.py`; ADR-0007 and spec 0041 define the historical policy that must remain replayable.
- Affinity and accounting: `providers/openrouter.py`, shared Provider contract/callers, `providers/http.py`, `providers/chat_completions.py`, `cost.py`, `session_report.py`, existing log metadata/diagnostics.
- Prefix and snapshots: `_build_system_prompt`, registry definitions, Provider input preparation, instruction/Memory/Skill/Todo integration and their existing behavioral tests.
- Recovery: `tools/workspace.py:PreparedChange/apply_change`, `tools/apply_patch.py:PreparedPatch/apply_patch_change`, `tools/registry.py` execution boundaries, safe project-scoped storage, local commands and Resume. Existing `/undo` removes Conversation only.
- Regression surface includes manual/automatic selection, old log replay, failed/cancelled tasks and retries, stream usage, provider-neutral budgets, write confirmation, live mode switching, path/symlink restrictions and partial-write recovery. Update concise user docs and canonical vocabulary when behavior changes.

## Decisions already authorized

- All six priorities are in scope; `/fork`, new MCP integrations, background jobs, dashboards, new dependencies, vendor SDK/API migrations, model benchmarks and native Claude cache activation are outside this delivery.
- Use the smallest complete implementation and validate increments. File recovery is independently risky and deserves its own review before subsequent work.
- On 2026-10-14 the user authorized local commits for this SDD flow after reviewing its brief. No paid API calls, sudo or pushes are authorized. This feature's local commit authorization includes documents, tickets, code, tests and review records.
- Keep pre-existing source changes intact. The only incoming untracked files are the two research reports produced in this conversation; preserve them.
- Planner owns spec, ADR amendments, persistence format, acceptance criteria, test seams, ticket granularity and blocking edges. Orchestrator owns brief, current glossary and state. Implementers run sequentially; reviewers independently check exact committed ranges and branch security.

## Settled discovery

1. Follow the recommended routing from the approved proposal: evaluate once before the first task, then only on explicit request; manual selection before the first task bypasses evaluation. Resume conserves the chosen tier and ends old scheduled checkpoints without discarding recorded history. Explicit re-evaluation keeps the existing monotonic keep/raise rule; only manual tier selection can lower it.
2. Follow the recommended recovery from the approved proposal: a separate local command restores files from the latest routed execution that changed files, with preview/confirmation; `/undo` keeps its Conversation-only semantics. Each explicit Retry is a separate execution under its original submission ordinal, and the preview identifies that boundary; earlier executions are outside the retained restore set. Protect later external edits and exclude shell effects. Recovery must handle actual successful file mutations from failed/interrupted executions as well as completed tasks, durably invalidating a matching saved continuation before restore so Retry cannot reuse undone Tool results.

No discovery questions remain. Ask only if planning exposes a genuine product/cost/data-loss decision not resolved by these obligations; routine command naming, bounds, schema and ticket slicing belong to the planner.

## Execution state

Full-path discovery and planning are complete on `feature/0053-stable-sessions-and-recovery`. Canonical spec and five independent tickets were committed by sdd-planner in `32107158e7974447e36de9de7c89390a96ce3165`. All six priorities map to 32 requirements. Implement and review sequentially in ticket order; file recovery remains isolated. Full baseline passed 2441 tests in 128.88s outside sandbox; socket/process permission failures inside sandbox were reproduced and resolved by test execution permissions without code changes. No paid verification.

User resumed on 2026-10-15. All five tickets are independently approved with BRANCH security and Standards/Spec evidence; ticket 05 closed its independently reproduced alias privacy finding at `0f5b674`, passed 485 independent regressions plus the original probe, and has matching full-suite evidence of 2757 tests. Review evidence is committed alongside each ticket. Independent final verification passed all six priorities and R1–R32: 756 fresh integration tests, matching full-suite evidence of 2757 passing tests, and approved security coverage for all six production commits. README-only contradictions were corrected and independently rechecked; no open findings. Canonical final evidence: `.ai/0053-feature-verification.json`.

## Delivery and known limitation (2026-10-15)

Ticket 04 is committed at `ba965838a3a1a36146dfd32062f3fcb934ed0475` with 2644 tests passing. After an automatic approval rejection, the user explicitly approved this commit and the remaining local feature commits on 2026-10-15 ("sim pode commit"). All isolated ticket reviews and final feature verification are approved; no implementation remains pending. Handoff: `.ai/0053-04-implementation-handoff.json`.

Accept and log, outside this cache feature: pre-existing Gemini output accounting uses only `candidatesTokenCount`, excluding separately reported `thoughtsTokenCount`. Baseline `9c8214d` and unchanged `test_gemini_empty_capped_response_preserves_termination_and_usage` establish the existing behavior; locked LiteLLM Gemini transformation adds reasoning when candidates are not inclusive. Existing Gemini estimates can therefore omit thought-token cost. No reasoning/output normalization change is added here; independent ticket 04 review confirmed cache-specific R19 compliance and reproduced this same pre-existing undercount on both base and head.
