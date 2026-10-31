# 0032 — Complete skills

Brief: `docs/briefs/0032-complete-skills.md`. Terms and existing boundaries: `docs/CONTEXT.md`, spec 0030 (Workspace Skills), ticket 0031 (skill Tool), and ADR-0005 (Call Log / Resume).

## Problem Statement

Skills currently work only inside the Workspace Root, with at most one manually active skill per Run and one skill per model Tool call. Users cannot reuse their own skills across workspaces or compose several skills without repeated requests.

## Solution

Offer one effective catalog from workspace and user-global skill directories, preferring a valid workspace skill when both roots have the same name. Allow the user to keep multiple snapshotted skills active in activation order for a Run. Allow the model to request several catalog skills in one `skill` Tool call without changing the manual active set; retain the existing `skill(name)` contract.

## User Stories

1. As a user, I want my `~/.agents/skills` skills to appear alongside workspace skills, so that I can reuse them in different workspaces.
2. As a user, I want the workspace copy to win on duplicate valid names, so that local instructions can specialize a global skill.
3. As a user, I want `/skills` to show each effective skill's origin, so that I know which instructions will load.
4. As a user, I want the model's catalog to show names, descriptions and origins without full bodies, so that it can choose a skill without wasting context.
5. As a user, I want `/skill <name>` to add a skill rather than replace my previous choices, so that later tasks can use several at once.
6. As a user, I want an already-active name to stay unchanged on repeated activation, so that my activation order and snapshot remain stable.
7. As a user, I want `/skill off <name>` to remove only that skill, so that others stay active.
8. As a user, I want `/skill off` to remove all active skills, so that later turns receive none.
9. As a user, I want `/skills` to mark every active skill, so that I can inspect my Run's selections.
10. As a user, I want every active snapshot on subsequent routed exchanges in activation order, so that my composed instructions are available through follow-ups, retries and Escalation.
11. As a user, I want command failures to preserve my active selections, so that typos or unsafe files cannot partially change my Run.
12. As a user resuming a Session, I want no skills active by default, so that earlier Run choices are not silently restored.
13. As a model, I want to load several advertised skills with one Tool call, so that I can use them during the current Conversation without separately activating them for future turns.
14. As an existing model client, I want `skill(name)` to keep working and return its familiar result, so that old calls do not break.
15. As a user, I want invalid, changed, missing or unsafe Tool selections to fail without returning partial instructions, so that one failure does not leak or ambiguously load another skill.
16. As a user, I want global skill loading to leave plan/build and Tool Confirmation rules intact, so that a skill cannot expand access to my home directory or grant Tools.
17. As a piped-input user, I want the same commands and clear errors, so that skills do not require an interactive terminal.

## Requirements

- **R1 — Effective catalog.** Discover valid direct children of `<Workspace Root>/.agents/skills/<name>/SKILL.md` and the current user's `~/.agents/skills/<name>/SKILL.md` only. Apply the existing safe YAML/Markdown reader: validated matching name, description, nonempty instructions, UTF-8, 16 KiB per file, and confined path resolution at each permitted root. No recursion or auxiliary files. An absent root contributes nothing; invalid/inaccessible/escaping entries are skipped safely. Merge by name: a valid workspace entry shadows a valid global entry; an invalid workspace entry does not suppress a valid global entry. Never read a global file from outside the user's skills directory via symlinked ancestors, base, child, or file.
- **R2 — Catalog presentation.** `/skills` remains a local REPL Command and lists the effective catalog deterministically by name, with description, `workspace` or `global` provenance, and a marker for *each* active name (also show active names even if their snapshotted files no longer appear in the live catalog). Report skipped entries without exposing their contents; distinguish their roots. `/help` and completion reflect the new commands. The model-facing `skill` definition in both `plan` and `build` lists the same effective names, descriptions and provenance without full instructions; omit it when the catalog is empty. Discovery itself does not call a Provider or grant filesystem access to other Tools.
- **R3 — Manual activation.** `/skill <name>` resolves the effective catalog and appends a validated immutable snapshot to a Run-local ordered active set. Repeating an already-active name is a no-op (no re-read/reorder), even if its file has since changed; remove then add to refresh. `/skill off <name>` removes just that active name; an unknown active name is a visible error without changing others. `/skill off` empties the set (including when already empty). Missing/extra/invalid arguments or failed load leave the set unchanged. Both input modes work without a Provider Attempt.
- **R4 — Run-local routed prompts.** Subsequent routed turns inject all manually active skill snapshots once, labeled by name and provenance, in activation order into each System Prompt. Freeze the set for the whole turn across Tool follow-ups, local retries and Escalation; `/retry` and Auto-Compress Continuation Turns use the then-current set. `/clear`, `/undo`, `/compress`, `/mode`, and `/model` do not change it. Compression's separate Tool-free summary request still receives no active skills. Resume starts a new Run with an empty set even though Conversation history is replayed; no new Call Log skill-state event or Provider Contract change.
- **R5 — Multi-load Tool contract.** Extend the existing `skill` Tool to accept exactly one of `{ "name": "alpha" }` or `{ "names": ["alpha", "beta"] }`. `names` is a nonempty ordered list of distinct valid names, bounded to at most four per call; single-name calls keep the existing `{ "instructions": "..." }` result. Multi-name calls return `{ "skills": [{ "name": "alpha", "instructions": "..." }, ...] }` in request order, even when the list has one entry. Validate the entire selection against the catalog advertised at the start of this routed turn and re-read each effective file through its permitted root before returning; if a name is invalid, missing, replaced, shadowed by a new workspace copy, or changed since advertisement, return one normal Tool error and no partial skill instructions. Reject a multi-result exceeding 32 KiB of combined instruction UTF-8 bytes rather than truncating. Keep the existing 16 KiB per-file bound and single-name behavior. No Tool Confirmation for `skill`; its result goes into the current Conversation/Call Log but never changes Run-local activation.
- **R6 — Authority boundary.** Global discovery is a narrowly permitted read path for skills only; Workspace Tools and path-based Mutating Tools remain confined to Workspace Root. Skill Markdown and metadata (including `allowed-tools`) are lower-priority content, never permissions, mode changes or Tool Confirmation. `plan` still rejects Mutating Tools at execution; `build` still asks for confirmation. Preserve existing workspace-only and manual single-name usage.
- **R7 — Offline proof.** Test command behavior, duplicate precedence and provenance, snapshot ordering/lifetime, Tool schema and result compatibility, multi-call validation/limits, Resume and root/mode/confirmation boundaries without live Providers.

## Implementation Decisions

- Extend the existing workspace-skills reader to resolve a named skill from the effective two-root catalog, keeping the file parser and per-root containment in one place; carry origin and the effective file identity with catalog snapshots so the Tool can detect changed selection or shadowing. This is a narrowly scoped exception for global skills, not a second Workspace Root for other Tools.
- Keep the active ordered set in the Terminal's Run state, pass immutable snapshots to the Router, and render their blocks in the existing System Prompt path. Do not use Conversation or Call Log entries as activation storage (ADR-0005).
- Extend the Tool Registry's single existing `skill` entry with a mutually exclusive name/names schema and one result path. Freeze the effective catalog for a routed turn for advertisement, and revalidate against current effective resolution at Tool execution rather than trusting an arbitrary model path. Selection errors are atomic.
- No new ADR: the brief settles provenance, precedence, Run lifetime and Tool authority; details here refine the existing seams without reversing an ADR.

## Testing Decisions

- Test visible `/skills` and `/skill` output and captured Provider requests/Tool results through the existing scripted `run_repl` + fake transport + temporary Workspace Root seam. Verify behavior, not helper internals or whether a model obeys hostile instructions. Prior art: `tests/test_workspace_skills.py`, `tests/test_agent_mode.py`, and `tests/fakes.py`.
- At that seam, exercise global-only and workspace-only catalogs, duplicate valid/invalid precedence, provenance, skipped unsafe roots, active ordering/idempotence/selective and total off, unchanged snapshots across commands and changed files, prompt follow-ups and a resumed Run.
- Exercise `skill(name)` unchanged and `skill(names)` in both modes, ordered results and atomic errors for duplicates, malformed/oversized selections, changed or shadowed files, and a multi-result over its total bound. Check Tool results enter Conversation without changing `/skills` activity or sending bodies in the catalog definition.
- Use symlink escapes under both roots and hostile skill instructions to verify no outside reads, no new Workspace Tool access, plan execution denial and build Tool Confirmation. Run the offline test suite.

## Out of Scope

Skill installation/downloads, auxiliary files, model-persisted activation, cross-Run activation persistence, multi-agent execution, MCP/plugins, new home-directory access for ordinary Tools, and automatic skill selection beyond the existing on-demand Tool.

## Further Notes

The 0030/0031 docs describe the previous workspace-only and one-skill behavior; this spec extends those contracts only where stated. Existing Tool results in Conversation can still appear after Resume via ordinary Call Log replay; that is not Run-level manual activation.
