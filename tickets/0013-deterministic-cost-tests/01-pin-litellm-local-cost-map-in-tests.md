# 01: Pin litellm's bundled cost map in tests

**What to build:** The offline test suite no longer depends on the network or
on litellm's live remote pricing table. Tests always price models from the
cost map bundled with the installed litellm version.

**Blocked by:** None (can start immediately).

**Spec:** none (fast path); **ADRs:** none.

**Root cause (proven):** `tests/conftest.py::_isolate_router_env` sets
`LITELLM_MODE=PROD`, so litellm does not auto-load the repo `.env`, which is
the only place `LITELLM_LOCAL_MODEL_COST_MAP` is set. Without that variable,
litellm fetches the remote cost map at import time. The current remote map no
longer contains the retired `claude-3-haiku-20240307`, while the bundled map
(litellm 1.102.0) does. As a result,
`test_call_anthropic_uses_messages_shape_and_normalizes_usage` and
`test_estimate_uses_real_litellm_pricing_and_tolerates_unknown_models` get
`cost None`.
Evidence: run from `/tmp`, the remote map gives `"claude-3-haiku-20240307" in
model_cost == False`. With `LITELLM_LOCAL_MODEL_COST_MAP=True` it is `True`,
and `cost_per_token` returns a float.

- [x] `_isolate_router_env` also sets `LITELLM_LOCAL_MODEL_COST_MAP` to the
  value litellm checks for (verify the exact comparison in the installed
  litellm), before any test body can import litellm. Extend the docstring in
  the same style.
- [x] No production code change and no change to the two tests' model ids.
- [x] The full suite passes with 0 failures.
