status: approved
ticket: 0002-router-reliability/02
reviewed_range: 6e8db93df40919d8dad24c489e228751a82fbd1a..b5d3c552caa7635ffd0ea4045a359255e4c2962e
review_round: 2 (correction round; whole ticket range reviewed fresh)

## Criteria

All 12 acceptance criteria pass. Tier ladder is an explicit ordered sequence (`LADDER` tuple + `ladder_from()`) in `model_router/tier.py`, not enum order or a `next_tier` field. `route()` walks it, full Attempt budget per rung, returns on first success. Escalation triggers only on technical failure (grep for `reference_model_router`/`looks_unreliable`/content-heuristic terms: zero hits). Call Log `attempt` resets per tier. README accurate.

## Round-1 findings disposition

1. **blocking** (non-retryable failure escalated instead of terminating) - **fixed**, verified independently rather than taken on trust. `_attempt_tier` now returns `(answer, error, exhausted)` with `exhausted = error is not None and is_retryable(exc)`; `route()` returns immediately when `not exhausted`. Regression test confirms: HTTP 400 on an EASY-classified task produces exactly 1 request, `result.tier == Tier.EASY`. REPL test task order restored.
2. **suggestion** (loop-scope leak) - partially addressed (no longer reads from the `for`'s leaked scope), one wart remains - see finding 1 below.
3. **suggestion** (weak error assertions) - fixed. Exact error text and exact `Error:`-line count now asserted.

## New findings (all suggestions, non-blocking)

1. `model_router/router.py` `route()`: `result = None` before the loop, `return result` after - statically can return `None` (type checker would reject it), safe today only because `ladder_from()` is provably non-empty. Fragile once ticket 03 inserts a guardrail check between rungs. Required change: return success from inside the loop, construct the terminal failure result explicitly.
2. `model_router/router.py` `_attempt_tier()`: the retryability decision is expressed twice as exact complements (`break` condition inside the loop, `exhausted = ...` after it) - a future change to one must be mirrored in the other. Required change: derive `exhausted` from the loop's own exit condition (single statement of the rule).
3. Mixed chain (two retryable failures then a non-retryable one at the same tier) terminates at that tier rather than escalating - correct under the accepted round-1 reading, but untested and the README's "When a Complexity Tier's Attempts are exhausted, the task escalates" reads ambiguously for this case. Required change: add a test pinning this behavior; add a README clause. Explicitly flagged for ticket 03 (Budget Guardrail gates the same rung transition and inherits this semantics).

## Checks

- `uv run pytest -q`: 65 passed
- grep for content-heuristic terms: no hits
- Independent behavioural probe of the mixed retryable/non-retryable edge case, run outside the repo, nothing written to the working tree
- `git status --porcelain`: clean before and after

## Residual risks

- No test starts a task at the medium tier directly from classification (transitive coverage only) - carried over from round 1, not a ticket-02 criterion.
- Backoff-at-escalated-tier is structurally true via the shared `_attempt_tier` but unpinned by a dedicated test.
- `test_repl_shows_escalated_tier_and_continues_after_a_later_task_fails_entirely` asserts `'medium' in output`, satisfiable by the model ID string alone - weak but backed by stronger `test_routing.py` assertions.
