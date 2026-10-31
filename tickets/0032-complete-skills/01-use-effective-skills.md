# 01: Use effective global and workspace skills everywhere

**What to build:** A user can discover, manually activate, or model-load a single global skill just like a workspace skill; duplicate valid names use the workspace copy, with provenance visible to both user and model. Existing workspace-only and `skill(name)` behavior still works. This is a complete usable cross-workspace skill slice.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0032-complete-skills.md` (R1–R2, R6–R7, Implementation/Testing Decisions); **ADRs:** ADR-0005 (Run state is not Conversation state).

- [x] Extend the existing bounded skill reader to inspect only direct children of the workspace and user-global `~/.agents/skills` roots. Reuse YAML/name/body/16 KiB validation; confine resolution at each permitted root and reject symlink escapes including a global base/ancestor escape. Absent roots are harmless; unsafe/invalid entries are skipped with root-identified diagnostics and no body leakage.
- [x] A valid workspace skill shadows the global skill of the same name; an invalid workspace entry does not shadow a valid global one. `/skills` displays only the effective catalog in name order with description, `workspace`/`global` origin and active marker. Existing `/skill <name>` activates the effective version as a bounded snapshot; `/help` reflects global availability.
- [x] The model-facing `skill` definition advertises the same effective names, descriptions and origins in `plan` and `build` without instructions; `skill(name)` still returns `{ "instructions": "..." }` for the selected effective version without Tool Confirmation or changing manual activation. Changed/missing/shadowed files between advertisement and Tool execution return a normal Tool error. No catalog means no advertised `skill` Tool.
- [x] Through scripted REPL + fake Provider tests cover global-only/workspace-only, valid and invalid duplicate precedence, provenance/diagnostics, changed or unsafe paths, legacy single-name result, and no global filesystem access via other Workspace Tools. Assert hostile global skill text cannot enable plan Mutating Tools or skip build Tool Confirmation; keep offline suite green.
