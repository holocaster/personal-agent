# Exact file checkpoints separate from Conversation Undo

Feature: [0053](../specs/0053-stable-sessions-and-recovery.md), requirements R21–R28. Status: approved for implementation; this ADR does not claim delivery.

## Decision

Add one bounded exact checkpoint for the latest routed execution with successful changes from `write`, `edit` or `apply_patch`, including failed/interrupted executions. A submission or explicit Retry opening defines an execution. Retry retains the original ordinal but creates a separate restore set; earlier executions' mutations are outside that set. Coalesce repeated canonical paths to first before-state and final after-state, recording creation/deletion as absence.

Store versioned before/after byte images and permission/path identity in an owner-only companion under existing project-scoped Session storage. Call Log keeps only compact recovery attribution and continuation invalidation. This extends [ADR-0005](0005-call-log-is-the-conversation-record.md) and [ADR-0008](0008-project-scoped-session-discovery.md) with a local file-state companion; Conversation remains solely in Call Log and no Git state changes.

Journal intent before approved file mutation and observed after-state before further dependent work. Persist restoration intent before file recovery. Resume reconciles exact before/after states, never automatically executes Tools or restores files. Incomplete/ambiguous state fails visibly instead of claiming recoverability.

`/recover` previews the latest set and requires literal `yes`, including auto/piped operation; plan permits preview only. Validate every recorded after-state, exclusion, link identity and boundary before restoration and after confirmation. Refuse the whole set on conflict. Preserve existing supported in-root leaf links; reject hard-linked mutation targets whose untracked aliases cannot satisfy confinement. Restore bytes, absence and mode, with rollback/error reporting for partial failure. Success consumes the checkpoint; there is no older-checkpoint stack or redo.

Before the first restore write, durably invalidate continuation belonging to that exact execution. Preserve its request/ordinal for fresh Retry and discard obsolete Tool results, Todo effects, fetched URLs and Gemini replay. An unrelated later pending execution is retained. `/undo` remains Conversation-only; recovery changes no successful turn, Summary or evaluator input. Even if restoration later fails, invalidated continuation remains invalidated.

## Consequences

The latest file mutation can be recovered after Resume without a repository, while later external edits cause safe refusal. Shell effects remain outside the guarantee. Capture/storage failures and configured bounds can reject a file mutation before it happens rather than silently losing its before-image.

Exact recovery cannot use redacted Tool logs; snapshot bytes must remain exact and private, never enter reports, discovery or Provider requests. Owner-only storage, fixed path/file/aggregate bounds and latest-only retention limit exposure and size. This is not a general backup, tamper-proof history, concurrent-write safeguard or atomic multi-file filesystem transaction. The spec owns exact schema, bounds, ordering, failure and acceptance details.
