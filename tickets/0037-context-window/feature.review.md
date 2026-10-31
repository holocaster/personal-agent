# Whole-feature review: 0037/context-window

status: approved
reviewed_range: b3c36a1053e70a9b905d144265b621fd9f8b6359..bbdcbeeaf2cd0624fccae3f2e212f7ff1d4bda87
tickets: 01-06
findings: [notebook drift, fixed in the recording commit]

## Spec

R1-R11 and 06 AC1-AC6 pass. Published `max_input_tokens` is the known total (Claude 200000 -> ceiling 174000; gpt-5 and Gemini -> effective 250000, ceiling 224000; unknown routes 128000 assumed -> 102000). Soft trigger requires eligible older turns; a soft-only failure proceeds within the ceiling with no commit; recovery and above-ceiling failures still stop; persistence failures never dispatch.

## Cross-ticket probes

- Soft failure, transient exhaustion, Escalation to a smaller published-input route: re-resolved ceiling 174000, mandatory Compression reran, failed, stopped with no commit; `/usage` labels correct.
- Soft failure, dispatch, positive overflow: R8 recovery reran Compression, committed once, retried, answered; each summary Attempt charged once.

## Evidence

- `uv run --offline pytest -q` at bbdcbee: 1629 passed.
- `git diff --check` on the range: clean.
- README, ENV_VARS and CONTEXT agree with the code.

## Finding (fixed)

- suggestion: `.notebook/context-budget-contract.md` still stated the pre-06 capacity rule; updated by the orchestrator in the commit recording this review.

## Residual risks

- Input-as-total subtracts the output reserve, so small-window routes get lower ceilings than before (accepted conservative bound).
- After a soft failure, later grown Tool follow-ups or new routes may re-attempt paid Compression within one task (spec Further Notes allow).
- Accepted: soft-path persistence failure is fatal while the hard path is a non-fatal stop.
- Pre-existing, out of scope: `compress()` catch-all can leave a charged but unlogged summarization Attempt on hard/recovery/manual paths. Pending user routing.
