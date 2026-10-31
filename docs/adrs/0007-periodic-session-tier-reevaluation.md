# Periodic Session-tier re-evaluation from durable user submissions

Tier/evaluator policy and compatibility are superseded in planned feature 0054 by [ADR-0011](0011-direct-provider-model-selection.md), pending plan review/delivery. Independent submission/execution identity and durable ordering remain.

Feature 0053's approved [ADR-0009](0009-stable-session-selection.md) supersedes the runtime schedule and `/model auto` policy below. This document remains the normative historical policy-version-1 replay contract; retain its transitions when reading existing logs. Implementation status belongs to the feature tickets.

Implemented, independently approved and merged to `main` in feature 0041 on 2026-10-03. Amends [ADR-0006](0006-persist-session-tier-and-remove-escalation.md)'s one-time evaluation, evaluator-input and `/model auto` policies. Its single-route execution, no Escalation, Provider, fatal persistence and Run-spend decisions remain in force. Extends [ADR-0005](0005-call-log-is-the-conversation-record.md) without introducing another Session file.

## Decision

Fresh Sessions automatically evaluate before submitted routed tasks 1, 5 and 15 using all accumulated routed user messages. Automatic changes only raise the Session tier. Manual `/model <tier>` may lower it and suspends evaluation; `/model auto` retains the tier and progress, requests one evaluation and re-enables remaining checkpoints. Clear discards evaluator input without resetting tier/progress; Undo and Compression preserve it. Evaluation stays outside Conversation and contributes to Run spend.

Persist explicit task submissions and selection policy in the existing version-2 Call Log. A submission records ordinal and exact accepted user text before any evaluation or ordinary dispatch. Small policy records preserve selection mode, next checkpoint and explicit request alongside the tier. Replay restores these independently of Conversation. Deriving them from retained turns would lose failed, undone or compressed requests; deriving them from Attempts would duplicate Provider retries and miss pre-dispatch tasks. A separate file would duplicate the Session record. Submission deltas avoid repeatedly persisting the whole cumulative corpus.

A completed failed evaluation consumes its due checkpoint/request: initial failure selects medium, later failure keeps the tier, both visibly. Cancellation stops the ordinary task and leaves evaluation due. Writes precede live changes and dependent dispatch; observable partial appends restore the prior prefix and failures remain fatal. The full cumulative request must fit the existing easy-route budget; there is no silent truncation, summary, split evaluation or new paid counting path.

Policy-less logs retain their saved tier and have no scheduled evaluations until explicit `/model auto`. Saved pending state retains only its old one-time evaluation; missing tier retains ADR-0006's warned medium fallback. Initialize new counting and input collection at the first Run under this policy, without guessing historical ordinals, texts or origin from old logs. This compatibility mode persists until explicit opt-in.

## Consequences

The first request is no longer the sole automatic evidence for a fresh Session. Tasks 5 and 15 can each add an easy-route evaluation, even if the tier is already complex. Explicit requests, cancelled re-executions and transient Attempts may add cost beyond the three scheduled evaluations. A selected tier remains visible while evaluation is pending instead of being erased by `/model auto`.

Exact routed user text now survives failed tasks and Conversation editing for evaluator replay, until Clear logically discards it; historical Call Log lines are not erased. Progress survives Clear, Undo, Compression and Resume, and Retry retains its original position without duplicating input. The ordinary Router continues to execute an explicitly supplied Tier using current Runtime Configuration mappings. No new Provider or high-level persistence seam is needed.

[Spec 0041](../specs/0041-periodic-tier-reevaluation.md) defines the additive schema, transition validation, compatibility boundary and observable acceptance matrix. Earlier ADRs retain their original decisions with amendment/supersession pointers.
