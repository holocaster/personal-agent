status: approved
ticket: 0002-router-reliability/03
reviewed_range: 991fded60c3f07c868fa0d4b5d659b9d2da9249d..0a3549453bb46a74ce64074df5b911a75202758e

## Criteria

All 12 acceptance criteria pass. `budget.py` mirrors `tier_config.py`'s loader shape: `load()` reads `ROUTER_BUDGET_USD`, returns `None` when unset/empty, raises on an invalid value (same startup-error reporting as missing Tier Config vars). `BudgetGuardrail` accumulates every Attempt's cost (ignoring `None`) and is consulted only at the moment of Escalation - the Classifier's own tier always runs its full Attempt budget regardless of guardrail state. A block returns the failed tier's own `RouteResult` with `error="budget exceeded, not escalating to {tier}"`, no new field, no Call Log entry. README documents it as optional, per-session, Escalation-only.

## Verification of the two carried-over ticket-02 points (explicitly checked)

1. **`result = None` / `return result` refactor**: sound and behavior-preserving. The reviewer walked all six paths through `route()` against the pre-diff version - identical observable behavior outside the new guardrail branch, corroborated by every ticket 01/02 escalation and REPL test passing unmodified.
2. **`_attempt_tier`'s retryability/exhausted duplication left untouched**: accurate, not scope-avoidance. The only changes to that function are the `budget` parameter and a two-line `record()` call before the Call Log write; the break/exhausted lines appear only as diff context. Touching them would have meant restructuring retry logic inside a ticket whose criteria say nothing about it - correctly left as an open ticket-02 suggestion.

## Findings (all suggestions, non-blocking)

1. `model_router/budget.py:21-35` (`load`) - `ROUTER_BUDGET_USD=nan` or `=inf` passes startup validation (`nan <= 0` is `False`) and produces a guardrail that silently always-blocks (`nan`) or never-blocks (`inf`) - the mirror of the typo'd-budget-changes-behavior-silently failure the ticket and spec forbid. Low real-world likelihood; fails toward "still answers at the classified tier," hence suggestion. Required change: reject non-finite values (`not math.isfinite(limit)`), extend the existing invalid-value test with `nan`/`inf`.
2. `model_router/router.py:51` - the post-loop `return RouteResult(...)` still reads the for-loop's leaked variables; correct only because `ladder_from()` is never empty, unguarded. Required change (optional): return the exhausted-top-tier result from inside the loop under the existing `is_top_tier` branch.
3. `tests/test_repl.py` / `tests/test_routing.py` - cross-task cost accumulation (criterion 10) is proved via direct `route()` calls sharing one guardrail; the only `run_repl` test drives a single task. Required change (optional): drive the accumulation scenario through `run_repl` with two tasks so the session-spanning object is asserted at the REPL entry point.

## Checks

- `pytest -q`: 87 passed (includes every ticket 01/02 test, unmodified in this diff)
- Manual probe of `budget.load()` numeric edge cases (`nan`/`inf`/`1_0`/whitespace)
- `git status --porcelain`: clean after all checks
- Range contains exactly one implementation commit, no bookkeeping inside it

## Residual risks

- Accumulated cost depends on the Provider reporting a numeric `cost`; a non-numeric value raises `TypeError` inside `record()` - spec-conformant (null-safe only), not a finding.
- **Handoff transcription error caught during orchestration**: the implementer's reported `head_sha` (`0a354942bf3898faf60d0d0f45e7c6a67d43d97a`) did not resolve; the real commit is `0a3549453bb46a74ce64074df5b911a75202758e` (same short prefix, diverges after). Verified against `git log`/`git rev-parse` before recording this approval; `PROJECT_STATE.md` corrected to the real value.
