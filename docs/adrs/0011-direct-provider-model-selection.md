# Direct Provider/model selection replaces tier policy

Feature: [0054](../specs/0054-direct-provider-model-selection.md). Status: Accepted; implemented by feature 0054.

## Decision

Choose one concrete Provider/model through `PA_PROVIDER`/`PA_MODEL`. Require only the chosen Provider's key; validated local selection saves the pair together through the existing atomic dotenv writer. Ordinary work and all Compression use that pair. Remove tiers, evaluator input/calls/policy, keep/raise and automatic route substitution. Capture immutable configuration at each task/explicit Retry; live Agent Mode remains independent.

This supersedes the tier/evaluator and compatibility decisions in [ADR-0006](0006-persist-session-tier-and-remove-escalation.md), [ADR-0007](0007-periodic-session-tier-reevaluation.md) and [ADR-0009](0009-stable-session-selection.md). Preserve single-route retries, no monetary cap, fatal persistence and ordinary/Compression OpenRouter affinity. The evaluator suffix becomes obsolete.

Explicit submissions and Retry retain original monotonic ordinal and separate execution identity `(run_id, opening position, ordinal)`. Keep request/digest and contributor lineage needed by pending work, reports and recovery; remove cumulative evaluator input/policy. Attempts remain evidence inside executions, never their opener.

New Call Logs use version 3, recording direct routes at Run boundaries and explicit openings as well as Attempts. Resume accepts the new format, uses current validated configuration, restores Conversation/Summary/Todo/pending work and resets Run spend. The user explicitly rejected old-Session/tier-environment migration. Refuse old formats before append, preserve files, and introduce no compatibility wrapper. This amends [ADR-0005](0005-call-log-is-the-conversation-record.md)'s format boundary while retaining Call Log as Conversation's only durable record.

[ADR-0008](0008-project-scoped-session-discovery.md)'s project storage/discovery and [ADR-0010](0010-file-checkpoints-and-recovery.md)'s private exact checkpoint/conflict/rollback/lineage guarantees remain. Recovery before any Attempt uses the opening's route, never a removed easy-route default.

## Consequences

Selection has no hidden evaluator cost. Old setups need new explicit settings; old Sessions cannot Resume. Files are neither migrated nor deleted. New Sessions retain continuity/reporting/recovery. Historical routes are evidence; current Runtime Configuration selects later tasks/Retry. [ADR-0012](0012-models-dev-selection-catalog.md) defines catalog admission and accounting boundaries; the spec owns exact contracts/tests.
