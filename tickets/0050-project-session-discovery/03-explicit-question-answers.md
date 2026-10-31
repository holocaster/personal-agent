# 03: Offer Other and reject invalid Question option numbers

**What to build:** The Question Tool displays an obvious local Other choice, accepts literal custom answers, and reprompts out-of-range numeric selections instead of passing them to the model as answers.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0050-project-session-discovery.md`, Question Tool answers (R16–R19), Tests and documentation (R20), and Testing Decisions. **ADRs:** None specific; preserve existing Question Tool semantics.

- [x] Reproduce current behavior for four choices: `10` becomes a free-text answer. With the correction, `5` opens Other and `10` displays the valid range/reprompts without entering an answer in Tool output or Conversation.
- [x] Display all supplied question/choice labels before collecting answers, append `N+1. Other (custom answer)` locally for every choice question, and use `Custom answer <question number>: ` after its numeric selection. Six model choices permit the seventh local option without changing the model-supplied schema/arguments.
- [x] Selection uses trimmed signed/unsigned ASCII integer tokens, including leading zeros. Valid 1–N returns the original label; N+1 opens Other; 0/negative/out-of-range/enormous integer tokens reprompt safely. Ordinary noninteger text stays unchanged. Explicit `text: ` takes precedence and returns its nonblank suffix literally.
- [x] Custom answers are literal: numeric-looking `5`/`10`, `text: 5` and surrounding nonblank whitespace are returned as entered, with no recursive escape/selection parsing. Questions without choices keep direct numeric/free-text answers and the existing escape handling.
- [x] Both initial/custom prompts enforce nonblank and raw-answer length of at most 1,000 characters. Keep existing question/label/question-count/choice-count limits and string/text-only-object normalization; accepted answer result shape is unchanged.
- [x] Update Question Tool description and concise README explanation so local Other/custom answers and invalid numeric handling are discoverable. Rendering remains sanitized, and spinner stop/restart surrounds the entire interaction, including reprompts.
- [x] Preserve same-turn model continuation, provider Tool result correlation, accepted answer Call Log/replay, EOF errors, KeyboardInterrupt and already-completed partial batches, piped input handling and independence from Mutating/Network Tool Confirmation. No extra model retry is introduced by an invalid local selection.
- [x] Focused Question regressions cover the root-case inputs, whitespace/leading-zero/signed numeric selection, literal custom/escape/no-choice answers, six-choice Other, input bounds, EOF/interrupt during custom entry, and an Other `yes` followed by a separately rejected mutating Tool. Existing Question/input-box/affected Registry tests pass.

## Implementation notes

Use the existing `_make_question` interaction and `InputBox.ask` path; no alternate UI abstraction or dependency. Keep model arguments and answer payloads intact. Preserve other agents' changes, validate each increment, and add no unnecessary code comments.
