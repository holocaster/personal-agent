# Review: ticket 0007-session-call-log/03

## Round 1: changes_requested

status: changes_requested
reviewed_range: 19b3d2adaeae43e151b1b954da6f13422f243aef..acaa7b5f818cfa62f22b35533ba6bd17970301d2

9 of 11 criteria passed. The Tool-execution half of the ticket was
correct and well evidenced (ordering, correlation, rejected-vs-executed
`arguments`, wholesale-rejection suppression, "Tool execution is not
an Attempt"). Failed: `tool_calls[*].arguments_raw` on attempt lines
was emitted verbatim from `ToolCall.arguments_raw`, which
`chat_completions.py` sets on every call whether or not parsing
succeeded — so the field signalled "which provider answered" instead
of "parse failed", contradicting ticket criterion 2 and spec R06. The
README's documentation of the field was accurate to intent but not to
the shipped code.

Required change: null `arguments_raw` in the Call Log projection
whenever `call.arguments is not None`, leaving `ToolCall.arguments_raw`
itself and `_normalize_assistant` (the wire/replay projection)
untouched.

The implementer's own test-file deviation
(`tests/test_routing.py::test_attempt_numbering_continues_across_tool_exchanges_within_one_tier`,
filtering `type == "attempt"` before indexing) was independently
verified as a legitimate minimal fix forced by this ticket's own new
`tool_execution` line type — not scope creep.

## Round 2 (correction): approved

status: approved
reviewed_range: 19b3d2adaeae43e151b1b954da6f13422f243aef..29f01e9508979537f8695d0e9d817772d8f734ab

All 11 acceptance criteria pass. The fix is one expression in
`router.py`'s `_tool_calls_for_log`:
`"arguments_raw": call.arguments_raw if call.arguments is None else None`.

Independently verified, not taken on report — reviewer's own probe
tests drove `route()` through the real `install_fake_urlopen` seam and
read the actual Session file off disk:

- Successful parse (OpenRouter, where the wire `arguments_raw` **is**
  populated): now logs `arguments_raw: null`.
- Genuine parse failure: still logs the raw string.
- Mixed three-call batch: `arguments_raw` came out per-call
  (`[None, "oops", None]`), not flattened across the whole line.
- Anthropic (never sets `arguments_raw` on the wire): unchanged,
  `null`, now for the correct reason.
- Scope confinement confirmed: `ToolCall` in `contract.py` is
  byte-identical to base; `_normalize_assistant` still emits
  `arguments_raw` verbatim for the wire/replay path; `_tool_calls_for_log`
  has exactly one caller (the Call Log line), so the new rule cannot
  leak elsewhere.
- No regression in the rest of the function: key-set stability,
  Attempt numbering, answers, line order, and rejected-vs-executed
  `arguments` all re-verified against captured files, not just the
  suite (280 tests pass).

### Findings (suggestion, non-blocking, carried over from round 1)

- `router.py`'s `_log_tool_execution`: `result.content.get("error")`
  assumes every error `ToolResult` carries a dict — true for all five
  current constructions in `tools.py`, but a future string-content
  error result would raise `AttributeError` mid-loop. Optional:
  tolerate non-dict error content.
