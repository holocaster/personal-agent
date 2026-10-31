# 01: Switch Agent Mode per Run with a plan-safe Tool boundary

**What to build:** Give the user a local `/mode` command to switch between
investigation-only `plan` and the existing `build` behavior for subsequent
routed turns. Show the active mode in the interactive Terminal, preserve the
Session's Conversation and routing state, and ensure that plan-mode Tool calls
cannot change the workspace even when a Provider invents a forbidden call.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0025-plan-build-mode.md` (R1–R6, Testing Decisions);
**ADRs:** ADR-0004 (interactive Input Box), ADR-0005 (Resume/Call Log).

- [x] Add `/mode`, `/mode plan`, `/mode build` to the Terminal REPL. Report the
      current Agent Mode, list the command in `/help` and interactive command
      completion, reject malformed or extra arguments without changing mode,
      and keep it local (no Provider Attempt for a mode command). Piped input
      uses the same syntax and prints plain text, without a new UI. (R1)
- [x] Initialize mode to `build` on every Run, including Resume; do not persist
      mode to or replay it from the Call Log. Show the current mode in the
      interactive Status Footer, while preserving its existing tier/model,
      spend, Tier Pin and `/help` information. (R2)
- [x] Use a turn-scoped Agent Mode for routed work. A plan turn advertises only
      `list_files`, `read_file`, `search_text`, `calculator`, `current_time`,
      `todo`, `webfetch` at *every* Provider exchange; build advertises the
      existing Tool set with `PA_ENABLE_SHELL=0` still honored. Do not add a
      Provider call for selecting mode, or change classification, Tier Config,
      retry, Escalation or Provider selection. (R3, R5, R6)
- [x] Enforce plan mode in Tool execution too: `write`, `edit`, and `shell`
      calls by name produce a Tool error before argument validation,
      preparation, confirmation, or application, even when mixed with allowed
      calls, across Tool rounds and with shell registered. Leave ordinary
      unknown Tool handling, permitted Tool logging/results, and the existing
      `webfetch` Tool Confirmation path intact. (R3, R4)
- [x] In plan's System Prompt instruct the agent to discuss/investigate and,
      when asked to modify the workspace, tell the user to switch to `build`.
      Keep the existing date, Memory, Conversation Summary, Todo List, and
      fetched-content instruction. In build preserve Tool Confirmation,
      Strong Confirmation and Fetched-Content Warning unchanged. (R4, R5)
- [x] Switching modes affects only later routed turns, including a later
      `/retry`; keep the Conversation, Todo List, Tier Pin, and classifier
      behavior intact. Freeze mode for all exchanges and Tool calls within
      a turn. Compression continues to offer no Tools. (R6)
- [x] Test through the existing `run_repl` and fake Provider seam: command
      responses/help/completion/footer, default and Resume, no command
      Attempts, preserved Conversation/Todo List/Tier Pin, multiple exchanges
      and switch then retry, plan guidance and build parity. Exercise every
      permitted Tool, with approved and rejected `webfetch`, and forbidden
      Tool calls with valid and malformed arguments, in a mixed batch and
      later rounds; assert no forbidden confirmation, command execution or
      file change, and that denied results are logged. Reuse existing Tool
      tests for build confirmation regressions and run the full offline suite.
