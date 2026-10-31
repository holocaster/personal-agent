# 0055: Fork, Background Jobs and Claude prompt caching

## Goal

Deliver the remaining research proposals the user selected on 2026-10-17: Claude prompt caching, `/fork`, and Background Jobs. Sources: `docs/research/done/2026-10-14-cache-and-session-routing.md`, `docs/research/done/2026-10-14-reference-opportunities.md` (section 4), `docs/research/done/2026-10-09-feature-opportunities.md` (jobs).

## Settled scope

1. **Claude prompt caching.** Send one request-level cache marker, default five-minute TTL, on the direct Anthropic Provider and on OpenRouter when the model id starts with `anthropic/`. Always on, no setting. No manual breakpoints. Verify the current request syntax for both APIs through Context7/official docs before specifying. Existing cache accounting (0053 ticket 04) must keep working; prompt surface snapshots change only where the payload legitimately changes.
2. **`/fork`.** Creates a child Session with a new Session Id from the latest closed turn of the current Session, copying Conversation, Conversation Summary and Todo List and recording the parent Session Id. The REPL switches to the child immediately; the parent stays unchanged and resumable with `--resume <id>`. The child's Run spend starts at zero; inherited history never counts as new Attempts or cost. Refused while a pending or failed turn awaits `/retry`. Agent Mode and active Skills stay as they are in the Run. The Provider/model pair is global configuration, so nothing is inherited. Copying runs no Tools, restores no files and creates no worktree. Both Sessions share the same Workspace Root; help text says so.
3. **Background Jobs.** `shell` gains `background: true`, returning a job id instead of waiting. Same Tool Confirmation, Strong Confirmation and plan-mode refusal as `shell`. New Tools `job_status(id)` (state, exit code, output tail) and `job_stop(id)`. REPL commands `/jobs` (list) and `/jobs stop <id>`. At most four live jobs; each retains only its latest 64 KB of combined output. Jobs belong to the Session in the current Run: `/clear` keeps them; Fork, `/exit` and Run end (including crash paths the REPL can handle) stop the whole process group. Not persisted; never survive Resume. Start and stop are visible in the Call Log like other Tool executions.

## Out of scope

MCP Tools (deferred by the user), entry-point plugins, and `/report` model-switch diagnostics (already covered by 0053 ticket 04 route groups). No job persistence, no job stdin, no forking from an arbitrary earlier turn, no concurrent Sessions.

## ADR proposals

- Fork creates a new self-contained Call Log v3 file seeded from the parent (copy, not reference), so the child resumes without reading the parent. Planner decides whether this earns an ADR against ADR-0003/0005.

## Open questions for the planner

None from the product side. Seam choices (seeding format of the child log, job registry location) belong to the planner.
