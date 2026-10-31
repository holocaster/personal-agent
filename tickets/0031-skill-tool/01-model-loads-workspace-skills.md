# 01: Let the model load workspace skills on demand

**What to build:** Offer a read-only `skill(name)` Tool so the model can see available workspace-local skills and load one when useful, without requiring a `/skill` command from the user.

**Blocked by:** None (can start immediately). Depends on feature 0030 already present in this branch.

**Spec:** none (fast path). **ADRs:** none.

- [x] Advertise `skill` in both Agent Modes when workspace skills are available, with each valid skill's name and description discoverable by the model without sending full instructions in every prompt. No external or global skills.
- [x] Accept exactly one `name` string in the Tool call and return the matching bounded `SKILL.md` instructions as a normal Tool result in the current routed turn. Reuse feature 0030's validation and Workspace Root confinement; invalid, missing or changed files produce a normal Tool error.
- [x] Keep `skill` read-only and free of Tool Confirmation, just like existing Workspace Tools. Loaded instructions do not activate `/skill`, persist as a Run setting, grant Tools, or change plan/build restrictions or Tool Confirmation. Keep `/skills`, `/skill <name>` and `/skill off` working as before.
- [x] Verify through the routed Provider/Tool Registry seam that the model can discover and call `skill`, receives only the selected content in the Tool result, sees an error after an invalid or missing name, and does not gain access to forbidden Tools. Keep existing offline tests passing.
