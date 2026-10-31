status: approved
ticket: 0002-router-reliability/01
reviewed_range: b11b015582b58f9cfe83126cfb3c790360364542..d6004bf59c75ed48fe9cc15f138d5567100a6116

## Criteria

All 12 acceptance criteria pass: retryability predicate, 3-Attempt loop with module-level backoff constants, backoff only between Attempts, `call_openrouter` unchanged, Call Log one-entry-per-Attempt with the new `attempt` key, unchanged failure/success contract for `route()`/REPL, `KeyboardInterrupt` propagation untouched, the `urlopen`-fake test seam plus the new replaceable clock seam, full test coverage of the retry/backoff/log scenarios, and README documentation.

## Two-axis review

- **Standards**: 0 hard violations. Layering preserved - `provider.py` gains only a pure predicate, the Router stays the sole owner of the Attempt/log chain, no new module or seam. The unused third `BACKOFF_SECONDS` value reads as Speculative Generality but is explicitly mandated by the spec, not a finding.
- **Spec**: 0 gaps, 0 scope creep, 0 incorrect implementations. Escalation, the Budget Guardrail, the tier ladder, and `ROUTER_BUDGET_USD` are entirely absent, correctly - no ticket 02/03 placeholder was smuggled in.

## Findings (non-blocking suggestions only)

1. `model_router/provider.py:12` - `is_retryable`'s docstring restates the function name; CLAUDE.md asks for no comments unless really necessary. Optional: drop it or replace with the one non-obvious fact (unrecognised exception types default to not-retryable on purpose).
2. `tests/test_call_log.py:105` vs `tests/test_routing.py` - the clock seam is patched by string in one file, by object in the other. Cosmetic; optional to unify.

## Notable correctness details

- `provider.py:13-17` checks `HTTPError` before `URLError` (HTTPError subclasses URLError) - a 400 would misclassify into the timeout branch under the reverse order.
- `router.py:42` catches `Exception`, not `BaseException` - this is what lets `KeyboardInterrupt` escape before `call_log.append_entry` runs, giving the interrupted Attempt no log line while completed ones keep theirs.
- Two pre-existing tests switched their stand-in exception from `TimeoutError` to `ValueError` (now that timeouts retry, a single-call assertion needs a non-retryable exception) - adaptation, not weakening.

## Residual risks

- `is_retryable` relies on `socket.timeout` being a `TimeoutError` alias (true from Python 3.10+; `pyproject.toml` pins `>=3.12`) - an implicit dependency on the version pin.
- Exception-shape-based retryability is fail-closed by design (spec's explicit choice) - a transient failure surfacing as an unrecognised exception type won't be retried.
- `install_fake_urlopen`'s `Repeat` wrapper only works in the trailing position of the scripted list; unenforced convention, documented in the fixture docstring.

## Checks

- `uv run pytest -q`: 59 passed
- `git diff b11b015..d6004bf --stat`: 10 files, +241/-36
- Range contains exactly one implementation commit, no bookkeeping inside it
- `git status --porcelain` after the review run: clean
