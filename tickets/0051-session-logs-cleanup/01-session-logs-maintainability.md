# 01: Make the Session discovery reader easier to maintain without changing behavior

**What to build:** The `session_logs` Tool (feature 0050) behaves exactly as today, but its reader module is easier to read and no longer depends on other modules' private names. Follow-up approved by the user after feature 0050 review (see `docs/briefs/0050-project-session-discovery.md`, Execution state).

**Blocked by:** None (can start immediately).

**Spec:** none (fast path); **ADRs:** 0008 (unchanged).

- [x] `router.COMPRESS_TASK` is imported once at module level in `session_logs.py`, not per rendered row; if a circular import prevents it, break the cycle without moving behavior (e.g. keep the constant where both modules can import it).
- [x] `session_logs.py` and `tools/registry.py` use no underscore-prefixed names from other modules (`_SESSION_ID_PATTERN`, `_current_session_id`, `_configured_workspace` and any others found); expose public names or accessors in the owning module and update every caller.
- [x] `execute()` is split into smaller functions with clear responsibilities and shallower nesting; internal cursor keys use descriptive names. The cursor stays opaque, HMAC-signed, bound and bounded exactly as before; old cursors need not remain valid.
- [x] The current-Session "in progress" label applies only when both the Session Id and the project id equal the current Session's; a same-id file in another project folder keeps the unresolved/missing wording. Add one regression test for it.
- [x] No other observable behavior changes: Tool schema, output text, ordering, bounds, diagnostics, redaction and errors are unchanged. Existing `tests/test_session_logs.py` and the full suite pass without weakening assertions (test edits only for renamed internals).

Reopened by the user after approval (2026-10-07) to fold in the review suggestions:

- [x] One definition of "current Session": `last`/`previous` exclusion uses the same check as the in-progress label (Session Id and project id). A same-id file in another project folder is no longer skipped under `project: all`. Add one regression test.
- [x] `_Scan` no longer threads the same per-candidate context (candidate, root, header warning, coverage phase, audit) through several method signatures; bundle it once (e.g. set it on the scan when a candidate starts). Replace the `_emit(...) and _advance()` boolean trick with plain sequential calls. No other behavior change.
