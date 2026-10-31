# Fork copies the Conversation into a new self-contained Session

Feature: [0055](../specs/0055-fork-jobs-claude-cache.md), requirements R4-R11. Status: approved for implementation; this ADR does not claim delivery.

## Decision

`/fork` creates a new Session with a newly minted Session Id. Its Call Log v3 file begins with a `session_start` naming `parent_session_id`. The next line, `conversation_forked`, holds a full copy of the parent's turns, Conversation Summary and Todo baseline at the latest closed turn. Resume of the child replays that copy and never reads the parent's file. The parent's Run closes with `session_end` reason `fork` and names the child; nothing else in the parent changes.

[ADR-0005](0005-call-log-is-the-conversation-record.md) rejected "minting a new Session that copies or links back to the old history" for Resume. That rejection still holds. Resume continues one Session, while Fork deliberately produces two independent Sessions from one point. Linking the child to the parent's file instead of copying was rejected for two reasons. First, the child would depend on a file that a later parent Run keeps appending to, so replay would need a cut-off position and the parent's continued validity. Second, the child would break [ADR-0003](0003-call-log-per-session.md)'s one self-contained file per Session. The copy keeps both properties: each Session's Conversation still has exactly one durable record, its own Call Log.

The seed is a separate line rather than part of `session_start`. Project-wide readers inspect line 1 under a per-record size bound, and a large copied history there would make the child unreadable to them.

## Consequences

The child's file duplicates the parent's history at fork time, which costs disk space proportional to the retained Conversation. That is acceptable for a single-user tool, and Compression already bounds the retained turns. Deleting the parent does not affect the child. The child's Run spend, submission ordinals, `/report` and file checkpoint start empty, so inherited history is never counted as new Attempts or cost. Both Sessions share one Workspace Root with no worktree, so file effects from either branch are visible to both. Resuming the parent after the child changed files is protected only by the existing ADR-0010 conflict checks. Revisit if forking from an arbitrary earlier turn or concurrent Sessions become required.
