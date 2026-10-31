# 01: Activate Claude prompt caching

**What to build:** Every request on a Claude route carries one request-level cache marker with the default five-minute lifetime. Claude routes are the direct Anthropic Provider, and OpenRouter when the model id starts with `anthropic/`. Every other route sends exactly what it sends today. There is no setting.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0055-fork-jobs-claude-cache.md`, R1-R3, R17 (cache docs); Implementation Decisions "Prompt cache activation"; Testing Decisions "Caching".

- [x] The direct Anthropic adapter adds top-level `"cache_control": {"type": "ephemeral"}` to every payload, streaming and non-streaming. It sends no `ttl`, no block-level markers and no beta header.
- [x] The OpenRouter adapter adds the same field only when the exact model id starts with `anthropic/`, streaming and non-streaming. Other OpenRouter ids, and the OpenAI and Gemini adapters, keep their payload keys unchanged. The existing `provider` preferences and `session_id` behavior are unchanged.
- [x] The marker is added at payload construction, outside prepared input. Prepared-input token counts, context budgets, the detailed audit's presented request and the three prompt surface fixtures do not change.
- [x] Offline Provider tests assert the captured payload in these cases:
  - direct Anthropic, streaming and non-streaming;
  - OpenRouter `anthropic/...`, streaming and non-streaming;
  - OpenRouter non-Anthropic, OpenAI and Gemini, where the marker is absent;
  - one Compression exchange on a Claude route.

  The existing cache accounting (`test_cache_accounting`), affinity and prompt surface suites stay green without changes to their expectations.
- [x] The README states briefly that Claude routes request prompt caching automatically, and that this guarantees no hit or saving. Mark the cache research proposal as delivered.
- [x] Focused tests pass, then the complete installed `.venv/bin/pytest` suite passes. No live or paid call is made.
