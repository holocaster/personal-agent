# Models.dev selection catalog with local cache and separate accounting

Feature: [0054](../specs/0054-direct-provider-model-selection.md). Status: Accepted; implemented by feature 0054.

## Decision

Use Models.dev's public Provider map through stdlib and a bounded validated cache. Only four existing adapters execute: OpenRouter, OpenAI, Anthropic, Gemini. Normalize upstream `google` to `gemini`, preserving exact offering IDs; never adopt remote SDK/credential/endpoint/body/header configuration.

Cache-first startup uses any valid cache without a request or age expiry. Missing/unusable cache triggers one bounded fetch; explicit refresh validates all four sections before private atomic replacement. Failure preserves the last valid cache and pair. Without cache or successful fetch, stop setup/dispatch with retry guidance. No LiteLLM/bundled catalog fallback, background polling, SDK or generic discovery framework.

Require positive text/Tool capability evidence, usable limits and nondeprecated status. Missing required evidence is locally unsupported; reject specialized/override/replay requirements the unchanged adapters cannot honor. Catalog admission proves neither account access nor universal System/Streaming support. Add no model-name heuristic, unrestricted ID bypass or paid preflight. A refresh removing/disqualifying the current offering preserves its selection/settings but blocks future execution boundaries; current snapshots stay fixed.

For future task snapshots, capacity precedence per field is exact manual override, Models.dev, locked LiteLLM where absent, then existing labeled assumptions. Retain complete prepared-input counting/output constraints. This amends [ADR-0002](0002-hand-rolled-provider-contract.md)'s capacity source, preserving hand-rolled Provider dispatch and local tokenizer/cost utilities.

Pricing stays separate: OpenRouter reported cost is authoritative; direct Estimated Cost uses the existing locked cache-aware LiteLLM path/provenance. Missing pricing does not invalidate an eligible model or imply zero. Live catalog prices do not rewrite accounting/history.

## Consequences

Offline operation can use stale offerings; even admitted models can fail remotely. Refresh can block a selected route locally without choosing another. These are metadata limits, not fallback triggers. The [spec](../specs/0054-direct-provider-model-selection.md) defines concrete bounds and consumed-schema rules. The [official guide](https://models.dev/) and [schema](https://github.com/anomalyco/models.dev/blob/dev/packages/core/src/schema.ts) were checked through Context7/public sources on 2026-10-15. The JSON exceeds generic webfetch's limit, so direct bounded parsing is necessary.
