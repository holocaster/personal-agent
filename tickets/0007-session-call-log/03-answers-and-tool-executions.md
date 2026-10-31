# 03: Record answers, requested Tool calls, and Tool executions

**What to build:** A Session's file stops hiding the interesting half of the flow. Each Attempt line gains the assistant's answer text and the Tool calls that response requested, and every locally executed Tool call gets its own line with its arguments and its result or error. Reading a Session file top to bottom now replays the real sequence: the model asked for the calculator, here is what it was given, here is what it returned, here is the follow-up Attempt and the final answer.

**Blocked by:** 01 (one Call Log file per Session) — the envelope and per-Session file it establishes. Independent of 02; either can land first.

**Spec:** `docs/specs/0007-session-call-log.md` (R04, R06, R07, R10, R12); **ADRs:** `docs/adrs/0003-call-log-per-session.md`, `docs/adrs/0002-hand-rolled-provider-contract.md`.

- [x] Each `attempt` line gains `answer`: the assistant's text for that exchange, `null` when the Attempt failed or the response carried no text.
- [x] Each `attempt` line gains `tool_calls`: an ordered list of the Tool calls that response requested, each with `id`, `name`, `arguments` (the parsed object, or `null` when the Provider's arguments were not valid JSON) and `arguments_raw` (the raw string when parsing failed, otherwise `null`). It is an empty list when no Tool calls were requested and `null` when the Attempt failed.
- [x] Every existing `attempt` field keeps its current meaning and value, and all `attempt` lines still share exactly one key set.
- [x] One `tool_execution` line is written per result the Tool boundary returns for a batch, in execution order, carrying the envelope plus `tool_call_id`, `name`, `arguments` (the object passed to the Tool, `null` when the call was rejected before execution), `ok`, `result` (the Tool's returned object when `ok`, else `null`) and `error` (the error text when not `ok`, else `null`).
- [x] Calls the Tool boundary rejected — unknown Tool name, invalid arguments, wrong argument types, extra keys — appear as `ok: false` lines with the error text the model was handed, so the record matches the exchange rather than omitting the rejection.
- [x] A batch rejected wholesale as a protocol failure (missing or duplicate Tool call ids, spec 0005 R12) executes nothing and writes no `tool_execution` line; the requesting `attempt` line already records what was asked.
- [x] `tool_call_id` on each `tool_execution` line matches an `id` in the requesting `attempt` line's `tool_calls`, proven across a multi-call batch and across consecutive Tool rounds.
- [x] Line order is: the requesting `attempt` line, then its `tool_execution` lines in execution order, then the follow-up `attempt` line.
- [x] Tool execution is still not a Provider Attempt: it writes no `attempt` line, does not advance the Attempt counter within the tier, and does not enter Budget Guardrail accounting (spec 0005, R15). The existing Tool-loop and Attempt-numbering tests pass unchanged apart from path resolution.
- [x] Both a calculator round and a clock round are driven end to end through the existing `model_router.providers.http.urlopen` fake and asserted on the resulting file — no mocking of `call_log` out of the Router.
- [x] The README's Call Log section documents the `answer` and `tool_calls` fields on Attempt lines and the `tool_execution` line type with its fields.
