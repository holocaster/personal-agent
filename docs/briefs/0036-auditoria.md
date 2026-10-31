# 0036 — Auditoria

## Goal

Make a Session's actions auditable from the Personal Agent's point of view, while optionally recording enough model-facing context to diagnose why a Provider produced an answer. The Call Log remains the only record used for Resume; detailed payloads live in a separate, opt-in JSONL file per Session.

## Scope

- Record small Audit Events in the main Call Log even when detailed tracing is off: submitted REPL commands and outcomes (including invalid commands), state changes from `/mode`, `/model`, `/config`, `/skill`, `/remember`, `/forget` and Shift+Tab, Tool confirmation approvals/rejections, errors, and already-recorded Attempts/Tool results. Preserve existing Resume semantics; never copy secrets entered through `/config` or the full text of `/remember` into new always-on events.
- An environment flag, off by default and evaluated separately for each Run, enables a second JSONL file alongside that Session's Call Log. Record explicit start/end of detailed coverage so a resumed Session with mixed enabled/disabled Runs cannot be mistaken for fully traced.
- For each Provider exchange, correlate a detailed record with its Attempt and capture the actual model-facing System Prompt, messages, Tool definitions, and answer, including failures where observable. Do not dump HTTP headers or raw vendor requests/responses. Include submitted sensitive local-command content only in the opt-in file when necessary to understand the action.
- Apply existing known-credential redaction to detailed records and new Audit Events; never log API keys intentionally. Other private text may be recorded under opt-in; do not claim to detect every secret. Keep the auxiliary file owner-only and outside Git by default. Document its location, format, access and sensitivity; no REPL reader required.
- Audit only operations Personal Agent can observe. For `shell`, record the command, approval and returned exit/output as visible to the agent, including any truncation marker; do not claim to know its external effects or capture full unbounded stdout. Record failed and rejected operations as outcomes, not fabricated successes.
- If detailed auditing is enabled and the auxiliary file cannot be written, visibly stop before further auditable actions; preserve the main Call Log and Resume. An interrupted process or failed write can leave an explicitly incomplete trace; do not invent missing results. Auxiliary files share Call Log retention, without automatic pruning in this feature.

## Out of scope

- Deterministic re-execution, external state snapshots, observing every effect of `shell`, keystrokes/spinner/terminal redraws, arbitrary raw Tool output beyond existing caps, cryptographic integrity or tamper-proof storage, a new audit-viewing REPL command, automatic retention, and new Provider billing calls.

## Settled decisions

1. Audit means complete coverage of actions observable by Personal Agent, not proof against local alteration or an OS-level activity monitor.
2. The Call Log remains canonical and stores compact events; full model-facing payloads require a per-Run opt-in auxiliary file correlated by Attempt.
3. Known API credentials are redacted; opt-in may still store private text unknown to the program. A failed audit write is surfaced and halts new actions.
4. Mixed coverage across Resumes and abnormal termination must be distinguishable from a fully completed trace.
5. Keep audit schema field names and fixed outcome/state values legible even when an API key coincidentally matches them. Redact credential material in user-controlled and external values, including dynamic dictionary keys in Tool arguments and detailed payloads. The user authorized one extra correction/review round for ticket 01 after its third `changes_requested` verdict to enforce this rule.

## Open questions

None for product scope. The planner owns the flag name, event schemas/correlation, handling of partial writes, and the smallest safe ticket slices under these constraints.
