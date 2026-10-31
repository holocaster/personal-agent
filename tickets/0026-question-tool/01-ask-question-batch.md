# 01: Ask and answer a bounded question batch in one routed turn

**What to build:** Let the agent in either Agent Mode pose one to four questions
in a single Tool call, show the entire batch to the interactive user, collect
one choice or free-text answer per question in the Input Box, and continue the
same routed turn with the ordered answers. Preserve piped tasks and existing
Tool Confirmation gates.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0026-question-tool.md` (R1–R6, Testing Decisions);
**ADRs:** ADR-0004 (inline Input Box), ADR-0005 (Call Log/Resume).

- [x] Register `question` in the Tool Registry in `plan` and `build`, with
      schema accepting exactly one to four `{text, choices?}` entries, text
      of 1–500 characters containing non-whitespace, optional one to six choice
      labels of 1–120 characters containing non-whitespace, and no additional
      fields. Bad input returns the normal schema Tool error before any
      Terminal interaction; the Tool does not request Tool Confirmation. (R1)
- [x] In an interactive Run show every numbered question and numbered optional
      choice before prompting for answers; use the Input Box, not piped lines
      or the confirmation callback. One answer per question in order: number
      selects the corresponding choice; arbitrary text remains valid even
      with choices; `text: ` disambiguates numeric free text. Re-prompt blank
      or over-1000-character input; sanitize model-supplied display text and
      do not silently truncate answers. (R2, R3)
- [x] Return one Tool result with ordered `{question, answer}` pairs inside an
      `answers` array, and let the Router send it on its ordinary Provider
      follow-up in the same turn (one follow-up per Tool round, not per
      question). In a piped Run return an interactive-input-required Tool
      error without advancing the input iterator. EOF partway through the
      batch returns one Tool error with no partial answers. (R3–R5)
- [x] On Ctrl-C while answering, interrupt the routed turn without a question
      result or follow-up, retaining logging/reporting for any Tools completed
      earlier in the execution batch. Keep the ordinary Tool result display,
      `tool_execution`, Turn End, Conversation, `/history`, and Resume path for
      completed question calls and errors. Do not create a separate store.
      (R5, R6)
- [x] Prove answers never grant Tool Confirmation: a subsequent or same-batch
      `write`, `edit`, `shell`, or `webfetch` call still requires its own
      existing confirmation; no mode change occurs. Test through `run_repl`
      with scripted Provider responses and interactive Input Box/piped input,
      covering one and four questions, choices/free text, all offered Tool
      names, Provider follow-up, malformed args and bounds, EOF, Ctrl-C,
      logging, `/history`, Resume and unaffected next piped task. Exercise
      schema errors at the Registry seam and verify Tool-result correlation
      in Provider follow-up serialization for OpenRouter, Anthropic, OpenAI
      and Gemini; run the offline suite. (R1–R6)
