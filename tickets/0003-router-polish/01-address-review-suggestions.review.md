status: approved
ticket: 0003-router-polish/01
reviewed_range: a7793012b0ada3daacb976556a54b0d647674196..f7fcd6a36e09142fea31f88f51afb194bb4bf16e

## Criteria

All 8 checklist items pass, verified against both the required change and the originating review's stated impact - not just wording match. Item 3's `_attempt_tier` refactor confirmed logically identical to the old code (De Morgan complement), strictly safer at the `MAX_ATTEMPTS==0` edge. Item 5's `route()` refactor confirmed behavior-preserving: identical `RouteResult` from identical values, escalation/budget-guardrail ordering between rungs unchanged. All 91 tests pass, including every prior correction-round regression test.

## Findings (all suggestions, non-blocking)

1. `model_router/router.py` `route()`: item 5's literal required change was made, but the underlying wart is traded for a new form - the function's last statement is now the `for` loop with no trailing return, so it's implicitly `-> RouteResult | None` to a type checker (none configured in this repo). Unreachable today only because `ladder_from()` is never empty.
2. `model_router/router.py` (~38-43): the two early returns construct byte-identical `RouteResult(...)` five lines apart - could merge into one guarded return.
3. `model_router/router.py` `_attempt_tier()`: docstring still says "Returns (answer, error, exhausted)" but the variable is now `retryable_failure` - align the name or the docstring.
4. `README.md` (~73-79): the inserted clause reflowed the paragraph unevenly (a short line breaks mid-clause) vs. the rest of the file's wrap width.

## Checks

- `uv run pytest -q`: 91 passed
- Range contains exactly one implementation commit, no bookkeeping inside it
- Verified item 3 and item 5's refactors line-by-line against the pre-diff logic (see reviewer's detailed trace)
- grep confirms item 2 applied to all 20 `_sleep` patch sites, not just the two files named in the original finding
- `git status --porcelain`: clean before and after

## Residual risks

- No linter/type checker configured (pytest-only dev deps) - the implicit-`None` path in `route()` won't be tooling-caught if the ladder ever becomes conditionally empty.
- Items 1 and 4 are prose judged by reading, not automated check.
