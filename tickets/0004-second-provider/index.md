# Tickets: 0004-second-provider

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Each Complexity Tier names its own Provider | none | done |
| 02 | Anthropic as a second Provider, with Estimated Cost | 01 | done |
| 03 | OpenAI and Gemini as the third and fourth Providers | 02 | done |

Spec: `docs/specs/0004-second-provider.md`
Brief: `docs/briefs/0004-second-provider.md`
ADRs: `docs/adrs/0002-hand-rolled-provider-contract.md` (constrains all three tickets:
hand-rolled Provider Contract, no vendor SDKs, `litellm` for pricing only),
`docs/adrs/0001-escalate-on-technical-failure-only.md` (unchanged by this feature).

The chain is real, not clerical. 01 is the prefactor plus the config surface: the
Provider Contract, the registry, the one shared HTTP seam and per-Tier Provider
selection, with OpenRouter still the only Provider — so it lands with the entire
existing test suite as its regression proof that an unchanged `.env` behaves
exactly as before. 02 adds the first Provider that is not OpenRouter, and with it
the `litellm` dependency and Estimated Cost; Anthropic goes first because it is the
new Provider least like OpenRouter (its own auth header, a required `max_tokens`,
a top-level system field, content-block responses, its own usage names and its own
529), which is what proves the Contract rather than flattering it. 03 is then two
modules plugging into finished machinery, kept in one ticket because splitting them
would buy a second implement-and-review cycle for a registry line each.

Local CLI Providers (`claude exec` / `codex exec` on the user's own subscription)
are out of scope for this feature and have no ticket here — they get their own
brief (`docs/CONTEXT.md`, Decisions).
