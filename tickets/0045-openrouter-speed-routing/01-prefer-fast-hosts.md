# 01: Prefer fast OpenRouter hosts

**What to build:** Every OpenRouter request prioritizes upstream generation speed through the native provider sorting preference.

**Blocked by:** None.

**Spec:** none (fast path)

## Acceptance criteria

- [x] OpenRouter sends `provider.sort: "throughput"` together with `require_parameters: true` for calls with and without Tools, including prepared-input calls.
- [x] The configured model, output allowance, Tool definitions and default upstream fallback behavior remain intact; no fixed host, new setting or dependency is introduced.
- [x] Existing request-capture checks verify speed preference before and after the change; Provider and context-budget regressions pass without live API calls.
- [x] Concise documentation describes speed-first upstream selection, potentially higher cost, and the absence of a measured live speedup.

## Evidence and execution

The latest Session recorded 391.231 seconds across 14 MiniMax task calls. Current OpenRouter requests specify only `require_parameters`, leaving speed selection unspecified. OpenRouter documents default price-based host balancing and `sort: "throughput"` for highest generation throughput: https://openrouter.ai/docs/guides/routing/provider-selection.

Keep this a request-preference change in the existing Provider adapter. Do not change evaluator, reasoning, streaming, local filesystem traversal or tier/model selection. Implementation and validation were performed without commits; the user subsequently authorized commit and push with independent review still pending.
