# ChatGPT plan access as a separate Provider

Feature: [0057](../specs/0057-chatgpt-subscription-provider.md). Status: Accepted for implementation; planning only.

## Decision

Add `chatgpt` beside the four API-key Providers using the existing hand-rolled Provider Contract and the official public SIWC Responses flow. Each installation connects one user's own account through local browser OAuth. Keep stable host/registration identities, signature-verified account/consent bindings, private credential persistence, cross-process refresh serialization and server revocation. Existing API keys coexist; only explicit route selection determines the access method. No automatic fallback.

This amends [ADR-0011](0011-direct-provider-model-selection.md): API routes require their chosen key, ChatGPT requires its account session and plan permission, and the REPL may open without an admitted route for setup. Every model-backed boundary still requires admission. Runtime Configuration pins registration/session identity for the task and its children while tokens may rotate. Login alone does not change selection; successful explicit selection atomically saves the pair.

This amends [ADR-0012](0012-models-dev-selection-catalog.md): the account's authenticated model list admits ChatGPT choices independently of Models.dev. Optional exact public metadata supplies capacity only; absent verified capacity retains labeled assumptions. The four API Providers retain their catalog policy. ChatGPT plan usage records observed tokens with `cost=null`, never hypothetical API prices or zero billing. API prices and provenance remain historical evidence.

This amends [ADR-0002](0002-hand-rolled-provider-contract.md): the ChatGPT adapter must omit the unsupported remote output cap. Its output reservation is an estimate for local input planning; complete-input assessment and overflow recovery remain, without claiming a guaranteed remote generation or billing ceiling. Other Providers retain enforced caps.

The Call Log remains Conversation's only durable record under [ADR-0005](0005-call-log-is-the-conversation-record.md). Extend v3 additively for access method, opaque registration provenance and validated Responses replay; existing v3 API Sessions remain usable and older formats remain refused. Retain normalized text across account changes, show a notice before sending it to another registration and discard incompatible opaque state. Resume, Retry, Fork, Compression and child Sessions obey the same binding.

## Consequences

The application owns OAuth lifecycle and Responses translation without delegating prompts or Tools to another agent SDK. Declare `PyJWT[crypto]` directly for signature/JWKS verification; reuse stdlib transport and prompt-toolkit. The footer describes selected access/context, `/usage` and `/report` distinguish unknown plan cost from preserved API spend, and plan exhaustion stops for the user's decision. No saved-account selector, credential transfer or remote storage is introduced.

The [spec](../specs/0057-chatgpt-subscription-provider.md) defines exact schemas, readiness, failure and test obligations. [Official SIWC limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations) and [session guidance](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions) were rechecked on 2026-10-21; undocumented spike behavior cannot override them.
