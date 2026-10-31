# Review: 01-repl-routes-task-to-tier-model

- **ticket**: 01-repl-routes-task-to-tier-model (feature 0001-model-router)
- **reviewed_range**: 95630da84c98ac8cdef0eb361bfa21186214109f..2cd6764c18e8a1cf15eac265ae4f5d725da7064f
- **verdict**: approved

## Criteria (11/11 pass)

All acceptance criteria verified: Tier enum, Classifier (pure, ordered rules, module-level signal constant), Tier Config (env-driven, no hardcoded model IDs), Provider call (plain function, urllib, defensive usage parsing), Router, REPL (injectable streams, blank-line skip, exit/quit/EOF), the full test suite (classifier unit tests, single urlopen-seam routing tests, REPL scripted-input tests), and the README's placeholder-labelled env var block.

## Findings (all suggestion-level, non-blocking)

1. `tier_config.load(env=...)` parameter and `TierConfig.api_key` are unused/inert in this range (the live key path is `os.environ` inside `provider.py`); the two would disagree if `env` were ever passed. Deferred to ticket 03, which consumes `api_key` for validation — not a defect now, but drop the unused param if ticket 03 doesn't end up needing it.
2. `_install_fake_urlopen` is duplicated across `test_repl.py` and `test_routing.py` instead of living once in `conftest.py`. Promote to a shared fixture before ticket 02 adds a third caller.
3. Test modules `import ... from tests.conftest` — works today via `tests/__init__.py` but is brittle (conftest is pytest's plugin-discovery file, not meant to be imported as a library). Move `FakeOpenRouterResponse` to `tests/fakes.py`.
4. `EXIT_COMMANDS` check on the REPL is case-sensitive (`Exit`/`QUIT` get routed as tasks instead of exiting). Not a spec violation — spec only names lowercase `exit`/`quit` — owner's call whether to `.lower()` it.
5. (Scoped to ticket 02, not this ticket) The outgoing request body carries only `model`+`messages`, no usage/cost opt-in. If OpenRouter requires an explicit opt-in for per-call cost, `cost` will be `null` on every Call Log line. Confirm against a live response during ticket 02 and record the answer in the spec.

## Checks

- `uv run pytest -q` → 19 passed, no skips/warnings.
- Range contains exactly one implementation commit (`2cd6764`); no `.ai/**` or `tickets/**` bookkeeping in range.
- `python -m model_router </dev/null` with all env vars unset exits 0 (EOF path) — fail-fast validation correctly absent (ticket 03's job).
- No hardcoded model ID literal anywhere in `model_router/` (grep-verified).
- Zero runtime dependencies (`pyproject.toml` `dependencies = []`); `pytest` is the only dev dependency.
- Defensive usage-parsing probed across 9 synthetic response shapes (absent/null/empty/nested/top-level cost, unknown fields) — all degrade to `None`, no exception, per the spec's "read defensively" decision. Only a non-mapping `usage` (never returned by any real chat-completions API) would raise, and ticket 03's Router-level catch absorbs that anyway.
- REPL output manually verified against a fake `urlopen`: one routing line + one answer per task, blank line produces zero calls, `exit` terminates.
- Test seam conformance: only `provider.urlopen` is patched; no mocking of Classifier/Tier Config/Router.
- Working tree left clean by the reviewer.

## Residual risks (not blocking)

- OpenRouter's live cost/usage shape is still unverified (no network/API key in this environment) — parsing is proven safe for every realistic shape, but completeness of cost data is ticket 02's open question.
- REPL test asserts substrings/call counts rather than exact output string; reviewer closed the gap by direct manual observation instead of raising it as a finding.
