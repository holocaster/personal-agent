# 0025 — Plan and Build Modes

Brief: `docs/briefs/0025-plan-build-mode.md`. Vocabulary and existing Tool
boundaries: `docs/CONTEXT.md`. The existing Terminal and Resume decisions are
recorded in ADR-0004 and ADR-0005; this feature does not amend them.

## Problem Statement

Today a user can ask the Personal Agent to investigate without changing files,
but the same routed task still offers Mutating Tools. Tool Confirmation is a
last gate, not a way to ask the agent to work without attempting changes.

## Solution

Let the user select an Agent Mode for the current Run with `/mode plan` or
`/mode build`, and inspect it with `/mode`. Start every Run, including Resume,
in `build`. In `plan`, retain conversation and investigation Tools but never
offer or execute `write`, `edit`, or `shell`. In `build`, retain existing Tool
and Tool Confirmation behavior. A mode switch affects later routed turns only.

## User Stories

1. As a user, I want `/mode` to report the current Agent Mode, so that I can
   check what the agent is allowed to do.
2. As a user, I want `/mode plan` to switch later tasks to investigation only,
   so that I can explore a change without changing my workspace.
3. As a user, I want `/mode build` to restore the usual Tools for later tasks,
   so that I can authorize implementation when ready.
4. As a user, I want each fresh Run to begin in `build`, so that a past choice
   does not silently carry forward.
5. As a user resuming a Session, I want the new Run to start in `build` while
   keeping its Conversation and Todo List, so that mode is not Resume state.
6. As an interactive terminal user, I want the current mode visible while I
   type, so that I do not have to query it before every task.
7. As a piped-input user, I want the same `/mode` commands and plain-text
   replies, so that mode works without a TUI.
8. As a user in `plan`, I want workspace inspection, arithmetic, time, and
   Todo List Tools, so that investigation stays useful.
9. As a user in `plan`, I want `webfetch` available with Tool Confirmation,
   so that network access still requires my explicit decision.
10. As a user in `plan`, I want workspace-changing Tools and `shell` absent
    from offered Tools, so that the model is not invited to use them.
11. As a user in `plan`, I want attempts to call forbidden Tools by name
    refused without executing or confirming them, so that an invented Tool
    call cannot bypass the restriction.
12. As a user asking for a change in `plan`, I want an explanation that I must
    switch to `build`, so that I know how to proceed.
13. As a user in `build`, I want the existing confirmation and dangerous-command
    behavior, so that a mode change does not weaken my existing safeguards.
14. As a user, I want switching modes to leave my Conversation, Todo List,
    Tier Pin, and tier selection untouched, so that the choice is orthogonal to
    context and routing.
15. As a user, I want a task already in flight to retain its starting mode,
    so that a later command cannot change the rules partway through the task.
16. As a user, I want mode commands to be local, so that reporting or changing
    mode does not spend an extra Provider Attempt.

## Requirements

- **R1 — User-only command.** `/mode` reports exactly one of `plan` or `build`;
  `/mode plan` and `/mode build` set the mode for subsequent routed turns. Add
  discovery through `/help` and interactive command completion. Invalid forms
  (including extra arguments or an unknown value) report usage, keep the mode
  unchanged, and are not sent to a Provider. No agent-requested or automatic
  mode switch is supported.
- **R2 — Run scope and display.** The mode is initialized to `build` for every
  new Run, including Resume, and is not saved in or restored from the Call Log.
  The interactive Status Footer displays the current mode; piped input has no
  footer but supports the same `/mode` commands with plain-text replies.
- **R3 — Plan Tool boundary.** Every Provider exchange in a `plan` routed turn
  that offers Tools advertises only `list_files`, `read_file`, `search_text`,
  `calculator`, `current_time`, `todo`, and `webfetch`. For that whole turn,
  attempts to call `write`, `edit`, or `shell` (including calls in a mixed batch
  or in later Tool rounds) yield a Tool error without prepare, apply, or Tool
  Confirmation, regardless of registration, arguments, or caller-supplied name.
  Allowed Tools retain their existing validation, logging and results.
- **R4 — Plan guidance and network gate.** The `plan` System Prompt tells the
  agent to investigate and discuss only, and to explain that the user must
  switch to `build` when asked to change the workspace. `webfetch` remains
  available but still uses its existing Tool Confirmation, including rejection
  behavior. Mode commands themselves require no Provider exchange.
- **R5 — Build parity.** `build` advertises and executes exactly the current
  Tool set (including the existing `PA_ENABLE_SHELL=0` opt-out) and retains
  existing Tool Confirmation, Strong Confirmation for Dangerous Commands, and
  Fetched-Content Warning behavior. No new Tool or confirmation rule is added.
- **R6 — Turn stability and routing independence.** Capture the active mode at
  the beginning of a routed turn and use it for all its Provider exchanges,
  retries, Escalation, Tool rounds, and any subsequent Tool execution in that
  turn. A mode command only affects later turns (including `/retry` and a
  Continuation Turn when one is started after the switch). Switching mode
  does not clear or change the Conversation, Todo List, Tier Pin, classifier,
  Tier Config, or Provider selection. Compression still has no Tools.

## Implementation Decisions

- The Terminal owns the Run-local Agent Mode and `/mode` REPL Command, in the
  same area as `/model`. Report it in the existing interactive Status Footer
  without adding a new presentation surface; keep piped mode line-oriented.
- The Router accepts the turn's mode and chooses the advertised Tool
  definitions once per routed turn, applying the same choice to initial and
  follow-up exchanges. Existing Tier routing and retry/escalation logic stay
  intact; the mode is not a Complexity Tier or Tier Pin.
- The Tool Registry remains the single source of Tool definitions. Execution
  enforces the turn's permitted names before schema validation and before any
  prepare/confirmation/apply step, not just by hiding definitions from the
  Provider. Preserve the ordinary unknown-Tool error path for other invented
  names. An allowed call in a mixed batch continues to execute normally.
- Plan-only instruction text is added to the existing System Prompt for
  routed turns; existing date, Memory, Conversation Summary, Todo List, and
  third-party `webfetch` warning stay in place. No new Provider call is made
  to classify or select mode. Compression remains Tool-free.
- No new persistence format, Call Log state, Provider contract, or ADR is
  needed. ADR-0004's inline Input Box and ADR-0005's Resume replay remain as is.

## Testing Decisions

- Assert observable outcomes, not private state: replies/footer, offered Tool
  names in fake Provider exchanges, Tool results and Call Log entries, workspace
  contents, confirmation invocations, and unchanged routing/Conversation after
  switching. Do not rely on a model obeying an instruction for the safety gate.
- **Highest seam:** exercise `run_repl` with the existing fake Provider
  transport, scripted Tool calls and input/confirm responses. Prior art:
  `tests/test_repl.py`, `tests/test_input_box.py`, `tests/test_routing.py`, and
  `tests/fakes.py`. Cover interactive and piped commands, `/help`, default and
  Resume mode, footer, preserved context/Tier Pin, plan guidance, and build
  parity. Assert no Attempt for mode commands.
- At that seam, run a plan turn with allowed Workspace Tools, calculator,
  current_time, todo and webfetch (approved and rejected); then inject
  `write`, `edit`, and `shell` calls, including a mixed batch and later round.
  Check the denied calls have Tool error results and no file change, command
  execution or confirmation, even with shell enabled. Existing tool tests in
  `tests/test_workspace_tools.py`, `tests/test_shell_tool.py`, and
  `tests/test_webfetch.py` establish build-mode baselines.
- Check a turn with multiple Provider exchanges still offers the same allowed
  names; retrying after a switch uses the later mode. Confirm the existing
  Tool Confirmation, Strong Confirmation and Fetched-Content Warning behavior
  still passes in build. Run the full offline test suite.

## Out of Scope

Automatic or agent-initiated switching; persistence across Runs or in Resume
state; a new TUI, queued-input display or planning Tool; classifier, Provider,
Tier Config, and existing confirmation changes. The user-only local commands
such as `/config` and `/remember` are not model Tools and are not changed by
this feature.

## Further Notes

- `plan` is a restriction on built-in Tool execution by the agent, not a
  sandbox or a promise that reading files and using `webfetch` cannot disclose
  workspace content; the existing Network Tool confirmation remains important.
- The brief has no unresolved product questions. No ADR duplicates the mode
  choice: the brief is the source for that decision.
