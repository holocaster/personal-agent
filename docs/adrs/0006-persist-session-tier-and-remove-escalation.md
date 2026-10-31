# Persist Session tier and remove automatic Escalation

Tier/evaluator and legacy compatibility are superseded in planned feature 0054 by [ADR-0011](0011-direct-provider-model-selection.md), pending plan review/delivery. Single-route retries, no monetary cap and fatal persistence remain.

Implemented in feature 0039. Supersedes [ADR-0001](0001-escalate-on-technical-failure-only.md) and extends [ADR-0005](0005-call-log-is-the-conversation-record.md).

Amended by [ADR-0007](0007-periodic-session-tier-reevaluation.md), implemented in feature 0041, for scheduled evaluations, cumulative input and `/model auto`. The one-time evaluation policy below is historical; the single-route, no monetary cap and fatal persistence decisions remain in force.

The user chose stable Session routing: the configured easy route evaluates the first routed task once, `/model` can replace that choice or request another evaluation, and Resume retains the latest state. Technical failure must not silently choose a higher tier. Keep same-route transient retries and bounded Context Overflow Recovery; remove automatic Escalation and its monetary Budget Guardrail. Run spend remains visible and resets on Resume.

Persist explicit pending/selected state in the existing Call Log. A new `session_start` declares pending state; subsequent dedicated tier-state records replace it before live mutation or task dispatch. Attempts cannot represent a manual change followed by exit, and command Audit Events cannot represent every automatic decision reliably. A separate state file would duplicate the Session record. The replay contract therefore extends version 2 additively, preserving existing Conversation records and rejecting malformed new state. A valid old log with no tier state starts at medium with a warning and records that compatibility choice.

The evaluator uses the current task plus a fixed instruction through the shared Provider exchange path. It adds no Conversation turn, Tools or workspace context. Evaluator usage contributes to Run spend; its assessment does not replace ordinary `/usage` context information. Cancellation leaves evaluation pending, while ordinary evaluator failure selects medium visibly. Persistence failures remain fatal rather than becoming fallback choices.

## Consequences

Session tier outlives a Run, while Provider/model mappings still come from current Runtime Configuration. Clear and Undo affect Conversation without resetting routing. `/model auto` means one pending evaluation, not per-turn classification. The first routed task pays for an additional easy-route exchange unless a tier was chosen manually; later tasks do not. Older resumable logs remain usable without guessing tier from history. [Spec 0039](../specs/0039-session-tier-selection.md) defines the state schema and validation obligations.
