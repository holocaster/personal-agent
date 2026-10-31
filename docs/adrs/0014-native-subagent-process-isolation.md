# Native Subagents own a process and fresh Session

Feature: [0056](../specs/0056-isolated-subagents.md). Status: approved for implementation; this ADR does not claim delivery.

## Decision

Execute each named Subagent in a fresh Python worker process that calls the existing Router once. Keep one first-level child active at a time. Transfer the parent task's admitted immutable Runtime Configuration and configured capabilities, Project Instructions, the complete selected role, and task/references. Start fresh Conversation, Summary, Todo, active Skills and process state. Return a bounded answer/handoff through the native `agent` Tool. Roles narrow the parent's configured Tool set; children cannot delegate or ask product questions directly. The parent terminal owns live mode changes and confirmations.

Calling the Router inside the parent, recursively invoking the REPL, or using a thread would require saving/restoring process-global Call Log, Workspace, Tool Registry, shell configuration and Background Job state across errors and interrupts. That would couple ordinary routing to child lifecycle and make independent execution fragile. A separate process contains those globals and reuses the existing Provider/Tool loop without introducing another agent CLI or Provider abstraction. Private IPC carries confirmation/mode, evidence, progress and lifecycle messages; no generic RPC framework is needed.

Each child has a self-contained project-scoped Call Log v3 with `session_kind: subagent` and explicit parent Session/execution/Tool-call attribution. Its task starts from empty Conversation with no Fork seed. This extends [ADR-0003](0003-call-log-per-session.md), [ADR-0005](0005-call-log-is-the-conversation-record.md) and [ADR-0008](0008-project-scoped-session-discovery.md). [ADR-0013](0013-fork-copies-into-a-new-session.md)'s parent link continues to identify copied history for Fork unless the explicit Subagent kind is present; malformed Forks remain rejected.

Store physical Attempts only in the child's log. Compact parent cost receipts refer to original child Attempt identities and add known child costs to parent Run spend once, with separate delegated coverage in Session Reports. They are references to evidence, not duplicate Attempts. Parent Resume resets current Run spend without recharging history. Failures and interrupted children retain available cost evidence and incomplete coverage.

The worker uses the same Workspace Root and Git checkout. Its file checkpoints stay under its own Session; parent/child file conflicts use [ADR-0010](0010-file-checkpoints-and-recovery.md)'s existing refusal. Only bounded relative Skill-resource access extends beyond ordinary Workspace Tools. Selecting role instructions or loading Skills does not override Agent Mode, confirmation, file boundaries or role permissions.

## Consequences

Delegation incurs process startup and IPC complexity, but keeps state ownership and cancellation explicit. The parent must reap children and their shell/job groups on success, error, cancellation and channel loss, preserving parent-owned jobs. There is no automatic child Resume, concurrency, nested execution, filesystem sandbox or per-role route choice. Bash remains the existing host-access Tool when a role permits it. The [spec](../specs/0056-isolated-subagents.md) defines formats, limits, mappings, accounting and verification.
