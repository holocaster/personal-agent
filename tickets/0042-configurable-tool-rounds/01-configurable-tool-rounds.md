# 01: Configure the Tool round limit through the environment

**What to build:** Replace the fixed eight-round limit with `PA_MAX_TOOL_ROUNDS`, defaulting to 50, using existing configuration loading and per-task snapshots.

**Blocked by:** None.

**Spec:** none (fast path)

## Acceptance criteria

- [x] Unset `PA_MAX_TOOL_ROUNDS` permits 50 executed Tool rounds and a final-answer exchange; a requested 51st round fails before Tool execution.
- [x] A positive decimal integer supplied through environment or the existing dotenv loading controls the limit, including values below and above 50.
- [x] Empty, zero, negative, fractional and nonnumeric values fail configuration loading with a readable message naming `PA_MAX_TOOL_ROUNDS`.
- [x] The configured limit survives configuration snapshots and existing runtime model/Provider/context edits. Counting remains per routed task, including all existing Tool round types.
- [x] The limit error displays the effective configured number; REPL usability and audit records for unexecuted Tool intent remain covered.
- [x] `.env.example`, `docs/ENV_VARS.md` and concise current-behavior documentation explain the variable and default. Existing regressions pass.

## Execution guidance

Use the existing TierConfig and router; no new module, dependency or runtime menu is needed. Preserve the independent per-response Tool call limit and existing failed-turn policy. Do not address the unrelated skill schema, error classification or generated ERP defects in this ticket.

The user prohibits commits and pushes without asking. Preserve all pre-existing working-tree edits; implementation and independent review remain uncommitted. Pre-change copies are available at `/tmp/personal-agent-0042-before` for review of this ticket's changes.
