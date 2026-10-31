# 0030 — Workspace Skills

## Goal

Let the user explicitly load reusable, workspace-local instructions for the agent without changing its Tool Registry.

## Scope

- Discover `SKILL.md` files under `.agents/skills/<name>/` within the Workspace Root. Use the standard skill frontmatter for name and description and the Markdown body for instructions.
- `/skills` lists available skills by name and description; `/skill <name>` loads one skill into subsequent routed requests; `/skill off` deactivates it. Show the active skill in `/skills`.
- One skill can be active at a time. It remains active for this Run until replaced or disabled; a new Run, including Resume, starts without an active skill.
- Bound the skill content sent to the model and reject paths that escape the Workspace Root. Invalid or missing skills produce a visible error without activating them.
- Skill instructions cannot change Agent Mode, Tool availability, Tool Confirmation, or workspace path boundaries.

## Out of scope

- Automatic selection of a skill from its description.
- Global user skills or discovery outside the Workspace Root.
- Multiple simultaneously active skills; requested as a future feature.
- Skill installation, downloading, executing scripts, adding Tools, MCP, or plugins.

## Settled decisions

1. First release uses explicit activation only, via REPL commands.
2. Skills live under `.agents/skills/<name>/SKILL.md` in the Workspace Root and use the standard `SKILL.md` format.
3. A skill lasts for the current Run only, until `/skill off` or replacement. Only one may be active at a time.
4. Future improvements to consider separately: automatic selection, global user skills, and multiple active skills.

## Open questions

None for product scope. The planner owns validation, size bounds, prompt integration, and ticket slicing within these decisions.
