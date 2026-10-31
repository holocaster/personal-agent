# Project-scoped Session storage and read-only historical discovery

Feature: [0050](../briefs/0050-project-session-discovery.md). Exact encoding, Tool schema, safety bounds and verification are defined by [the spec](../specs/0050-project-session-discovery.md).

Personal Agent's flat, configurable log directory does not identify the project that produced a Session. Ordering by Session Id also treats an old Session resumed today as older than one created yesterday. Repository file searches cannot reliably answer requests for the agent's own previous Session.

Capture the resolved absolute starting cwd once per Run as Workspace Root and project identity. Use that same root for Project Instructions, workspace Tools and Resume. Store the self-contained Call Log and optional Detailed Audit Payload companion under `~/.personal_agent/logs/<readable-flattened-path>--<stable-short-hash>/`, recording the original absolute directory and Run identity on start/resume. Remove both `PA_WORKSPACE` and `PA_LOG_PATH`; no replacement destination override is provided. The hash distinguishes flattened/truncated names; validated metadata detects a conflicting project identity.

This amends ADR-0003's configurable base path, preserving one file per Session. It extends ADR-0005: Resume still appends to the same Session files and strictly rebuilds state, but `--resume last` selects within the starting project by the latest Run start/resume timestamp. Discovery's last/previous uses the same order and excludes the current Session. Interrupted Sessions are eligible; unknown recency or an exhausted selection scan never produces a guessed last.

Expose one read-only `session_logs` Tool using a small shared file reader, with list/read/search operations, current-project default and explicit cross-project access. The ordinary read is a recorded chronological timeline rather than Conversation replay: it includes partial activity and omits duplicate saved snapshots. Searches are literal and case-insensitive. Audit companions require explicit selection and recorded availability. Filesystem checks, existing known-key redaction, bounded scanning/output and continuation preserve source evidence without executing historical Tools or activating logged instructions.

## Consequences

Sessions are naturally separated even when launched outside a repository, and later directory changes cannot redirect a Run's logs. Renaming/moving a project creates a different identity; old evidence can still be addressed by its recorded absolute path. Existing flat logs are neither discovered nor migrated nor deleted. Tests isolate home lookup through existing temporary-home fixtures rather than restoring production overrides.

Finite file scans replace an index. A very large catalog can exceed a safety bound; read/search can continue across scan pages, while resolving last must fail visibly if it cannot establish a complete ordering. No promise of tamper-proof history, concurrent snapshot consistency, retention, or detection of unknown historical secrets is added. Revisit those concerns only as separately scoped work.
