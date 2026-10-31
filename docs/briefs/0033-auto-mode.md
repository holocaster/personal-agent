# 0033 — Auto Agent Mode

## Goal

Add a third user-selected Agent Mode so ordinary Tool calls can run without repeated confirmation while recognized Dangerous Commands still require the existing Strong Confirmation.

## Scope and settled decisions

- `/mode auto` selects the new mode for later routed turns; `/mode` reports it. `plan` stays read-only and `build` keeps today's confirmation behavior. `auto` offers the same Tools as `build` and changes only the confirmation policy. A mode stays fixed for a routed turn; it does not change tier routing, Conversation, Todo List, or active skills.
- In `auto`, `shell`, `write`, `edit`, `apply_patch`, `webfetch`, and `websearch` skip their ordinary confirmation prompts. A `shell` command matched by the existing Dangerous Command rules still shows its command and warnings and requires Strong Confirmation (`yes` exactly); rejection, EOF, and piped input keep existing behavior. Do not expand or replace the rule set. Validation, preparation, Workspace Root constraints, Agent Mode enforcement, Tool results and Call Log behavior remain intact. The `question` Tool still asks its actual question; it is not a Tool Confirmation.
- For automatically approved calls show only the normal Tool result, not the diff, command, or confirmation preview. For flagged commands keep the existing Strong Confirmation preview and fetched-content warning.
- Each Run, including Resume, still starts in `build`. Shift+Tab cycles `plan → build → auto → plan` only while editing a task; update `/help`, command completion, footer and model-facing mode/Tool descriptions to reflect the active policy. Piped input supports `/mode auto` and can execute non-dangerous Tools without confirmation input.
- Verify ordinary and dangerous paths in both input modes, mode switching, unchanged build/plan behavior and trust boundaries with offline tests.

## Out of scope

New Dangerous Command rules or shell sandboxing, changing the default mode, persistence across Runs, model-initiated mode changes, new Tools, and changes to Provider routing or Tool Confirmation in `build`/`plan`.

## Open questions

None. Local SDD artifact, implementation and review commits are authorized; do not push without another request.
