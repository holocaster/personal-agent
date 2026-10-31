# Review: ticket 0005-agentic-repl/02

## Round 1: changes_requested

status: changes_requested
reviewed_range: 84345366e063197d402fefc9c3579ca4eaaadffc..6f8589d7ae6bfde898ac66341aad49c5490bdcaf

13 of 14 acceptance criteria passed. Reviewer independently verified the
calculator's security boundary with 43 adversarial inputs (no
eval/exec/import/attribute/subscript/comprehension path survives), the
R13 bounded-loop gates, R14 pinning/retry (Tools executed once, outside
the retry loop), R15 Attempt/cost accounting, and Gemini's 3-round
thoughtSignature/part replay fidelity — all by reading `router.py`
directly and/or probing out-of-tree, not by trusting the green suite.

**Failing criterion (AC4):** Gemini wire translation dropped
vendor-returned call ids on both `functionResponse` and `functionCall`
parts, even when the vendor returned one. For a same-name multi-call
batch, response parts became byte-identical apart from the result
value — nothing on the wire let the model correlate results to calls,
so results could be silently transposed. Violated R08 ("Match each
result's name and any returned call ID").

Required change: emit `id` on the wire whenever it originated from the
vendor; keep omitting it for internally generated `gemini-call-N`
placeholders (never invent an id on the wire).

Non-blocking suggestions: `http.py`'s capability-rejection heuristic
message wording; three test-coverage gaps (multi-round Gemini replay
test only exercised one round; no cost-before-abort test; no
cross-Provider-from-Gemini follow-up test); `tools.py`'s hard-coded
"must be a string" type-mismatch message.

## Round 2 (correction): approved

status: approved
reviewed_range: 84345366e063197d402fefc9c3579ca4eaaadffc..49a85cf1dd65547dcd4a917829efdc0be1470caa

All 14 acceptance criteria pass. The correction adds
`id_is_generated: bool = False` to `ToolCall`/`ToolResult` in
`contract.py`, threads it through `router.py`'s normalization and
`tools.py`'s `execute_batch`, and `gemini.py` now emits `id` on
`functionCall`/`functionResponse` wire parts only when `id_is_generated`
is falsy.

Independently verified, not taken on faith:

- End-to-end wire probe: 2-round Gemini loop, two same-name calculator
  calls per round, vendor ids — both `functionCall` and
  `functionResponse` parts carry distinct, correctly paired ids across
  replay-continuation requests. Not transposed. Round-1 finding closed.
- Same probe with ids omitted from the vendor response: `gemini-call-`
  never appears in any outbound payload, on the fresh-loop or the
  replay-continuation path.
- Verified directly (not on faith) why a per-message flag was needed
  over a locally-scoped "generated ids seen" set: on the replay path,
  the tail handed to `_to_wire_contents` on a continuation is the
  `tool_result` messages only — the assistant message carrying the
  generated ids is already baked into `replay["contents"]` as raw
  parts, so a local set would be empty there and would leak the
  placeholder onto the wire. The implementer's claim was correct.
- `id_is_generated` leakage: recursive key search over every captured
  Gemini payload finds zero occurrences; cross-Provider probe replaying
  a generated-id Gemini turn into OpenAI and Anthropic finds the key in
  neither wire body (both build wire dicts field-by-field, so it cannot
  leak by construction). `/history` rendering ignores the field.
- Re-probed the calculator security boundary (~30 more adversarial
  inputs), loop bounds (17-call batch, 9th round, 8-round + final
  answer), R14/R15 retry/pinning/accounting, and the 20-turn boundary —
  all correct.

### Findings (both suggestions, non-blocking)

- `gemini.py`'s `functionCall` id-emission branch (as opposed to
  `functionResponse`, which the new test covers) has no regression
  test: deleting those two lines leaves the suite green. Reachable via a
  cross-Provider-into-Gemini follow-up or a fresh (non-replay) turn
  carrying vendor ids. Optional: add that test.
- `tools.py`'s `execute_batch`: three of five `ToolResult(...)`
  constructions were reformatted to multi-line, two left as long single
  lines — cosmetic inconsistency only, no repo lint config exists.

### Residual risks (informational, not blocking)

- Carried over from round 1, not re-escalated: Gemini's internally
  generated ids are index-based per round (`gemini-call-0` recurs every
  round). Reviewer's cross-Provider probe confirms the concrete
  consequence — duplicate `tool_call_id`/`tool_use_id` values across
  different assistant messages when replayed into OpenAI/Anthropic —
  but both APIs resolve against the immediately preceding assistant
  turn, so this is positionally unambiguous; no failure observed.
  `id_is_generated` makes a round-scoped id prefix a one-line fix if
  ever wanted.
- The `base_sha` recorded in `PROJECT_STATE.md` for this ticket was
  missing one character (`8434536e0...` instead of
  `84345366e0...`); reviewer caught it independently in both rounds.
  Fixed in the same commit as this approval.
- `_to_wire_contents` reads `id_is_generated` with `.get()`, so a
  message dict lacking the key defaults to "vendor-origin" (id
  emitted). Every current producer always writes the key and nothing is
  persisted to disk, so unreachable today — the unsafe default
  direction if a message ever arrives from another source.
