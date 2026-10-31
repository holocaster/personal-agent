# 01: Change Agent Mode throughout an interactive turn

**What to build:** Make Shift+Tab cycle Agent Mode during running provider/tool work, Tool Confirmation, questions and preview inspection, with the current mode applied at subsequent tool boundaries.

**Blocked by:** None.

**Spec:** none (fast path)

## Acceptance criteria

- [x] Shift+Tab cycles plan → build → auto → plan while editing a task, answering a Tool Confirmation or question, viewing a preview, and waiting for a provider/tool. Mode feedback updates promptly without submitting input or changing its draft. Secret prompts retain secrecy and history isolation.
- [x] The running turn uses the current user-selected mode at every subsequent tool boundary and provider exchange: auto skips ordinary confirmations; plan prevents mutating operations even if a provider requested them under an earlier mode; build restores confirmation. An already-running operation finishes normally.
- [x] Changing mode never substitutes for explicit approval of a pending confirmation. Its answer remains required; dangerous commands always require exact yes, including if switching to auto during their prompt. A switch to plan while an ordinary mutating confirmation is pending prevents its execution even after y. Question answers are preserved and never auto-filled.
- [x] Only one keyboard consumer owns terminal input at any time. Shift+Tab during busy work is processed while that work is still running; ordinary queued input remains available to later prompts. EOF/Ctrl-C retain interruption, continuation and cleanup behavior. No persistent background reader survives the task/Run.
- [x] Deterministic regression checks first reproduce blocked confirmation switching, then verify live changes during blocked provider/tool work, pending confirmation, questions and preview; same-batch policy changes, dangerous exact-yes behavior, plan gating, draft preservation and cancellation remain correct. Relevant existing terminal/router/registry/continuation/audit checks pass.
- [x] README and docs/CONTEXT.md describe the new timing and pending-approval behavior concisely. No dependency or unnecessary code comment is added.

## Evidence and constraints

Latest app log pa_log-20261005T213934Z-6jg5f7.jsonl contains 30 confirmations, five flagged dangerous, and a build→auto toggle only after the turn ended. Reproduction with create_pipe_input sending ESC[Zy to InputBox.ask returned y but never invoked on_mode_toggle. InputBox._toggle_mode gates on _reading_task; PromptSession runs only during prompts; route passes a fixed mode through the tool loop.

Installed prompt_toolkit is 3.0.53. Context7 official documentation confirms bindings are handled by a running Application/PromptSession. Use existing dependency input/event-loop facilities with minimal lifecycle changes; trace all affected callers before editing.

Implementation initially proceeded without commit/push authorization, preserving all pre-existing edits including feature 0046. The user subsequently authorized commit and push. Feature 0046 was committed separately as `deb9abbac7c13a42c651dfc33ee6c718a81338a9`, providing a Git baseline for independent review of this feature. The original snapshot remains at the directory recorded in /tmp/pa-0047-baseline-path. Do not restore or clean unrelated edits. Validation one check at a time.
