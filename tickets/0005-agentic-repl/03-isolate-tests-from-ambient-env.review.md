# Review: ticket 0005-agentic-repl/03

## Round 1: changes_requested

status: changes_requested
reviewed_range: 58517fa055630043b9f3e4844ad0e3e974fe2161..52e148de9494f32465df6d15bd8231364c4c6de1

7 of 8 criteria passed. Failed: "isolation is automatic, not opt-in;
clearing happens before each test body so no real secret can reach a
pytest assertion diff." `litellm`'s own import-time dotenv auto-load
still read the repo-root `.env` and wrote real values into `os.environ`
*during* a test body (traced landing mid-run in
`tests/test_call_log.py`), independent of the `model_router/__main__.py`
relative-read path that round 1's fix (`_isolate_cwd` chdir) already
closed. The implementer's own deviation note — that the ticket's litellm
root cause was inaccurate — was itself wrong: both leak paths were real,
only one was fixed.

Required change (reviewer-verified): `monkeypatch.setenv("LITELLM_MODE",
"PROD")` as the first line of `_isolate_router_env`, since
`litellm/__init__.py:29` guards its `load_dotenv` call on
`os.getenv("LITELLM_MODE", "DEV") == "DEV"`.

## Round 2 (correction): approved

status: approved
reviewed_range: 58517fa055630043b9f3e4844ad0e3e974fe2161..0b9d5c2a448e72fe767a58b644cf00959914ee4e

All 8 acceptance criteria pass. The correction adds
`monkeypatch.setenv("LITELLM_MODE", "PROD")` to `_isolate_router_env`
and extends both isolation fixtures' docstrings to document both leak
paths. The fix was independently verified with an `os.environ` tracer
(pytest plugin patching `__setitem__`), reproducing round 1's leak as a
positive control (4 dotenv-sourced writes at `52e148d`) and confirming
it drops to 0 at `0b9d5c2` while litellm is still genuinely imported
with `LITELLM_MODE='PROD'` in place — the zero is caused by the guard,
not by litellm never loading. Verified with the real `.env` present, with
it moved aside, with hostile ambient env exported, in reversed file
order, and with each test file run in isolation: 160 passed / 0
dotenv-sourced writes in every configuration.

### Findings (all suggestions, none blocking)

- `LITELLM_MODE=PROD` is set inside a function-scoped fixture; if
  litellm is ever imported before any fixture runs (module-level import,
  an early pytest plugin/hook), the guard evaluates too late and the
  leak silently returns. Not the case today (verified). Optional
  hardening: also `os.environ.setdefault("LITELLM_MODE", "PROD")` at
  conftest module level.
- No regression test pins the fix to litellm's current `LITELLM_MODE`
  behavior; if a future litellm release drops/renames that guard,
  isolation regresses silently until a real value happens to collide
  with an assertion. Optional: one test calling `cost.estimate()` and
  asserting no `_ROUTER_ENV_VARS` name reappears in `os.environ`
  afterwards.
- Carried over from round 1, non-blocking: provider modules hardcode
  their API key env var names as string literals rather than reading
  `tier_config`'s map, so a future provider could add a key that escapes
  isolation. Accept the drift risk knowingly, or have providers read the
  name from `tier_config`'s map.

### Residual risk (informational)

Repo-root `.env` holds live provider keys; round 1 proved pytest echoed
`OPENAI_API_KEY` into an assertion diff before this fix, in a throwaway
worktree, never committed or logged. After this fix the leak path is
closed for the offline suite. User has already confirmed this is an
accepted risk (low spend cap, keys rotated freely).
