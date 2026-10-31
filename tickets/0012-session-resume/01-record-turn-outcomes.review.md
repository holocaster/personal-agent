# Review: 01 - Record turn outcomes and clears in the Call Log

- ticket: 01
- reviewed_range: 728851ed2495c955c4a62bc1c009bf7e23457eae..cfdc6d188f4ce87e51c2881856f99a285f9ee311
- status: approved
- round: 1

## Criteria

All eight acceptance criteria pass.

## Findings (suggestions, non-blocking)

1. `test_tool_using_ok_turn_writes_turn_end_messages_with_tool_calls_and_results` does not assert that `turn_end` follows `tool_execution`. The order holds today because `route()` logs Tool executions before it returns.
2. The error-status tests assert substring containment rather than equality with the raw Router error.

## Checks

- Full suite at head_sha: 356 passed, 2 failed.
- Full suite at base_sha: 348 passed, the same 2 failed. The failures are pre-existing (`tests/test_provider.py` litellm pricing lookups) and unrelated to this ticket.

## Residual risks

- `write_turn_end("ok")` without messages would raise. Its only caller is the REPL, which always passes messages.
- A non-KeyboardInterrupt exception from `route()` leaves no Turn End. This is by design: the spec treats it as a crash marker.
