# 03: OpenAI and Gemini as the third and fourth Providers

**What to build:** the last two Providers, so the user can point any Complexity Tier at `openai` or `gemini` with that vendor's own model ID and API key and get an answer, with retry, Escalation, the Budget Guardrail and Estimated Cost behaving as they already do for Anthropic. After this, all four names in the brief are reachable, any mix across the three tiers works, and a user holding one vendor's key still needs only that key. The two Providers are one ticket because the machinery they plug into is finished: each is a module, a registry line, its own tests and a README line — the only genuinely new thing is Gemini's shape, which puts the model in the URL path, the system prompt in its own field and the token counts under its own metadata object.

**Blocked by:** 02 (both Providers are estimating Providers — they need the cost module, the `cost_estimated` convention and the `litellm` dependency introduced there, and OpenAI's tests reuse the per-Provider patterns 02 establishes).

**Spec:** `docs/specs/0004-second-provider.md` — Solution; Implementation Decisions (Per-Provider specifics; Usage normalisation; Retryable codes per Provider; Pricing model names); Testing Decisions (One seam, still; Coverage). **ADRs:** `docs/adrs/0002-hand-rolled-provider-contract.md`.

- [x] An OpenAI Provider module and a Gemini Provider module each implement the Contract as thin `urllib` callers through the shared HTTP helper — no vendor SDKs, no `litellm.completion()` — registered under `openai` and `gemini`.
- [x] Each one's request and response shape is confirmed against that vendor's current official API documentation (Context7) before its parser is written. Known specifics to honour: OpenAI's chat-completions endpoint with a bearer header and the same response shape OpenRouter uses; Gemini's generate-content endpoint with the model in the URL path, its key header, the system prompt as a dedicated instruction field, its `model` role where the others say `assistant`, the answer read from the first candidate's first part, and token counts under its usage-metadata object.
- [x] Both normalise usage into `cost`, `prompt_tokens`, `completion_tokens` plus `cost_estimated: true`, with the cost coming from the cost module. No vendor field name reaches the Router.
- [x] Each states its own retryable code set explicitly; neither inherits a shared mutable one.
- [x] Each owns the pricing-qualified model string it hands the estimator: OpenAI's is the raw model ID, Gemini's carries the prefix `litellm` requires for Google models.
- [x] Validation requires `OPENAI_API_KEY` and `GEMINI_API_KEY` only when a tier references that Provider; a setup using one of them needs only that one key, and a setup mixing three Providers across the three tiers requires exactly those three.
- [x] Both names appear in the accepted-names list that an unrecognised `TIER_<TIER>_PROVIDER` error reports.
- [x] Tests through the existing `urlopen` seam assert, per Provider, the URL (including Gemini's model in the path), the auth header, the request body and the parse of that vendor's response into `(answer, usage)`; a response missing usage fields yields `None` for them rather than raising. Retryability is unit-tested per Provider.
- [x] A test asserts a three-Provider configuration — a different Provider on each tier — where an Escalation walks all three rungs and the requests reach three different hosts in ladder order.
- [x] A Call Log test asserts `provider` and `cost_estimated: true` on OpenAI and Gemini entries with a cost derived from the reported token counts.
- [x] The README lists all four accepted Provider names with their key variables, and shows a short example of a mixed-Provider tier configuration.
