# 0026 — Question Tool

## Goal

Let the agent clarify requirements or ask for a user decision during a routed turn, then continue using the answers without forcing a separate user task for every question.

## Scope

- Add a model-facing `question` Tool available in both `plan` and `build`. One call can contain one to four questions. Present the batch together and collect one answer per question before returning the answers to the agent in the same routed turn.
- Each question can offer choices, but a free-text answer is always possible. One answer per question; no multiple selection within a question.
- Use the interactive Input Box for answers, distinct from Tool Confirmation. Do not treat answering as authorization for `write`, `edit`, `shell`, or `webfetch`; their existing gates remain in force.
- If the agent calls `question` in a non-interactive/piped Run, return a clear Tool error without consuming any further task lines. End-of-input during a question returns an error instead of inventing answers; Ctrl-C interrupts the turn like an interrupted Tool Confirmation.
- The answers flow through the existing Tool result, Conversation, Call Log, Resume, and Provider follow-up behavior. Keep output and question/answer sizes bounded for a terminal interaction.

## Out of scope

- A full-screen questionnaire UI, multiple selections for one question, or more than four questions in one call.
- Automatic mode changes or confirmation of other Tools by answering a question.
- A separate durable store for questions and answers, or a new Provider exchange per question in a batch.
- `websearch` and `apply_patch`; deliver them as separate subsequent SDD features, in that order.

## Settled decisions

1. Batch up to four questions per Tool call, so ten questions can be asked in three batches rather than ten Provider round trips.
2. Choices are optional; free-text answers remain available; one answer per question.
3. Piped input never becomes an implicit answer. The Tool reports that interactive input is required.
4. Ctrl-C interrupts the routed turn; EOF while asking yields a Tool error with no fabricated answers.
5. `question` is available in both Agent Modes and is not Tool Confirmation.

## Open questions

None for product scope. The planner owns argument/result shape, terminal presentation details, and acceptance criteria within these decisions.
