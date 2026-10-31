# 0004 - Second provider

Brief: `docs/briefs/0004-second-provider.md`
Glossary and cross-cutting decisions: `docs/CONTEXT.md`
ADRs: `docs/adrs/0002-hand-rolled-provider-contract.md` (constrains the whole feature), `docs/adrs/0001-escalate-on-technical-failure-only.md` (unchanged by it)

## Problem Statement

Every task the Router runs goes to OpenRouter. The Router imports one function, `call_openrouter`, directly; Tier Config maps a Complexity Tier to a model ID and nothing else. So the user's three tiers are three model IDs on one upstream, and the user has no way to say "run `easy` on the cheapest thing I have direct billing for, and keep `complex` on OpenRouter".

That costs the user three things. Price: the same model is often cheaper billed directly by its vendor than resold, and the cheap tiers are the ones that run most often. Reliability: when OpenRouter has a bad hour, every tier has a bad hour, and Escalation — the feature built precisely so one failing endpoint does not lose a task — just walks up three rungs of the same ladder into the same outage. Reach: a model that a vendor exposes on its own API but OpenRouter has not listed is simply unreachable.

There is also a smaller, already-present annoyance: the Call Log records `model`, which today implies the Provider because there is only one. The moment there are four, a reader of the log — or of the REPL's routing line — cannot tell which upstream actually answered.

## Solution

Each Complexity Tier picks its own Provider, independently, from four: OpenRouter (today's), Anthropic, OpenAI, Gemini. The user sets one new optional environment variable per tier alongside the model ID:

```bash
export TIER_EASY_PROVIDER="anthropic"
export TIER_EASY_MODEL="claude-haiku-4-5"
export TIER_MEDIUM_MODEL="vendor/some-openrouter-model"   # no TIER_MEDIUM_PROVIDER -> openrouter
```

`TIER_<TIER>_PROVIDER` unset means `openrouter`, so an existing `.env` that only sets `TIER_*_MODEL` keeps working with no edit and no behaviour change at all.

Each Provider authenticates with its own API key from its own environment variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, and today's `OPENROUTER_API_KEY`). Startup validation asks only for the keys of the Providers the user's tiers actually reference: a setup that routes everything to Anthropic needs `ANTHROPIC_API_KEY` and nothing else. A `TIER_<TIER>_PROVIDER` naming a Provider that does not exist is a startup error in the same class as a missing model ID — reported before the first prompt, never discovered after the user has typed a task.

Behind that, the Router stops knowing OpenRouter exists. It looks the tier's Provider up by name and calls it through the Provider Contract — `call(model, system, messages) -> (answer, usage)` plus `is_retryable(exc)` — so retry, Escalation and the Budget Guardrail work exactly as they do today, on whichever Provider the tier resolved to. Escalation that crosses Providers is not a new mechanism; it is what per-tier selection already means when `easy` is Anthropic and `medium` is OpenRouter.

Cost is the one place the four Providers are not interchangeable. OpenRouter reports real billed cost on the response; the other three report token counts only. For those, the cost written to the Call Log and fed to the Budget Guardrail is computed from the token counts via `litellm.cost_per_token()`, and the entry is marked `cost_estimated: true` so nobody later reads an estimate as a bill. OpenRouter entries carry `cost_estimated: false`. The Call Log also gains `provider`, and the REPL's routing line names the Provider next to the model, because `model` alone no longer says who answered.

## User Stories

1. As a terminal user, I want each Complexity Tier to choose its own Provider, so that I can put my cheap tier on the upstream that is cheapest for it without moving my expensive tier off the one I trust.
2. As a terminal user, I want `TIER_<TIER>_PROVIDER` to default to `openrouter` when unset, so that my existing `.env` keeps working unchanged after I upgrade.
3. As a terminal user, I want a setup with no `TIER_*_PROVIDER` variables at all to behave byte-for-byte like today, so that adopting this feature costs me nothing until I opt in.
4. As a terminal user, I want to route `easy` to Anthropic, so that I can bill the tier that runs most often directly to the vendor instead of through a reseller.
5. As a terminal user, I want to route a tier to OpenAI, so that I can reach OpenAI models on my own OpenAI billing.
6. As a terminal user, I want to route a tier to Gemini, so that I can reach Google's models on my own Google billing.
7. As a terminal user, I want to mix Providers across tiers freely, so that no combination of the four is forbidden by the tool.
8. As a terminal user, I want to point two different tiers at the same Provider with different models, so that "one Provider per tier" never means "one tier per Provider".
9. As a terminal user, I want each Provider to read its own API key from its own environment variable, so that I can hold keys for only the vendors I actually use.
10. As a terminal user, I want startup validation to require only the API keys of Providers my tiers reference, so that using one Provider does not force me to invent three unused keys.
11. As a terminal user, I want a missing API key for a Provider I *do* reference to be reported at startup naming that variable, so that I fix it before typing a task rather than after losing one.
12. As a terminal user, I want an unrecognised `TIER_<TIER>_PROVIDER` value to be a startup error naming the variable, the bad value and the accepted names, so that a typo like `antropic` tells me what to type instead of failing mysteriously on the first call.
13. As a terminal user, I want an unrecognised Provider name to fail at startup even for a tier I never reach in that session, so that a latent typo in my `complex` tier does not ambush me during an Escalation an hour later.
14. As a terminal user, I want all configuration problems reported together in one message, so that I fix them in one pass instead of one restart per mistake.
15. As a terminal user, I want `TIER_<TIER>_PROVIDER` to be case-insensitive and tolerant of surrounding whitespace, so that `Anthropic` or a stray trailing space is not a startup error.
16. As a terminal user, I want an empty `TIER_<TIER>_PROVIDER` to mean the same as unset, so that commenting a value out of my `.env` by blanking it does what I expect.
17. As a terminal user, I want retry to work identically on every Provider, so that reliability does not depend on which upstream a tier happens to use.
18. As a terminal user, I want each Provider's own transient-failure vocabulary respected — including Anthropic's overloaded response — so that a retryable failure on one Provider is not mistaken for a permanent one because it does not match another Provider's error codes.
19. As a terminal user, I want a bad API key on any Provider to fail immediately without burning the other two Attempts, so that an auth mistake is reported in a second, not in four.
20. As a terminal user, I want Escalation to work across Providers, so that a tier on a Provider having a bad hour escalates into a different upstream entirely and my task survives an outage that would have killed it before.
21. As a terminal user, I want Escalation still triggered only by technical failure, so that adding Providers does not smuggle in a content-quality judgment (ADR-0001).
22. As a terminal user, I want the Budget Guardrail to keep gating Escalation exactly as today regardless of Providers involved, so that a cross-Provider chain is still bounded by the ceiling I set.
23. As a terminal user, I want the REPL's routing line to name the Provider as well as the tier and model, so that I can see which upstream answered without opening the log.
24. As a terminal user, I want the failure path unchanged — one readable `Error:` line and back to the prompt — so that nothing about my failure experience regresses.
25. As a terminal user, I want every Call Log entry to carry a `provider` field, so that I can tell which upstream handled an Attempt now that `model` alone does not say.
26. As a terminal user, I want every Call Log entry to carry `cost_estimated`, so that I never read a computed number as a billed one.
27. As a terminal user, I want `cost_estimated: false` on OpenRouter entries, so that the real cost OpenRouter reports stays identifiable as real.
28. As a terminal user, I want `cost_estimated: true` on Anthropic, OpenAI and Gemini entries, so that the limitation is documented in the artifact rather than in my memory.
29. As a terminal user, I want a cost estimate computed from the token counts the Provider reported, so that my Budget Guardrail still accumulates something meaningful when the tier is not on OpenRouter.
30. As a terminal user, I want a model that the pricing table does not know to log `cost: null` rather than crash my session, so that an exotic or brand-new model ID never costs me a task.
31. As a terminal user, I want every existing Call Log key to keep its name, type and meaning, so that shell one-liners I already use keep working.
32. As a terminal user, I want all four Providers to honour the same request timeout, so that a hung upstream cannot hold my prompt indefinitely whichever Provider it is.
33. As a terminal user, I want the README to document `TIER_<TIER>_PROVIDER`, the accepted Provider names, the per-Provider key variables and which ones are required when, so that I can configure this without reading source.
34. As a terminal user, I want the README to state plainly that cost on the three non-OpenRouter Providers is an estimate, so that I calibrate my `ROUTER_BUDGET_USD` expectations accordingly.
35. As a maintainer, I want every Provider to implement one Contract (`call` + `is_retryable`), so that the Router depends on the shape and never on a specific upstream.
36. As a maintainer, I want the Router to resolve a Provider by name through one lookup, so that there is exactly one place that knows which names exist.
37. As a maintainer, I want everything a Provider differs in — base URL, auth header, request body, response parsing, retryable error codes, cost provenance — to live inside that Provider's own module, so that adding a fifth means adding one file and one registry line.
38. As a maintainer, I want no vendor SDKs and no multi-provider calling library in the call path, so that ADR-0002 stays honoured and each Provider is a thin `urllib` REST caller.
39. As a maintainer, I want `litellm` used for its pricing utility only and never for `completion()` or routing, so that the dependency does not quietly become the calling layer ADR-0002 rejected.
40. As a maintainer, I want the `litellm` import deferred to the moment a cost is actually estimated, so that a heavy dependency does not tax REPL startup or an OpenRouter-only session.
41. As a maintainer, I want all four Providers to share one HTTP helper, so that the test suite keeps exactly one boundary to fake instead of gaining one per Provider.
42. As a maintainer, I want the existing `urlopen` fake to keep being the only seam, so that tests still prove that the right URL, headers and body reached the wire for the Provider the tier selected.
43. As a maintainer, I want each Provider's usage translated into the same three keys the Router already consumes, so that the Router never learns a vendor's field names.
44. As a maintainer, I want `is_retryable` to stay a pure function of the exception, per Provider, so that "is this transient here?" remains directly unit-testable.
45. As a maintainer, I want the Provider name carried on the route result, so that the REPL and the Call Log get it from the same place rather than re-deriving it.
46. As a maintainer, I want Tier Config to own the Provider-name-to-key-variable mapping for validation only, while each Provider still reads its own key at call time, so that the existing division of responsibility is preserved rather than reshuffled.
47. As a maintainer, I want dispatch on an unknown Provider name to raise loudly rather than silently fall back to OpenRouter, so that startup validation is the single guard and a bug cannot hide behind a default.
48. As a maintainer, I want tests that assert an Escalation chain crossing two Providers reached two different hosts in order, so that cross-Provider Escalation is proven at the wire and not by a stub.
49. As a maintainer, I want the cost estimator tested against the real pricing utility rather than a fake, so that the tests fail if the dependency's contract moves under us.
50. As a maintainer, I want Local CLI Providers left unbuilt, so that they get their own brief rather than being smuggled in beside an API Provider.

## Implementation Decisions

**Providers become a package.** The single `provider` module becomes a Providers package: one module per Provider (`openrouter`, `anthropic`, `openai`, `gemini`), one shared HTTP helper, one registry. The move is a move, not a rewrite — OpenRouter's existing URL, payload, parsing, timeout and retryable-code set carry over unchanged into its own module, and its tests move with it. Everything that referenced `model_router.provider` (Router, tests, the `conftest` fake) is updated to the new location; no compatibility shim is left behind.

**Provider Contract.** A Provider is anything exposing two module-level functions: `call(model, system, messages) -> (answer, usage)` and `is_retryable(exc) -> bool`. Python modules satisfy that structurally, so the registry maps a name to a module and no Protocol class, ABC or wrapper object is introduced — the Contract has no state, and giving it a class would add a type with nothing in it.

**Registry and dispatch.** One mapping from Provider name to Provider module, plus the accepted-names set derived from it, lives in the Providers package. The Router asks Tier Config for the tier's Provider name, resolves it once per tier, and calls `provider.call(...)` / `provider.is_retryable(...)` through the Contract. Resolving an unknown name raises rather than defaulting; the guard against that ever happening is startup validation, and a silent fallback would make a config bug look like a working session on the wrong upstream.

**Shared HTTP helper.** One helper performs the POST: it takes a URL, a header dict and a payload dict, encodes JSON, applies the shared `TIMEOUT_SECONDS`, and returns the decoded response body. It also holds the retryable-HTTP-code predicate that each Provider parameterises with its own code set. `urlopen` is imported by this helper and nowhere else — that single import is the test seam for all four Providers.

**Per-Provider specifics.** Each Provider module owns its base URL, auth header, request body, response path to the answer text, usage translation, retryable code set and cost provenance:

| Provider | Endpoint shape | Auth | Answer path | Usage | Cost |
|---|---|---|---|---|---|
| openrouter | `/api/v1/chat/completions` | `Authorization: Bearer` | `choices[0].message.content` | `usage.prompt_tokens` / `completion_tokens` | real, from `usage.cost` |
| openai | `/v1/chat/completions` | `Authorization: Bearer` | `choices[0].message.content` | `usage.prompt_tokens` / `completion_tokens` | estimated |
| anthropic | `/v1/messages` | `x-api-key` + `anthropic-version` | `content[0].text` | `usage.input_tokens` / `output_tokens` | estimated |
| gemini | `/v1beta/models/{model}:generateContent` | `x-goog-api-key` | `candidates[0].content.parts[0].text` | `usageMetadata.promptTokenCount` / `candidatesTokenCount` | estimated |

These shapes are the starting point, not a substitute for the vendor's current documentation: the implementer confirms each request and response shape against the official docs (Context7) before writing the parser. Two known non-obvious points: Anthropic's Messages API requires `max_tokens` on every request (a module-level constant in that Provider, not a configurable knob) and takes `system` as a top-level field rather than a message; Gemini takes the system prompt as `systemInstruction` and uses `model` where the others use `assistant`, so that Provider translates the incoming message list.

**Usage normalisation.** Whatever a Provider's wire format calls them, `call()` returns the same usage dict the Router already consumes — `cost`, `prompt_tokens`, `completion_tokens` — with one key added: `cost_estimated`. The Router passes the dict through to the Budget Guardrail and the Call Log without interpreting it, so no vendor field name ever reaches the Router.

**Retryable codes per Provider.** Shared base: 429 and 500/502/503/504 are transient; a timeout (bare, or wrapped in a `URLError`) is transient; everything else, including parse-shaped exceptions and unrecognised exception types, is not. Anthropic adds 529 (overloaded) to its set. Each Provider states its own set explicitly rather than inheriting a mutable shared one.

**Estimated Cost.** A small cost module exposes one function: given a model string and the token counts, return a float or `None`. It imports `litellm` lazily inside that function — the dependency is heavy enough that importing it at module load would tax every REPL start, including sessions that never estimate anything. Any exception from the pricing utility (unknown model, missing token counts, a moved signature) is caught and turned into `None`: the Budget Guardrail already treats `None` as "record nothing", which degrades the guardrail to "off" rather than losing the user a task — the same failure direction feature 0002 chose for a missing `cost` field. The pinned version uses `cost_per_token()`; the settled decision remains "litellm for pricing only, never for calling".

**Pricing model names.** `litellm` identifies models by its own qualified names, which do not always match a Provider's raw model ID — Gemini models need a `gemini/` prefix, Anthropic and OpenAI IDs are used as-is. Each Provider therefore passes the pricing-qualified string when it estimates; the prefix is that Provider's constant, kept next to its other vendor-specific details rather than in the cost module.

**`cost_estimated` is a property of the Provider, not of the estimate's success.** OpenRouter always logs `false`; the other three always log `true`, including when the estimate came back `None`. The flag answers "did the Provider itself report this cost?", which is well-defined in every case; making it depend on whether pricing succeeded would produce an entry with `cost: null, cost_estimated: false` that reads as "OpenRouter reported nothing".

**Tier Config.** `TierConfig` gains a per-tier Provider name (`TIER_<TIER>_PROVIDER`, lowercased and stripped, empty or unset meaning `openrouter`) and an accessor alongside `model_for`. Its single `api_key` field becomes a mapping from Provider name to the value read from that Provider's environment variable, populated for all four at load time. Each Provider still reads its own key from the environment at call time exactly as `call_openrouter` does today — Tier Config holds the keys for validation only, which preserves the existing division rather than reshuffling it into a new one.

**Validation returns problems, not variable names.** `validate()` today returns a list of missing variable names and `__main__` prints them after "Missing required environment variable(s):". An unrecognised Provider name is not a missing variable, so `validate()` now returns a list of human-readable problem strings — one per missing model ID, one per missing key for a referenced Provider, one per unrecognised Provider value naming the variable, the offending value and the accepted names — and `__main__` prints them under a generic configuration-error heading, one per line, still exiting non-zero before the first prompt. This is a deliberate change to an existing user-visible message: it stays the same error class, at the same moment, with the same exit code, and it is the minimum needed to report a problem that is not "a variable is missing". All problems are still reported in one pass.

**Required keys are the union of referenced Providers.** Validation collects the Provider names the three tiers resolve to (including defaults) and requires exactly those keys. A tier whose Provider name is unrecognised contributes a name error and no key requirement — reporting a missing key for a Provider that does not exist would be noise.

**Router.** `route()` and `_attempt_tier` gain the Provider: the tier's name is resolved from Tier Config, the module from the registry, and both the name and the model are threaded through to the Call Log entry and the result. `RouteResult` gains a `provider` field. Everything else about the Attempt loop, the backoff schedule, the Escalation ladder and the Budget Guardrail checks is untouched. Because each tier resolves its own Provider, an Escalation may change Provider mid-chain; no code expresses that as a special case.

**Call Log schema.** Two keys added: `provider` (the resolved name) and `cost_estimated` (bool). Every existing key keeps its name, type and meaning. One entry per Attempt, as today.

**REPL.** The routing line names the Provider alongside the tier and model. This extends the brief's own reason for adding `provider` to the Call Log — `model` alone no longer identifies the upstream — to the other place the same ambiguity is visible to the user; it is a one-line format change, and the failure path's `Error: {error}` line is untouched.

**Dependency.** `litellm` is added to the project dependencies and the lock file. It is the project's first runtime dependency; the four Providers themselves stay stdlib-only.

**Modules touched.** Providers package (new: shared HTTP helper, registry, four Provider modules, of which OpenRouter is a move); cost estimation (new); Tier Config (per-tier Provider, per-Provider keys, problem-string validation); Router (dispatch through the Contract, Provider on the result and in the log); Call Log (two keys); REPL (routing line); `__main__` (configuration-error output); README; `pyproject.toml`.

## Testing Decisions

**What a good test looks like here.** Unchanged from features 0001 and 0002: drive the system at its outermost useful entry point and assert what an external observer could see — the HTTP requests that left the process (URL, headers, body), the lines in the Call Log file, and the text written to the REPL's output stream. Do not assert that the Router consulted the registry, do not count calls to the cost estimator, and do not reach into `TierConfig` internals when a startup message or a logged entry already proves the behaviour.

**One seam, still.** Four Providers must not become four fakes. All four call through the shared HTTP helper, so tests keep patching a single `urlopen` — now the helper's — through the existing `install_fake_urlopen` fixture. This keeps proving the thing that matters most in this feature: that the Provider a tier selected is the one whose URL, auth header and body actually reached the wire.

**Fixture extension.** The fake gains one capability: it inspects the outgoing request's URL to decide which Provider is being called and builds that Provider's own wire-shaped response. Test scripts stay Provider-agnostic — a bare string is still "the answer text", and the dict form still carries neutral `prompt_tokens` / `completion_tokens` / `cost` which the fake renders into the right vendor field names (`cost` only exists for OpenRouter). Every existing test keeps working untouched, which is itself the regression test for "unset provider still means OpenRouter". Nothing else is faked: no fake Provider module, no fake registry, no fake cost estimator.

**Cost estimation is tested against the real utility.** `litellm` is exercised for real — it is an offline table lookup, not a network call. One test asserts that a widely-known model ID and plausible token counts produce a positive float; it asserts positivity and type, never an exact number, because vendor prices change under us. Another asserts that an unknown model ID yields `None` without raising. Faking the pricing utility here would test our own mock and hide exactly the breakage (a moved signature) that this dependency can inflict.

**Coverage.**

- *Provider modules, through the seam*: for each of the four, a call sends a request to that Provider's URL with its auth header (and, for Anthropic, its version header and `max_tokens`; for Gemini, the model in the path and the system prompt as `systemInstruction`), and parses that Provider's response shape into `(answer, usage)`. A response missing usage fields yields `None` for them rather than raising.
- *Retryability, per Provider*: direct unit tests. The shared codes are retryable everywhere; 529 is retryable on Anthropic; a bad-request or auth code is retryable nowhere; timeouts and `URLError`-wrapped timeouts are retryable everywhere; parse-shaped and unrecognised exception types are retryable nowhere. The existing OpenRouter cases move over unchanged.
- *Tier Config*: unset `TIER_<TIER>_PROVIDER` resolves to `openrouter`; an empty or whitespace value does the same; a mixed-case value resolves; an unrecognised value produces a problem string naming the variable, the value and the accepted names; a tier's Provider key is required only when that Provider is referenced; a setup referencing only one Provider validates with only that one key present; several problems are reported together in one list.
- *Startup*: an unrecognised Provider name exits non-zero with a message before any prompt, including when only the `complex` tier is misconfigured; a missing key for a referenced Provider does the same; a valid single-Provider setup starts.
- *Routing and dispatch, through the seam*: a tier configured to a non-OpenRouter Provider sends its request to that Provider's host with that Provider's auth header; a default-configured tier still reaches OpenRouter; retry at a non-OpenRouter tier sends the repeat requests to that same host.
- *Cross-Provider Escalation, through the seam*: exhausting an Anthropic `easy` tier sends the next requests to the `medium` tier's Provider host, in order, and a success there returns normally; the Budget Guardrail blocks such an Escalation exactly as it blocks a same-Provider one.
- *Call Log*: a chain that escalates across Providers writes one line per Attempt carrying the right `provider` and `model` per rung; OpenRouter entries carry `cost_estimated: false` and the reported `cost`; non-OpenRouter entries carry `cost_estimated: true`; an unpriceable model logs `cost: null` with `cost_estimated: true` and does not break the session; the existing key set is present and unchanged.
- *REPL*: a session driven through `StringIO` prints a routing line naming the Provider that answered, including after an Escalation that changed Provider; the failure line is unchanged.

**Prior art.** `tests/test_provider.py` (moves and splits per Provider), `tests/test_routing.py`, `tests/test_call_log.py`, `tests/test_repl.py`, `tests/test_tier_config.py`, `tests/test_main.py`, and the `install_fake_urlopen` / `tier_env` / `_isolate_router_log` fixtures in `tests/conftest.py`. New tests extend these files rather than introducing a parallel structure.

## Out of Scope

Everything the brief lists, restated for the implementer:

- **Local CLI Providers** (`claude exec` / `codex exec` on the user's own subscription). Investigated and deliberately deferred to its own future feature — full coding agents with tool access are a different shape from a completion endpoint, and their reported cost is an unbilled client-side estimate. No hook, no stub, no registry entry "for later" (`docs/CONTEXT.md`, Decisions).
- **Any other subscription-based Provider auth.** Confirmed unsupported by all three vendors; every Provider authenticates with a pay-per-token API key.
- **Provider-level fallback or retry across Providers within one tier.** Each tier resolves to exactly one Provider. Escalation changing Provider is a consequence of per-tier selection, not a new retry mechanism, and nothing reorders or re-selects a Provider on failure.
- **A hand-maintained price table, or any cost-accuracy guarantee** for the three estimating Providers. `cost_estimated: true` documents the limitation instead of solving it.

Additionally out of scope for this spec: no use of `litellm.completion()`, its router, or any other part of its surface (ADR-0002); no vendor SDKs; no streaming; no per-Provider timeout, retry count or backoff configuration (shared module constants, as today); no configurable `max_tokens`, temperature or other generation parameters; no per-task or REPL-command Provider override; no automatic model-to-Provider inference from the model ID; no change to the Classifier, the tier ladder, the Attempt budget, the backoff schedule or the Budget Guardrail's rules; no Call Log rotation or analysis command; no async or parallel Provider calls; no change to how `.env` is loaded.

## Further Notes

The Provider Contract is the smallest thing that makes the Router Provider-agnostic, and ADR-0002 already settled that we own it rather than renting it from LiteLLM. The consequence that ADR names — a fifth Provider is a hand-written module, not a registered model string — is priced in here three times over, which is exactly why the shapes above are pinned in the spec and confirmed against vendor docs at implementation time rather than guessed at the keyboard.

Building Anthropic first is deliberate. Of the three new Providers it is the one least like OpenRouter — different auth header, a required `max_tokens`, a top-level system field, a content-block response, its own usage field names and its own 529 — so the Contract is proven against the hardest case before OpenAI (nearly identical to OpenRouter) and Gemini arrive. A Contract that only ever saw chat-completions-shaped Providers would not be a Contract.

The `cost_estimated` flag is the honest half of a limitation, not a feature. The Budget Guardrail sums whatever `cost` it is given without distinguishing real from estimated (`docs/CONTEXT.md`), so a session routed to estimating Providers has a guardrail that is approximately right rather than exactly right — and, when a model cannot be priced at all, one that silently does not fire. That is the same "degrade to off" direction feature 0002 chose when OpenRouter omits `cost`, and it stays the right direction: a pricing gap should never cost the user an answer.

Startup validation staying the single guard for Provider names is what lets dispatch raise instead of defaulting. The two decisions are a pair: weaken either one and a typo becomes a session quietly running on the wrong upstream, which is the one failure mode this feature could plausibly introduce and the one it must not.
