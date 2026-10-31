# Review: 0037/04

status: approved
ticket: 0037/04
base_sha: 24f7300b80fc0fccb805c3b97a5a013d60f2822b
head_sha: 4d7efe424b5559cbc320c300fb522a3506638418
reviewed_range: 24f7300b80fc0fccb805c3b97a5a013d60f2822b..4d7efe424b5559cbc320c300fb522a3506638418

## Criteria

- AC1 narrow four-Provider taxonomy, once-only HTTP evidence and negatives: pass.
- AC2 one strictly reduced same-route retry, separate transient allowance and terminal failures: pass.
- AC3 protected context/Tools, once-only execution, sequential Attempts, truthful outcomes, replay and audit: pass.
- AC4 truthful snapshots and accounting of rejected/recovery/summarization Attempts: pass.
- AC5 documentation/help/settings/arithmetic/counting/retry semantics: pass.
- AC6 integration/offline counting/full suite and coverage matrix, excluding ticket 05 obligations: pass.

## Findings

None in scope. Both previous findings are resolved: choice-level errors reject partial answers/Tools, and available normalized usage survives failed Attempts without double-counting. Standards and ADR-0001/0002/0005 passed; existing seams reused, no dependencies or speculative abstractions added.

## Independent evidence

- Exact SHAs resolve; tested HEAD `949b70432e6180b4797069e74d2c13c6f6bc4ef4` differs from implementation head only in `.ai/PROJECT_STATE.md`.
- `uv run --offline pytest -q tests/test_context_recovery.py::test_usage_bearing_recovery_rejections_are_charged_once tests/test_context_recovery.py::test_provider_failures_preserve_normalized_usage tests/test_compression.py::test_failed_summary_attempts_retain_reported_usage`: 78 passed in 3.95s.
- `uv run --offline pytest -q tests/test_context_budget.py tests/test_compression.py tests/test_preventive_compression.py tests/test_context_overflow.py tests/test_context_recovery.py tests/test_runtime_config.py tests/test_tier_config.py tests/test_provider.py tests/test_routing.py tests/test_call_log.py tests/test_detailed_audit.py tests/test_budget.py`: 605 passed in 24.59s.
- `uv run --offline pytest -q tests/test_context_budget.py::test_real_locked_counter_is_offline_repeatable_and_counts_tokens tests/test_context_recovery.py::test_real_offline_recovery_preserves_gemini_parts_and_one_mutating_apply`: 6 passed in 13.20s; local assets/custom caches, network denial, exact Gemini replay/signatures and once-only apply.
- `uv run --offline pytest -q`: 1599 passed in 82.92s.
- Independent Provider-to-REPL probe with real local estimator/socket-DNS denial: rejection costs 0.3 and 0.2 plus summary 0.1 yielded spend 0.6; failed counters input 111/completion 7 retained, Attempts [1,2], no partial outputs/Tools accepted. Later ordinary transient Attempts still dispatched and Budget Guardrail blocked only Escalation; final spend 0.75. Resume preserved committed Compression without failed turns. Zero network attempts/Tool executions.
- Official OpenRouter Usage Accounting and error formats, Anthropic cache-inclusive input and Google v1beta usageMetadata source verified.
- Exact-range diff check passed; final tree clean, no reviewer edits/commits.

## Out-of-scope finding

The pre-existing Anthropic `model_context_window_exceeded` summary defect remains formally owned by `0037/05`, not this verdict. The review previously proved an unfinished summary could be committed by manual Compression. Ticket 05 must reject it through shared termination validation and verify manual/preventive/recovery preservation before final feature review.

## Route

Mark 0037/04 done, implement and independently review 0037/05, then obtain final feature review. No paid live Provider calls; local estimates remain approximate. This ticket approval does not declare the feature complete.
