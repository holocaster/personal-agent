# Hand-rolled Provider Contract; bounded LiteLLM utility scope

Planned feature 0054 [ADR-0012](0012-models-dev-selection-catalog.md) amends capacity metadata precedence with Models.dev while preserving dispatch/tokenizer/cost boundaries. Pending plan review/delivery.

Adding Anthropic, OpenAI and Gemini as Providers meant either adopting a multi-provider calling library (LiteLLM was the obvious candidate — it was already being pulled in for `cost_per_token()`) or writing a small Provider Contract (`call()` + `is_retryable()`) and one `urllib`-based implementation per Provider, as `docs/CONTEXT.md` already did for OpenRouter. We chose the latter: each Provider stays a thin, dependency-free REST caller behind the same Contract, and `litellm` is imported for exactly one function (`cost_per_token()`), never its `completion()`/routing surface. Routing through LiteLLM would have meant handing it auth, retries and error mapping for all four Providers — more surface area to trust for a router whose whole job is that logic — in exchange for less code to write once. We picked owning the logic.

## Consequences

Adding a fifth Provider later means writing its `call()`/`is_retryable()` by hand again, not just registering a new model string with an existing library. Revisit only if hand-rolling a Provider becomes the actual bottleneck, not preemptively.

## Amendment (feature 0020)

Auto-Compress needs each model's context size to decide when to trigger. `litellm` already carries that data alongside its cost map, so it is looked up the same defensive way as `cost_per_token()`: `get_model_info(model).get("max_input_tokens")`, wrapped in `try`/`except Exception`, with a fixed fallback when it returns nothing usable. This is a second read-only metadata lookup, not a step toward `completion()`/routing — the "never call `completion()`, own the Provider logic" decision above is unchanged.

## Amendment (feature 0037)

The user additionally approved LiteLLM's local `token_counter()` for complete input estimates and explicitly rejected one-byte-per-token estimation. Reuse the installed dependency and locally available tokenizer assets; label generic tokenizer fallback as approximate and stop visibly if input cannot be measured. No paid counting requests or byte/character proxy fallback. REST payloads, auth, retries, error mapping and dispatch remain hand-rolled; LiteLLM's `completion()` and routing surface remain excluded. This extends utility scope, not the Provider calling architecture.
