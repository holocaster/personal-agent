# Review: 02-call-log-jsonl

- **ticket**: 02-call-log-jsonl (feature 0001-model-router)
- **reviewed_range**: 7d76ea60f32b33b40556cb829c8e7a883a32227e..f7a4e9c6864c393836b40ea32aa11be3f78e32dc
- **verdict**: approved

## Criteria (8/8 pass)

Call Log appends one JSON line per call (append mode, created on demand); line carries timestamp/task/tier/model/latency_ms/cost/prompt_tokens/completion_tokens/ok/error; `latency_ms` brackets only the Provider call via a monotonic clock; absent usage fields degrade to `null`, never raise; path from `ROUTER_LOG_PATH` defaulting to `./router_log.jsonl`, gitignored, documented as optional; Router logs every call without changing REPL output; tests assert the file artifact directly and keep the single `urlopen` seam.

## Findings (all suggestion-level, non-blocking)

1. The default-path branch of `_log_path()` (no `ROUTER_LOG_PATH` set) is never exercised by the suite — the autouse isolation fixture sets it for all 22 tests. Reviewer verified the default manually; a regression there would still pass CI. Optional: one test that unsets the env var and asserts the default filename.
2. `test_response_missing_usage_...` is effectively a second copy of the happy-path test, since the shared fake can never emit a `usage` object — it doesn't control its own precondition. Optional: let the fixture accept a payload/usage override so a sibling test can assert a *present* cost reaches the log line.
3. All three `test_call_log.py` tests re-set `ROUTER_LOG_PATH` to the same value the autouse fixture already sets — a no-op repeated three times. Optional cleanup.
4. `call_log.append_entry`'s three usage fields (cost/prompt_tokens/completion_tokens) are a data clump unpacked from a dict in `router.py` only to be reassembled — ticket 03 adds a second 9-arg call site. Optional: take a `usage: dict` param instead.
5. `install_fake_urlopen` couldn't absorb `test_provider.py`'s three inline fakes (they need payload shapes the fixture can't express yet). Optional follow-up if that file gets touched again.

## Checks

- `uv run pytest -q` → 22 passed, no skips/warnings.
- Working-tree pollution fix verified: no `router_log.jsonl` in repo root before/after a full suite run; `git status --porcelain` empty afterward.
- Production default verified directly (not via tests): unsetting `ROUTER_LOG_PATH` makes `_log_path()` resolve to `./router_log.jsonl` and two `append_entry` calls correctly create-then-append.
- Timestamp format verified: ISO 8601 UTC with `Z` suffix, round-trips through `datetime.fromisoformat`.
- `git check-ignore -v router_log.jsonl` confirms the default path is gitignored.
- Both ticket-01 review follow-ups confirmed folded in: `FakeOpenRouterResponse` now lives in `tests/fakes.py` (zero remaining `tests.conftest` imports); the duplicated `_install_fake_urlopen` replaced by one shared `install_fake_urlopen` fixture used by `test_repl.py`, `test_routing.py`, and the new `test_call_log.py`.
- Seam discipline holds: `provider.urlopen` remains the only patched call in the whole suite.
- Defensive parsing degrades safely regardless of OpenRouter's actual usage-accounting behavior — verified directly in code, not just asserted from the implementer's doc claim.
- `repl.py` untouched in this range — REPL output contract unchanged, as required.

## Residual risks (not blocking)

- OpenRouter's "usage always included, no opt-in needed" claim comes from the implementer reading OpenRouter's published docs (no live API key available in this environment to confirm against a real response). The code-level half of the criterion — tolerating absence either way — is verified directly. First live call with a real key should be checked for a non-null `cost`.
- `docs/specs/0001-model-router.md` was edited inside this implementation ticket (an additive Further Note, sanctioned by ticket 01's review) — worth the owner's eye since normative-doc edits inside implementation tickets are unusual.
