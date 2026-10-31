# 0032 — Complete skills

## Goal

Finish the user-facing skill capabilities together: discover user-global skills, activate multiple skills manually for a Run, and load multiple skills on demand through the model-facing `skill` Tool. This is one feature, not three separately approved features.

## Scope and decisions

- Discover both `<Workspace Root>/.agents/skills/<name>/SKILL.md` and `~/.agents/skills/<name>/SKILL.md`. Use the existing bounded YAML/Markdown reader and path protections for each permitted root; the global root is explicitly limited to the user's skills directory. Duplicate names resolve to the workspace version. `/skills` and the Tool description show the effective catalog and its provenance.
- `/skill <name>` adds a validated, snapshotted skill to the active set for the current Run (idempotent for an already-active name). `/skill off <name>` removes one; `/skill off` removes all. `/skills` marks all active skills. Subsequent routed exchanges receive every active snapshot in activation order. No Run activation is restored by Resume; existing `/clear`, `/undo`, `/retry`, `/compress`, and mode switches retain it within a Run.
- Expand the `skill` Tool to load multiple selected names in one call. Preserve a single-name call for existing users/providers. It returns bounded instructions for each selected skill in the current Conversation; it does not change the active set for future turns. Invalid, changed, or missing selections fail safely; a global skill shadowed by a workspace skill resolves to the workspace version. Tool discovery includes global and workspace skills in `plan` and `build`.
- Skill contents never grant Tools, override mode or Tool Confirmation, or bypass root boundaries. Global discovery does not grant general filesystem access to other Tools. Keep existing workspace skills and manual single-name use working.
- Verify command behavior, discovery precedence, prompt composition, Tool calls/results, Resume, and safety boundaries with offline tests.

## Out of scope

Installing/downloading skills, auxiliary skill files, automatic persistent activation by the model, multi-agent execution, MCP/plugins, and persisting manual activation across Runs.

## Open questions

None. Exact schema, ordering of catalog display, and bounded limits are implementation/spec details; prefer the smallest change reusing the current reader and Tool Registry.
