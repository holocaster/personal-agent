# 01: Read bounded Skill resources and expose installed SDD dependencies

**What to build:** A loaded Skill can read its relative support files through the existing `skill` Tool, including a legitimate global directory symlink, while ordinary Workspace Tools remain confined. Expose the already installed SDD dependency Skills through symlinks to their existing sources.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0056-isolated-subagents.md` — R01-R03, Module and interface choices, Testing Decisions. **ADRs:** ADR-0014; preserve ADR-0008/0010 storage exclusions.

- [x] `skill(name, path)` returns identifying name/path and text content for a relative support file. Existing `skill(name)`, `skill(names)`, `/skills`, `/skill` result shapes, activation behavior and precedence remain intact; `path` with `names` or without `name` is an argument error.
- [x] The support file is resolved under the effective, revalidated Skill directory. A real global symlink chain within home works; traversal, absolute paths, links escaping/retargeting the Skill, unreadable/nonregular files, excluded secret/recovery paths, NUL, invalid UTF-8, paths over 512 characters, and source over 32 KiB fail visibly. Exact-boundary content succeeds; overflow is refused without silent truncation or execution.
- [x] Existing immutable advertised Skill checks still reject source replacement, retargeting, or a new shadow between advertisement and execution. Resources read current validated bytes and do not change manual active Skill snapshots. Ordinary `read_file`, list/search, mutating Tools and Project Instructions gain no global access.
- [x] Add absent global links for the eight SDD dependencies listed in R03 to their existing `~/.codex/skills` directories, preserving `sdd-main` and unrelated paths. Verify `grilling`, `domain-modeling`, and `tdd` plus their referenced files through production discovery/resource loading. Do not add an installer/startup hook or copy instructions. Report external setup evidence in the implementation handoff; only repository changes belong in the commit.
- [x] Tests use temporary homes/workspaces and real files/symlinks through the Skill Tool seam. Cover a nested support file, a global linked resource, each relevant boundary/error category, instruction single/multi compatibility and changed advertisement. No test depends on this user's installed files or reaches a paid Provider.
- [x] Update the intentional Skill schema description and regenerate/review plan/build/auto prompt-surface fixtures. Focused Skill/workspace/prompt-surface checks pass; unrelated tests are unchanged. Run `git diff --check` before the authorized ticket commit.

Use the existing `workspace_skills` and Tool Registry seams; no new dependency or separate resource Tool is needed. The local linking step may require filesystem approval outside the workspace; preserve unrelated user configuration and give exact diagnostics if a pre-existing conflicting path prevents it.
