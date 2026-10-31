# Stable Session selection with explicit re-evaluation

Tier/evaluator and historical replay are superseded in planned feature 0054 by [ADR-0011](0011-direct-provider-model-selection.md), pending plan review/delivery. Non-evaluator affinity, snapshots and execution/durability guarantees remain.

Feature: [0053](../specs/0053-stable-sessions-and-recovery.md), requirements R1–R10. Status: approved for implementation; this ADR does not claim delivery.

## Decision

Evaluate once before a fresh Session's first routed execution unless manual selection already chose a tier. Thereafter only `/model auto` requests an evaluation. It retains tier, submission progress and cumulative input and coalesces repeated requests before execution. Automatic decisions only keep or raise; manual selection can lower and cancels pending evaluation. Resume makes no evaluation at startup and removes old scheduled checkpoints without discarding user input or Conversation.

This supersedes [ADR-0007](0007-periodic-session-tier-reevaluation.md)'s runtime schedule and auto re-enablement. Its exact submission identity, cumulative evaluator-input, failure/cancellation, single-route, spend and fatal persistence guarantees remain. Replay old policy-version-1 state using old transitions, then append a validated version-2 policy migration before dependent commands/dispatch. Genuine initial/explicit pending evaluation survives; a selected tier's scheduled checkpoint does not. No historical records are rewritten.

Version 2 retains mode and explicit evaluation request and removes checkpoint scheduling. No separate routing-state file is introduced. Policy-less logs preserve their existing selected/pending/missing-tier compatibility boundary and begin absent counting/input empty, never inferred from retained turns or Attempts.

Carry the existing Session Id as OpenRouter's ordinary `session_id`, including Retry and Resume. Evaluator and Compression use distinct deterministic purpose suffixes; preserve current provider preferences. This is best-effort affinity, not cache sharing across models or a guarantee of savings.

## Consequences

Submissions 5 and 15 no longer create maintenance calls or automatic promotions. A greeting-first Session may need explicit `/model auto` or manual selection when later work changes; changing Runtime Configuration remains explicit and can still change the concrete Provider/model at the selected tier.

Keeping strict historical replay costs a small policy-version boundary, but editing a checkpoint constant would make valid old transitions unreadable. The existing Call Log remains the routing/Conversation source; count/input, pending continuation and durable ordering survive independently of Conversation editing. See the spec for the additive migration format, caller changes and acceptance matrix.
