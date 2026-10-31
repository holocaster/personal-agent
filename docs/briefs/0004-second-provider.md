# 0004 — Second provider

## Goal

The Router today calls exactly one Provider — `provider.call_openrouter()`, imported directly by `router.py`. This feature adds Anthropic, OpenAI and Gemini as three more Providers, each Complexity Tier picking its own independently, so the Router isn't locked to a single upstream and can route cheaper tiers to whichever Provider is cheapest or most reliable for them.

## Scope

- **Provider Contract**: a common shape (`call(model, system, messages) -> (answer, usage)` + `is_retryable(exc)`) implemented by all four Providers. `router.py` dispatches through it instead of importing `call_openrouter` directly.
- **Anthropic, OpenAI, Gemini**: each a thin `urllib`-based REST caller, no vendor SDKs — same style as the existing OpenRouter implementation.
- **Per-Tier Provider selection**: `TIER_<TIER>_PROVIDER` env var alongside the existing `TIER_<TIER>_MODEL`, one pair per Complexity Tier. Unset `TIER_<TIER>_PROVIDER` defaults to `openrouter` — an existing `.env` with only `TIER_*_MODEL` set keeps working unchanged.
- **API keys**: one env var per Provider (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, existing `OPENROUTER_API_KEY`). `tier_config.validate()` requires only the key(s) for Provider(s) actually referenced by a configured `TIER_<TIER>_PROVIDER` — not all four unconditionally.
- **Estimated Cost**: OpenRouter keeps returning real `cost`. The other three don't, so their `cost` is computed from `prompt_tokens`/`completion_tokens` via `litellm.cost_per_token()` — `litellm` is a new dependency, but only that one function is used (see ADR-0002). Every Call Log entry gains `cost_estimated: bool`; `true` for the three new Providers, `false` for OpenRouter.
- **Call Log**: gains a `provider` field (existing `model` field alone no longer identifies which Provider handled an Attempt).
- **Config validation**: an unrecognized `TIER_<TIER>_PROVIDER` value is a validation error, same class as a missing required env var today.

## Out of scope

- **Local CLI Providers** (`claude exec` / `codex exec` authenticated via the user's own subscription instead of an API key): investigated, technically legitimate (official headless modes, not the session-token workaround Anthropic blocked in April 2026), but a materially different shape — full coding agents with tool access rather than plain completion endpoints, and their reported cost is an unbilled client-side estimate, not a real charge. Deferred to a possible future feature. See `docs/CONTEXT.md` Decisions.
- Any other consumer-subscription-based Provider auth — confirmed unsupported by any of the three vendors (see `docs/CONTEXT.md` Decisions).
- Provider-level fallback/retry across Providers within one Tier (each Tier still resolves to exactly one Provider; Escalation moving to a higher Tier may incidentally change Provider, but that's a consequence of per-Tier selection, not a new retry mechanism).
- A price table maintained by hand, or any cost-tracking precision guarantee for the three new Providers — `cost_estimated: true` documents the limitation instead of solving it.

## Settled decisions

See `docs/CONTEXT.md` (`Provider`, `Provider Contract`, `Tier Config`, `Estimated Cost` glossary entries and the Decisions bullets on Provider scope, subscription auth, LiteLLM scope, and required API keys) and `docs/adrs/0002-hand-rolled-provider-contract.md`.

## Open questions

None — grilling frontier closed and confirmed by the user.
