# 0026 — Question Tool

Brief: `docs/briefs/0026-question-tool.md`. Terminology: `docs/CONTEXT.md`.
Keep ADR-0004's inline Input Box and ADR-0005's Call Log/Resume contract.

**Choice compatibility amendment (2026-10-04):** R1 now accepts each choice as
a string or an object containing exactly `text`, a string. Both use the same
nonblank 1–120-character label bounds; extra object fields are rejected before
input. R2/R3 display and return the label, while R6 retains original arguments
in the existing Call Log. This removes repeated failures on text-only choices
observed in ERP sessions; the original contract below is preserved as history.

## Problem Statement

During a routed turn, the agent cannot obtain a clarification or decision from
the user as a Tool result. It must end its reply and wait for a new task, losing
the ability to continue that turn with the answer, and repeated questions incur
unnecessary Provider exchanges.

## Solution

Offer a `question` Tool in both Agent Modes. One call presents one to four
questions together in the interactive Terminal, then gathers one response per
question through the Input Box. Choices are optional and do not prevent a
free-text answer. Return the ordered answers in one Tool result and let the
same routed turn continue. Never use piped task lines as answers or treat an
answer as Tool Confirmation.

## User Stories

1. As an interactive user, I want the agent to ask for clarification in the
   current turn, so that it can continue with my answer.
2. As an interactive user, I want several questions presented as one batch, so
   that I can see the context before responding and avoid a Provider exchange
   per question.
3. As an interactive user, I want each answer associated with its question in
   order, so that the agent cannot confuse my decisions.
4. As an interactive user, I want optional choices visible for each question,
   so that I can select a suggested answer quickly.
5. As an interactive user, I want to type an answer even when choices are
   offered, so that I am not constrained by the agent's suggestions.
6. As an interactive user, I want one answer per question, so that a choice
   cannot be mistaken for a multiple selection.
7. As a user in `plan`, I want to answer questions without switching to
   `build`, so that the agent can clarify a plan before changing the workspace.
8. As a user in `build`, I want to answer questions without authorizing a
   later `write`, `edit`, `shell`, or `webfetch`, so that existing Tool
   Confirmation stays separate.
9. As a user running a piped Run, I want a clear Tool error without reading
   further lines, so that the next line still belongs to the REPL.
10. As an interactive user who reaches end-of-input, I want the Tool to fail
    rather than invent answers or return a partially answered batch.
11. As an interactive user pressing Ctrl-C while answering, I want the routed
    turn interrupted as with Tool Confirmation, not a fabricated Tool result.
12. As a user viewing `/history` or Resuming, I want completed question and
    answer exchanges preserved with the rest of the Conversation.
13. As a user inspecting the Call Log, I want a question Tool execution and
    Provider follow-up recorded using the existing format, so that the turn
    remains auditable.
14. As a user, I want long or malformed questions and answers bounded or
    rejected, so that a model cannot overwhelm the Input Box or Tool result.

## Requirements

- **R1 — Registry contract.** `question` is offered and executable in `plan`
  and `build`. Its arguments are exactly `{ "questions": [ { "text": string,
  "choices"?: string[] }, ... ] }`, with one to four entries, nonblank
  question text (at most 500 characters), optional one to six nonblank choice
  labels (at most 120 characters each), and no extra fields. Reject malformed
  or out-of-range arguments via the existing Tool schema error path, before
  any input is solicited. `question` does not require Tool Confirmation.
- **R2 — Interactive batch.** Show all numbered questions and, where present,
  their numbered choices above the interactive Input Box before requesting
  any answers. Then prompt once per question, in order, using the existing
  Input Box in a single-line answer mode (not the Tool Confirmation prompt).
  An option number selects only that question's matching label; other text is
  the free-text answer. A `text: ` prefix lets a user enter a literal numeric
  free-text answer when it would otherwise select an option. Empty/whitespace
  input is not an answer: prompt again. Keep model-supplied display text
  terminal-safe using the Terminal's existing control-character sanitization.
- **R3 — Bounded answers and result.** Accept at most 1000 characters per
  answer; overlong answers are not accepted and are prompted for again. Do
  not truncate an answer silently. Return one ordered Tool result of the form
  `{ "answers": [ { "question": <original text>, "answer": <selected label
  or entered text> }, ... ] }`. The result has exactly one entry per question
  and is passed back in the existing Provider follow-up, not a separate
  exchange per question. Preserve free-text answers without interpreting them
  as commands or approvals.
- **R4 — No piped consumption.** When there is no interactive Input Box,
  calling `question` returns a clear Tool error stating interactive input is
  required, without reading from the REPL's piped input iterator. The normal
  Tool result and follow-up path can report that error to the agent; later
  piped task lines remain available as tasks.
- **R5 — EOF and interruption.** EOF at any answer prompt yields one Tool
  error for the whole batch, without partial/fabricated answers; the agent may
  receive it in the same turn's ordinary Tool follow-up. Ctrl-C propagates as
  KeyboardInterrupt: the routed turn gets an `interrupted` Turn End, no
  fabricated question result or Provider follow-up, and already completed
  Tools in the same execution batch remain logged/reported as today.
- **R6 — Existing record and gates.** A successful or failed question Tool
  execution flows through the existing Tool result display, Call Log
  `tool_execution`, Conversation messages, Turn End, `/history`, Resume and
  Provider follow-up for all supported Providers. Provider-specific Tool
  serialization must still correlate this call's result to its call id. An
  answer is never a Tool Confirmation for `write`, `edit`, `shell` or `webfetch`;
  these Tools retain their existing execution gates even when requested in the
  same or a later batch. Do not persist an additional questionnaire store or
  alter Agent Mode.

## Implementation Decisions

- Register `question` in the Tool Registry and add it to plan's allowed Tool
  names. Use the same schema for Provider advertisement and Tool validation.
  Keep input acquisition as a callback supplied by the Terminal to the
  Registry, separate from the existing Tool Confirmation callback. The
  Registry can return a Tool error if that callback is unavailable; it should
  not access stdin directly.
- The Terminal callback presents a whole validated batch, suspends and resumes
  the spinner around the interaction, and uses the interactive Input Box's
  existing inline single-line reading facility. It never calls `next(lines)`
  for question answers. Input Box remains the only interactive reader per
  ADR-0004. Reuse Terminal sanitization for displayed untrusted labels and
  questions; the returned values retain their actual text.
- Use a Tool execution error for EOF and leave Ctrl-C uncaught at the Tool
  boundary. Preserve the current partial-results handling for interruption
  after other completed calls in an execution batch. There is no new Call Log
  entry shape or Resume reader: existing Tool execution and successful Turn
  End messages suffice per ADR-0005.
- Keep the Router's existing Tool loop and the Provider Contract unchanged;
  hand the question callback alongside confirmation to the execution batch.
  The Provider receives only one Tool result for the call; existing follow-up
  serialization handles that result across the supported Providers. Existing
  Tool round and per-round call limits still apply.

## Testing Decisions

- Prefer observable turn outcomes to internal callback wiring: validate
  advertised names, displayed questions/choices, prompts, returned ordered
  answers, Tool errors, Provider follow-up messages, Call Log entries and
  reconstructed Conversation. Avoid asserting implementation details of the
  Input Box beyond its visible interaction.
- **Highest seam:** exercise `run_repl` with scripted Provider Tool calls and
  interactive Input Box test doubles/pipe input, plus the existing piped Run
  harness. Prior art: `tests/test_repl.py`, `tests/test_input_box.py`,
  `tests/test_routing.py`, `tests/test_tools.py`, `tests/fakes.py`. Check
  one-/four-question batches, choice vs free text, plan/build offerings, one
  Provider follow-up for a whole batch, and next task preserved after piped
  rejection. Test argument bounds and malformed calls at the Tool Registry
  seam, which is also how existing schema checks are tested. Check existing
  Provider-specific follow-up serialization for OpenRouter, Anthropic, OpenAI
  and Gemini using their current fake transport tests.
- At the same routed-turn seam, check EOF after at least one entered answer,
  Ctrl-C with a previously completed Tool in the same execution batch, and
  subsequent confirmed Tools requiring their own approval. Inspect Call Log,
  `/history`, and Resume for completed answers and errors, ensuring no
  invented answer or extra durable store. Run the offline test suite.

## Out of Scope

Full-screen questionnaire UI, multi-select choices, more than four questions
per call, automatic Agent Mode changes, implicit confirmation, a new Provider
exchange for each question, and a separate question store. `websearch` and
`apply_patch` are later SDD features, not part of this spec.

## Further Notes

The brief settles the product behavior; the schema, size limits and inline
presentation above are implementation-level choices. No new ADR is needed:
this keeps the existing Tool Registry, Input Box and Call Log seams.
