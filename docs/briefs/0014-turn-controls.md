# 0014 - Turn Controls

## Goal

Give the user direct control over routed turns: pin a tier when the Classifier
guesses wrong, undo or retry the last turn, and compress a long Conversation
instead of losing older turns at the Context Window cut. Inspired by Hermes'
`/model`, `/retry`, `/undo` and `/compress`, and DeepSeek Harness'
`compaction`. All three live in one feature by the user's choice.

## Scope

1. **Tier Pin**:
   - `/model <easy|medium|complex>` pins the tier for later routed turns, and
     the Classifier is skipped.
   - `/model auto` removes the pin.
   - `/model` with no argument shows the current pin or `auto`.
   - Escalation (ADR-0001) and the Budget Guardrail work as they do today.
   - The Status Footer shows when a pin is set.
   - The pin lasts for the Run only and is not written to the Call Log.
2. **Undo**:
   - `/undo` removes the most recent successful turn from the Conversation
     and writes a `turn_undone` entry.
   - With no turn to undo, it prints a local error.
3. **Retry**:
   - `/retry` re-sends the most recent routed task.
   - If that turn ended `ok`, it is first Undone, with the same `turn_undone`
     entry. If it ended `error` or `interrupted`, the task is simply sent
     again.
   - The Classifier runs again unless a Tier Pin is set.
   - With no previous task, it prints a local error.
4. **Compression**:
   - `/compress` replaces all but the two most recent turns with a
     Conversation Summary produced by the easy tier. The summary call is
     logged as a normal Attempt and counts toward the Budget Guardrail.
   - It writes a `conversation_compressed` entry carrying the summary.
   - The summary goes into the System Prompt, not into the messages.
   - `/history` shows the summary first.
   - A later `/compress` summarizes the previous summary together with the
     turns it replaces.
   - With two or fewer turns, it prints a local error and makes no call.
   - If the summary call fails, the Conversation is unchanged and the error
     is shown.
5. **Resume** (extends 0012): the Conversation is rebuilt as follows:
   - the latest `conversation_compressed` summary;
   - then the `ok` Turn Ends after the last `conversation_cleared` or
     `conversation_compressed`;
   - then each `turn_undone` removes the most recent remaining turn, applied
     in log order.
6. `/help`, Tab completion, and the README cover the new commands.

## Out of scope

- Pinning a raw `provider:model`.
- Automatic Compression.
- Undo of more than one turn per command. Repeating `/undo` is fine.
- Redo.
- Persisting the Tier Pin across Runs.

## Settled decisions

- The Tier Pin can only name a tier, never a raw model id, so Tier Config
  stays the single source of models.
- Compression is manual only. The existing Context Window cut stays as it is.
- The easy tier writes the summary. The summary call has local retries but
  no Escalation. It is a housekeeping call, not a routed task.
- The summary lives in the System Prompt, so no fake user or assistant
  message is added and Provider role ordering does not break.
- The original turns remain in the Call Log for audit.
- `/clear` also drops the Conversation Summary.

## Open questions

None.

## Routed during implementation

- README's Call Log paragraph has been stale since 0012 and does not list
  session_resumed, turn_end, conversation_cleared or turn_undone. The fix is
  folded into ticket 03, which also edits the README and adds
  conversation_compressed.
