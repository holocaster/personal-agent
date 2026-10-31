# 01: Keep each Run's logs in its starting project and Resume the latest Run

**What to build:** Launching Personal Agent fixes one Workspace Root and writes its Session files under that project's home-log folder. Resume is current-project scoped and a recently resumed older Session is selected ahead of a newly created but less recently used Session.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0050-project-session-discovery.md`, Fixed Run identity and storage (R01–R05), Shared filesystem/read seam (R06–R08), Tests and documentation (R20), and Testing Decisions. **ADRs:** 0003, 0005, 0007, 0008.

- [x] `main()` captures the resolved starting cwd before Resume, initializes Call Log storage with that same root, and passes it consistently to workspace Tools, Project Instructions, shell/MCP and REPL. Direct REPL/Call Log use has the defined once-captured fallback. Changing cwd afterwards does not redirect log files.
- [x] R03's exact flattened 96-character readable component and 12-hex SHA-256 suffix yield stable project folders, including root, Unicode, long paths, case and two paths with the same flattened readable name. Files use `pa_log-<Session Id>.jsonl` and `.audit.jsonl` within the fixed user-home log root. No new production path option is introduced.
- [x] Start/resume records carry exact `workspace_root`, `project_id` and `run_id`, retaining version 2 and existing routing/replay fields. Initial and available later Run identities are validated before Resume append; mismatched identities cannot mix projects.
- [x] Remove runtime constants/reads for `PA_WORKSPACE`/`PA_LOG_PATH`, replace workspace error text that refers to the removed setting, and update affected README/`.env.example` examples. Ambient stale overrides have no effect; unrelated cap/configuration remains supported. Do not rewrite old planning artifacts or delete/migrate old logs.
- [x] Reuse Call Log's path/reset interfaces and add only the small shared candidate/record/recency seam R06 requires. Directory/id/file boundary checks apply to lookup, fresh writes, ordinary Resume append and audit companion access; safe opens refuse project/root/file symlinks, replacement links and nonregular files. Retain audit owner-only validation.
- [x] `--resume last` compares the latest physical valid Run boundary's parsed timestamp, with the specified Session Id tie break, in the startup project only. Regression: an older id resumed later wins; a newer id from another project does not. Explicit Resume ids cannot escape the current project.
- [x] The shared selection scan obeys 4,096-entry, 8 MiB-byte, 8,192-record and 256 KiB-retained-record bounds without loading whole logs. Empty/inaccessible scopes, unusable Run metadata and exhausted selection scans fail explicitly rather than selecting a partial candidate. Valid unclosed/interrupted Sessions remain eligible.
- [x] Strict Conversation/pending replay still rejects malformed logs, while bounded metadata inspection can retain valid Run boundaries amid unrelated invalid activity. Continue the original files/Session, reset Run spend, and preserve policy/count/input, clear/undo/compression, Todos and pending continuation behavior.
- [x] Replace environment-dependent destination tests and extension/base-path assumptions with temporary-home/cwd fixtures or a narrow patched home lookup, resetting captured storage between tests. No production destination injection is added to satisfy tests.
- [x] Focused Call Log/main/audit/project-instructions/Resume regressions verify folder isolation, fixed capture, identity mismatch, safe opens, exact recency, scan-bound failure and removed overrides. Relevant existing tests pass. Ticket is demoable with two project directories and `--resume last`, without requiring the new model-facing Tool.

## Implementation notes

Own storage and recency behavior now; do not implement a speculative catalog service. Ticket 02 uses this reader and completes tolerant timeline/search paging. Preserve other agents' changes. Root-cause fixtures must prove changed ordering and path behavior before modification; validate one focused increment at a time. No new dependencies or unnecessary code comments.
