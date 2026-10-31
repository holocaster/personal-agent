# 0025 — Plan and Build Modes

## Goal

Let the user choose whether the agent can change the workspace during a Run, without changing the existing tier routing or adding a Provider call.

## Scope

- `/mode` shows the current Agent Mode; `/mode plan` and `/mode build` switch it for subsequent routed tasks. Only the user can switch modes.
- Every new Run, including Resume, starts in `build`. The current mode is visible in the interactive terminal; piped input can use the same command and gets a plain-text response.
- In `plan`, the agent can converse, use read-only workspace Tools, `calculator`, `current_time`, `todo`, and `webfetch` with its existing Tool Confirmation. It cannot run `write`, `edit`, or `shell`, even if it requests one by name. If the user asks for a change in `plan`, the agent should explain that the user must switch to `build`.
- In `build`, the existing Tool set and Tool Confirmation behavior remain available, including Strong Confirmation and the fetched-content warning.
- Changing modes does not change the Conversation, Todo List, Tier Pin, or tier classification. No mode change takes effect in the middle of a routed turn.

## Out of scope

- Agent-initiated or automatic mode switching.
- Persisting mode across Runs or including it in Resume state.
- A new TUI, queued-input display, or a new planning Tool.
- Changing the classifier, Provider selection, or existing confirmation rules.

## Settled decisions

1. The user alone controls mode via `/mode plan|build`; `/mode` reports the current value.
2. Default and Resume mode is `build`, with mode scoped to one Run.
3. `plan` retains `webfetch` under its existing confirmation gate; workspace-changing Tools and `shell` are unavailable in this mode.
4. Commits on this feature branch are authorized for SDD artifacts, implementation, and review; do not push.

## Open questions

None for product scope. The planner owns acceptance details and ticket decomposition.
