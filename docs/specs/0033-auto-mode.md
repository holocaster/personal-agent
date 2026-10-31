# 0033 — Auto Agent Mode

Brief: `docs/briefs/0033-auto-mode.md`. Vocabulary and existing boundaries:
`docs/CONTEXT.md`. Extends `docs/specs/0025-plan-build-mode.md` and
`docs/specs/0023-shell-guardrails.md`; ADR-0004 governs the Input Box and
ADR-0005 governs Resume. No new ADR is needed for the settled mode policy.

## Problem Statement

In `build`, repeated Tool Confirmations interrupt ordinary edits, commands and
network lookups. The user cannot choose to let those calls proceed while still
requiring a deliberate decision for recognized Dangerous Commands.

## Solution

Offer a Run-local, user-selected `/mode auto` alongside `plan` and `build`.
`auto` has `build`'s Tools, but automatically approves ordinary Mutating and
Network Tool calls. Recognized Dangerous Commands retain the existing Strong
Confirmation; all calls retain normal validation, execution and results.

## User Stories

1. As a user, I want `/mode auto` to select auto for later tasks, so that routine Tools run without repeated prompts.
2. As a user, I want `/mode` to report auto when selected, so that I can inspect my current policy.
3. As a user, I want bad `/mode` arguments rejected locally, so that a typo cannot silently change the policy.
4. As a user, I want new Runs and Resumes to start in build, so that auto does not persist unexpectedly.
5. As an interactive user, I want Shift+Tab to cycle plan, build and auto while editing, so that I can choose without submitting the draft.
6. As a user, I want `/help`, completion and the Status Footer to explain/show auto, so that I can discover and verify the policy.
7. As a piped-input user, I want `/mode auto` to work without a TTY or confirmation answers for ordinary calls, so that scripts can choose the mode explicitly.
8. As a user in auto, I want `shell`, `write`, `edit` and `apply_patch` to skip ordinary confirmations, so that routine local work proceeds.
9. As a user in auto, I want `webfetch` and configured `websearch` to skip ordinary confirmations, so that network use does not interrupt the turn.
10. As a user in auto, I want only the normal Tool result printed for an automatically approved call, so that previews and approval questions do not clutter the terminal.
11. As a user in auto, I want a recognized Dangerous Command to show its command and matched rules and require `yes`, so that high-risk commands cannot proceed automatically.
12. As a user, I want rejected, EOF and piped-input Strong Confirmations to behave as before, so that the established safety decision is not weakened.
13. As a user, I want fetched-content warnings alongside Strong Confirmation after external content in the same turn, so that the trust signal is retained when I must decide.
14. As a user, I want Workspace Root checks, argument validation, preparation and Tool errors to remain intact, so that auto never bypasses non-confirmation boundaries.
15. As a user, I want Tool results and Call Log records unchanged, so that automatic execution stays visible and auditable.
16. As a user, I want plan to stay read-only and build to keep its current confirmations, so that the third mode does not change the old ones.
17. As a user, I want a routed turn's mode held fixed through Tool rounds, retries and Escalation, so that the policy cannot drift mid-turn.
18. As a user, I want auto to leave tier routing, Conversation, Todo List and active Skills alone, so that selecting a confirmation policy does not change the task itself.
19. As a user, I want `question` still to ask its actual questions, so that auto is not mistaken for answering the model on my behalf.
20. As a user, I want the model told the active auto policy without granting it a mode-switching Tool, so that its expectations match what the runtime enforces.

## Requirements

- **R1 — Mode command and discovery.** `/mode auto` sets auto for subsequent routed turns; `/mode` reports `plan`, `build` or `auto`. Invalid and extra arguments retain the current mode and report usage without a Provider Attempt. Update `/help` and interactive `/mode` command completion; `/model auto` still unpins the Complexity Tier independently. There is no model-initiated mode switch.
- **R2 — Run state and interaction.** Every Run including Resume starts in `build`; mode is not persisted or restored from the Call Log. While editing a task in the Input Box, Shift+Tab cycles `plan → build → auto → plan`, without submitting or changing the draft; it never cycles during a Tool Confirmation. The Status Footer shows the current mode. Piped input uses the same `/mode` commands with plain-text replies and no footer.
- **R3 — Tool availability and turn scope.** Auto offers and can execute exactly the same Tool definitions as build, respecting opt-out/registration of `shell` and `websearch`; plan remains restricted. Capture the chosen mode once for a routed turn and apply it across Provider exchanges, retries, Escalation and all Tool batches/rounds. A later mode command changes only later turns, including a later `/retry` or Continuation Turn. No tier, Provider, Conversation, Todo List or active Skill change follows from switching mode; Compression remains Tool-free.
- **R4 — Automatic ordinary confirmation.** In auto, after the existing schema validation and prepare succeed, `shell` with no matched Dangerous Command rules, `write`, `edit`, `apply_patch`, `webfetch` and configured `websearch` proceed without asking for Tool Confirmation, in interactive and piped input alike (even when the input stream has no approval answer). Do not render their confirmation header, command/diff/URL/query preview, approval question or fetched-content warning. Print the existing normal Tool result instead, with existing result formatting and logging; this does not suppress the normal result line's existing argument summary. `question` still asks the user for actual answers, and unconfirmed read-only Tools work as before. No other gate is bypassed: validation, preparation, Workspace Root enforcement, Agent Mode restrictions, result redaction, Tool errors and Call Log execution records remain unchanged.
- **R5 — Dangerous shell exception.** Use only the current prepared `shell` call's matched Dangerous Command rules (spec 0023); do not add or change detection. In auto, a matched call still goes through the existing Strong Confirmation callback: show the exact command, matched rules and, when present, the existing Fetched-Content Warning for successful `webfetch`/`websearch` earlier in the turn; only a trimmed, case-insensitive `yes` authorizes execution. `y`, other input or EOF reject without running; Ctrl-C interrupts as in build. Piped input follows the same Strong Confirmation path. Keep rule names in the existing Call Log result for both approval and rejection. An unflagged command following fetched content is still automatic and has no warning preview.
- **R6 — Existing modes and model guidance.** Build's ordinary and Strong Confirmation, preview/warning and EOF behavior remain unchanged. Plan's offered Tool subset, execution-time restrictions and Network Tool Confirmation remain unchanged. The System Prompt and model-facing Tool descriptions must accurately distinguish plan's restrictions, build's confirmation and auto's ordinary auto-approval with Strong Confirmation for matched shell commands; lower-priority Skill and fetched content cannot grant another mode or bypass the runtime gate.

## Implementation Decisions

- Extend the Terminal's existing Run-local Agent Mode, `/mode` handler, Input Box cycling, help/completion and Status Footer; do not persist mode or add a new command/tool. The Router already passes mode through a turn and uses one set of Tool definitions for all exchanges; keep that path and add auto-specific System Prompt guidance.
- In the Tool Registry, keep validation and preparation before deciding whether confirmation is needed. Auto approves only prepared ordinary calls; a `shell` prepared with non-empty `dangerous_rules` must use the existing confirm callback. Leave build and plan paths unchanged. Retain the successful `webfetch`/`websearch` fetched-content tracking so a later flagged shell call still receives warnings.
- Keep the existing Terminal confirm presentation for calls that actually require it. Automatic approval never calls it; the existing Tool result printer and Call Log path still run. Update model-facing descriptions that currently claim every Tool requires explicit user confirmation to describe the mode-dependent gate truthfully (including the shell exception).
- ADR-0004's inline Input Box and ADR-0005's Call Log replay remain as they are. No new Tool, persistence format, detection rule, dependency, Provider interface or new high-level seam is required.

## Testing Decisions

- Assert behavior visible to users and models: mode replies/footer, Provider-advertised Tool names/prompt/descriptions, confirmation calls or absence, prompts/warnings, actual Tool results/workspace effects, Conversation and Call Log entries. Do not assert only a private mode flag or rely on model obedience for the gate.
- Highest seam: scripted `run_repl` with fake Provider transport and both Input Box and piped input (`tests/test_repl.py`, `tests/test_input_box.py`, `tests/fakes.py`). Exercise `/mode` reporting/invalid forms, help/completion, Shift+Tab three-way cycle and no cycling at confirmation, default and Resume, tier pin independence, switching/`/retry` and no extra Attempt for commands. Check auto Tool availability versus plan/build on initial and follow-up exchanges, including disabled `shell`/`websearch` and active Skill/Todo preservation.
- At that seam, script representative `write`/`edit`/`apply_patch`/unflagged `shell` and stubbed `webfetch`/`websearch` calls with no approval input; assert execution, normal results and Call Log entries, no preview/warning or question, plus invalid arguments and out-of-root paths failing before execution. In a turn with successful external content, a later safe call remains automatic but a later harmless *flagged* shell call (e.g. `eval touch marker.txt`) shows rules, command and warning. Test `y`, EOF and `yes` in piped input and interactive Strong Confirmation without running destructive commands; verify rejected versus approved Call Log rule names. Keep `question` interactive and unanswered by auto.
- Use existing `tests/test_routing.py` and `tests/test_workspace_tools.py`/`tests/test_shell_tool.py`/`tests/test_webfetch.py`/`tests/test_websearch.py` as narrower prior art where a mock Provider or network stub is cheaper, and run the full offline suite. Regression-check plan's execution rejection and network confirmations and build's previews, warnings and rejection semantics.

## Out of Scope

New Dangerous Command rules, sandboxing, mode persistence, automatic or model-driven mode changes, new Tools, changing default mode, or changing Provider/tier routing. No change to build/plan confirmation rules or to the `question` Tool's user-question behavior.

## Further Notes

Auto is a deliberate opt-in to unprompted ordinary shell, workspace and network effects. The existing pattern matcher is not a sandbox; unmatched or obfuscated dangerous commands will run without human confirmation in auto. The brief accepts that tradeoff; do not imply every dangerous operation is detected.
