# 0002 - Router reliability

Brief: `docs/briefs/0002-router-reliability.md`
Glossary and cross-cutting decisions: `docs/CONTEXT.md`
ADRs: `docs/adrs/0001-escalate-on-technical-failure-only.md`

## Problem Statement

Today the Router makes exactly one Provider call per task and gives up on anything that goes wrong. A rate-limit response, a 502 from an overloaded upstream, or a network timeout — none of them a statement about whether the task is answerable — ends the task with `Error: ...` and the user has to retype it. The user is paying the full cost of a failed call and getting nothing back.

There is also no recovery path when a tier genuinely cannot complete a task: if the Classifier sends a hard task to `easy` and that model's endpoint is down, the task fails even though the `complex` model was sitting there available. And the moment a recovery path exists, an unbounded one is its own problem — a session that silently escalates every flaky task to the most expensive tier is a bill the user did not agree to.

The user wants a single flaky call to stop costing them a task, without that turning into an open-ended spend.

## Solution

Three behaviours layered onto the same code path the Router already runs, all invisible to the user until something fails.

**Retry.** A Provider call that fails transiently is retried — up to three Attempts at that Complexity Tier, with exponential backoff between them (0.5s, then 1s, then 2s). Transient means network timeout or HTTP 429/500/502/503/504. Anything else — a 400, a 401, a malformed response — is a real answer from the Provider about this request, and fails on the first Attempt without burning the other two. Retry applies uniformly at every tier, whether it is the tier the Classifier picked or one the Router escalated to.

**Escalation.** When every Attempt at a tier has failed, the Router moves up the Complexity Tier order (easy → medium → complex) and starts a fresh set of Attempts at the next tier. The trigger is technical failure only — `RouteResult.error is not None` — never a judgment about whether the answer's content looks right (ADR-0001). Nothing follows `complex`: when the top tier's Attempts are also exhausted, the contract is exactly today's, `RouteResult(error=...)` and the REPL prints `Error: {result.error}`.

**Budget Guardrail.** An optional ceiling, set by `ROUTER_BUDGET_USD`, on the cost accumulated during one REPL session. Unset means no guardrail and today's behaviour exactly. When set, it gates one thing only: Escalation to a more expensive tier. It never blocks the tier the Classifier originally picked, so a configured budget can never stop the user from getting a first answer — it only stops the Router from spending more than the user asked for while chasing a failure.

**Call Log.** Because a single typed task can now produce several Provider calls, the log records one entry per Attempt — every retry, every escalated tier — rather than one summary entry per task. Existing keys are unchanged; one new key identifies the Attempt within its chain.

The REPL's output is unchanged on success: one routing line naming the tier that actually answered, then the answer.

## User Stories

1. As a terminal user, I want a call that fails with a network timeout to be retried automatically, so that a blip on my connection does not cost me a task.
2. As a terminal user, I want a call that fails with HTTP 429 to be retried, so that a momentary rate limit does not read as a permanent failure.
3. As a terminal user, I want calls that fail with HTTP 500, 502, 503 or 504 to be retried, so that an overloaded upstream does not end my task.
4. As a terminal user, I want up to three Attempts at a Complexity Tier, so that recovery is bounded and I am never stuck waiting on an infinite loop.
5. As a terminal user, I want a wait between Attempts that grows (0.5s, 1s, 2s), so that a retry storm does not make an overloaded Provider worse.
6. As a terminal user, I want a 400 or 401 to fail on the first Attempt, so that I am told about a bad key or a bad request immediately instead of 3.5 seconds later.
7. As a terminal user, I want a malformed or unparseable Provider response to fail on the first Attempt, so that a broken contract is not mistaken for a transient one.
8. As a terminal user, I want retry to work identically at every Complexity Tier, so that the reliability of my task does not depend on which tier the Classifier picked.
9. As a terminal user, I want a task whose Attempts are exhausted at `easy` to be tried at `medium`, so that one dead endpoint does not fail a task another tier could have answered.
10. As a terminal user, I want a task whose Attempts are exhausted at `medium` to be tried at `complex`, so that Escalation walks the whole ladder rather than stopping one rung short.
11. As a terminal user, I want a task the Classifier sent straight to `complex` to have no Escalation path, so that the Router does not invent a tier that does not exist.
12. As a terminal user, I want Escalation triggered only by technical failure, so that a short-but-correct answer is never second-guessed and re-billed at a higher tier (ADR-0001).
13. As a terminal user, I want the routing line to name the tier that actually produced the answer, so that I can see an Escalation happened without reading the log.
14. As a terminal user, I want the answer from an escalated tier returned normally, so that a recovered task is indistinguishable from one that worked first time.
15. As a terminal user, I want the final failure after `complex` to print the same one-line `Error:` I get today, so that nothing about my failure experience regresses.
16. As a terminal user, I want the REPL to stay alive through retries and Escalation, so that a hard-failing task still returns me to the prompt.
17. As a terminal user, I want Ctrl-C during a retry or backoff wait to abort the whole task, so that I am not held hostage by a chain of Attempts I no longer want.
18. As a terminal user, I want a successful first Attempt to behave exactly as it does today with no extra latency, so that the common path pays nothing for the failure path.
19. As a terminal user, I want an optional `ROUTER_BUDGET_USD` ceiling on one session's spend, so that an escalating session cannot quietly run up a bill.
20. As a terminal user, I want `ROUTER_BUDGET_USD` unset to mean no guardrail at all, so that I get today's behaviour unless I opt in.
21. As a terminal user, I want the Budget Guardrail to only block Escalation, so that a spent budget can never stop me getting a first answer at the tier I was classified into.
22. As a terminal user, I want the budget window to be this REPL session only, so that yesterday's spend does not block today's first Escalation.
23. As a terminal user, I want a blocked Escalation to tell me it was the budget, naming the tier that was not tried, so that I can tell "the models failed me" apart from "I capped myself".
24. As a terminal user, I want the budget to accumulate the cost of every Attempt including retries, so that the ceiling reflects what I actually spent, not what one call cost.
25. As a terminal user, I want Attempts whose cost the Provider did not report to count as zero rather than crash the session, so that missing usage data never breaks routing.
26. As a terminal user, I want `ROUTER_BUDGET_USD` documented in the README alongside the other environment variables and marked optional, so that I can find it without reading the code.
27. As a terminal user, I want every Attempt written to the Call Log as its own line, so that I can count how many retries a task really took.
28. As a terminal user, I want each Call Log line to carry the tier and the Attempt number within that tier, so that I can reconstruct an Escalation chain from the file.
29. As a terminal user, I want the existing Call Log keys unchanged, so that whatever shell one-liners I already use keep working.
30. As a terminal user, I want each Attempt's own latency and cost logged, so that I can see what the failure path cost me separately from the successful call.
31. As a terminal user, I want failed Attempts logged with `ok: false` and their error text, so that I can tell which specific error triggered the retries.
32. As a maintainer, I want the retry decision to depend only on the exception the Provider call raised, so that "is this retryable?" is a pure, directly testable function.
33. As a maintainer, I want backoff sleeps replaceable in tests, so that the suite asserts retry behaviour without spending real seconds.
34. As a maintainer, I want the whole feature tested through the one existing HTTP-boundary fake, so that no new mock layer enters a codebase that has exactly one seam.
35. As a maintainer, I want the tests to assert the sequence of model IDs that reached the wire, so that an Escalation regression fails loudly rather than passing on a stub.
36. As a maintainer, I want the Call Log asserted by reading the written file, so that the per-Attempt format is tested as the artifact a user will parse.
37. As a maintainer, I want `call_openrouter` to stay a single HTTP call with no retry inside it, so that the Router remains the one place that knows about Attempts, tiers and logging.
38. As a maintainer, I want the Budget Guardrail state to be an explicit object passed into the Router, so that there is no module-level mutable spend counter and tests need no reset ritual.
39. As a maintainer, I want the manual tier override left unbuilt, so that it is designed as its own feature rather than smuggled in beside Escalation.

## Implementation Decisions

**Where retry lives.** The retry loop lives in the Router, not inside the Provider call. The brief phrases it as "`call_openrouter()` gets up to 3 Attempts", and the observable behaviour is exactly that — but the loop is placed one level up because each Attempt must be individually timed and written to the Call Log, and the Call Log is the Router's job. `call_openrouter` stays what it is today: one HTTP request, one response, raises on failure. This keeps a single module (Router) owning the whole Attempt → Escalation → log chain and keeps the Provider module free of tier, budget and logging concepts.

**Retryability predicate.** A pure function living with the Provider call, since it is the module that owns the `urllib` vocabulary: given an exception, return whether it is transient. True for a timeout (`TimeoutError` / `socket.timeout`, and `URLError` wrapping one) and for an `HTTPError` whose `code` is 429, 500, 502, 503 or 504. False for everything else, including all other `HTTPError` codes, `KeyError`/`IndexError`/`JSONDecodeError` from parsing a malformed response, and any exception type the predicate does not recognise. The default is "not retryable" on purpose: an unrecognised failure is more likely a bug or a permanent contract break than a blip, and retrying it burns money three times.

**Attempt budget and backoff.** Three Attempts per tier. Backoff is slept *between* Attempts only — 0.5s after the first failure, 1s after the second — so a first-Attempt success adds zero latency and a fully exhausted tier sleeps 1.5s in total, not 3.5s. The documented "0.5 / 1 / 2" sequence is the module-level constant; the third value applies to nothing today and exists so the Attempt budget can be raised without re-deriving the schedule. Both the Attempt count and the backoff sequence are module-level constants in the Router.

**Escalation.** Complexity Tier order is `easy → medium → complex`, expressed as an explicit ordered sequence in the Tier module (not the enum's declaration order implicitly, and not a `next_tier` field on each member — the ladder is a property of the ordering, not of a tier). `route()` iterates the ladder from the Classifier's tier to the top. For each tier: run up to three Attempts. On success, return immediately. When Attempts are exhausted, consult the Budget Guardrail and either move to the next tier or stop. When the last tier's Attempts are exhausted, return `RouteResult` with the last tier's tier/model and the last Attempt's error text — byte-identical in shape to today's failure result.

**Budget Guardrail.** A small module with two pieces:

- `load()` reads `ROUTER_BUDGET_USD` from the environment and returns `None` when it is unset or empty, otherwise a guardrail object holding the limit and a running total starting at zero. A value that is present but not a valid positive number is a startup error, reported the same way missing Tier Config variables are today — a clear message before the first prompt, not a surprise mid-session.
- The guardrail object accumulates the cost of every Attempt (`record(cost)`, ignoring `None`) and answers one question (`allows_escalation()` — is the accumulated total still below the limit?).

`__main__` loads it once at startup and hands it to `run_repl`, which passes it into every `route()` call, so one object spans the session and dies with the process. `route()` takes it as an optional trailing parameter defaulting to `None`, meaning "no guardrail" — so every existing call site and test keeps working unchanged.

**Why the check is "already spent >= limit" and not "would the next tier exceed it".** There is no price table in this codebase — Tier Config maps a tier to a model ID, not to a cost, and cost is only known after a call returns. So the only deterministic rule available is: if a budget is configured and the session's accumulated spend has reached the ceiling, do not escalate. This can overshoot the ceiling by the cost of the Attempts that carried it over, which is accepted: the guardrail's job is to stop an escalating session from running away, not to be an exact accountant. Building a price table to predict the next tier's cost is out of scope.

**Blocked-Escalation result.** No new field on `RouteResult`. When the guardrail blocks, `route()` returns `RouteResult` carrying the tier and model of the tier that just failed, with `error` set to `budget exceeded, not escalating to {tier}` naming the tier that was *not* tried. The REPL prints it through the existing `Error: {result.error}` path with no REPL change. The underlying technical errors that led there are not folded into this string — they are already one line each in the Call Log, and the REPL error line stays a single readable sentence.

**No Call Log entry for a blocked Escalation.** The Call Log records Attempts, and a blocked Escalation is precisely the absence of an Attempt. A reader reconstructs it from the chain ending at a non-top tier with its Attempts exhausted; `ROUTER_BUDGET_USD` being configured is the other half of that story and lives in the user's shell, not the log.

**Call Log schema.** One entry per Attempt. Every existing key keeps its name, type and meaning — `timestamp`, `task`, `tier`, `model`, `latency_ms`, `cost`, `prompt_tokens`, `completion_tokens`, `ok`, `error` — now scoped to a single Attempt rather than a whole `route()` call. `latency_ms` measures that one Attempt's Provider call, excluding backoff sleep. One key is added: `attempt`, a 1-based integer counting Attempts *within the current tier*, resetting to 1 on Escalation. Together with the existing `tier` key this is the "tier + attempt number" identity the brief asks for, without duplicating tier into a compound string. `task` repeats across every entry in a chain, which is what makes the chain groupable with ordinary line-oriented tools.

**Modules touched.** Router (the Attempt loop, the Escalation ladder, the guardrail checks, per-Attempt logging), Provider call (the retryability predicate only — the HTTP call itself is unchanged), Call Log (the new `attempt` key), Tier (the explicit tier ladder), REPL (accepts and forwards the guardrail; printing unchanged), `__main__` (loads the guardrail, validates `ROUTER_BUDGET_USD`), plus a new Budget Guardrail module. README gains `ROUTER_BUDGET_USD` and a short description of retry and Escalation behaviour.

**Ctrl-C.** `KeyboardInterrupt` is not an exception the retry loop handles — it propagates out of `route()` to the REPL's existing handler, which prints `Interrupted.` and returns to the prompt. This means Ctrl-C during a backoff sleep or a later Attempt aborts the entire chain, not just the current Attempt, which is the intent: the user is saying "stop working on this task". Attempts already completed keep their Call Log entries; the interrupted one gets none, consistent with today's behaviour.

## Testing Decisions

**What a good test looks like here.** The same standard as feature 0001: drive the system at its outermost useful entry point and assert what an external observer could see — the sequence of HTTP requests that left the process, the lines in the Call Log file, and the text written to the REPL's output stream. Do not assert that the Router called the retryability predicate, do not count invocations of internal helpers, and do not reach into the guardrail's running total when the Call Log or the printed error already proves the behaviour.

**Seam — the existing one, unchanged.** Tests keep using the single `install_fake_urlopen` fixture that replaces `urlopen` in the Provider module. It already returns a scripted list of per-call outcomes and already raises any `BaseException` instance in that list, so a retry/Escalation scenario is expressed by handing it a list like `[HTTPError(503), HTTPError(503), HTTPError(503), "escalated answer"]` and then asserting which model IDs the four captured requests carried. This is exactly the seam feature 0001 established, and the whole feature is testable through it: no fake Router, no fake `call_openrouter`, no fake Budget Guardrail. Adding any of those would stop the tests from verifying that the escalated tier's model ID actually reached the wire, which is the feature's central claim.

**Second seam — the clock, deliberately narrow.** Backoff sleep is referenced through a module-level name in the Router so tests can replace it with a no-op (or a recorder, for the one test that asserts the delay sequence). Without this, every retry test costs 1.5 real seconds. This is a clock seam of the same kind as patching `urlopen` — replacing a call into the outside world at the boundary — not a new architectural abstraction, and nothing else about the Router is faked. `time.monotonic` stays real; no test asserts an exact `latency_ms`, only that it is a number.

**Fixture extension.** `install_fake_urlopen` gains only what the new scenarios need: a way to express "raise this for every remaining call" so an all-tiers-fail test does not have to spell out nine identical items. Everything else about the fixture and `FakeOpenRouterResponse` is reused as-is.

**Coverage.**

- *Retryability predicate*: direct unit tests. Each of 429/500/502/503/504 is retryable; 400/401/403/404 are not; a timeout is; a `URLError` wrapping a timeout is; a parse-shaped exception is not; an unknown exception type is not.
- *Retry, through the seam*: a transient failure followed by success yields the answer with two requests sent, both carrying the same model ID; three transient failures at `easy` produce three requests at the easy model before anything else happens; a non-retryable failure produces exactly one request; a success on the first Attempt produces exactly one request and no sleep.
- *Backoff*: with the sleep recorded, an exhausted tier slept `[0.5, 1]` — asserting the schedule and that no sleep follows the final Attempt.
- *Escalation, through the seam*: exhausting `easy` sends the next requests to the medium model and then the complex model, in that order; a success at `medium` returns that answer and the REPL routing line names `medium`; a task classified straight to `complex` that exhausts its Attempts sends exactly three requests and never escalates; all tiers exhausted returns an error result whose text is the last Attempt's error and prints one `Error:` line.
- *Call Log*: a chain that retried twice then escalated and succeeded writes one line per Attempt, in order, with `attempt` running 1,2,3 at `easy` and restarting at 1 for `medium`; failed Attempts carry `ok: false` and an error string, the successful one `ok: true` and a null error; every line carries the same `task`; the existing key set is present and unchanged.
- *Budget Guardrail*: with `ROUTER_BUDGET_USD` unset, an exhausted tier escalates (proving the default is today's behaviour); with a ceiling already reached, an exhausted `easy` tier does not send a medium request and the result's error names the blocked tier; the Classifier's own tier is still called in full even when the ceiling is already reached, including its retries; costs from Attempts accumulate across several tasks in one REPL session, so the second task can be blocked by what the first one spent; a non-numeric or negative `ROUTER_BUDGET_USD` is reported at startup and exits non-zero.
- *REPL*: a session driven through `StringIO` where the first task escalates and succeeds prints the escalated tier's routing line and answer; a session where everything fails prints one `Error:` line and continues to the next task.

**Prior art.** `tests/test_routing.py`, `tests/test_call_log.py` and `tests/test_repl.py` from feature 0001, plus the `install_fake_urlopen` / `tier_env` / `_isolate_router_log` fixtures in `tests/conftest.py`. New tests for this feature extend those files rather than introducing a parallel structure.

## Out of Scope

Everything the brief lists, restated for the implementer:

- **Manual tier override in the REPL.** Planned as its own feature; no command parsing, no per-task tier argument, no config knob for it here — not even a hook "for later".
- **Any content-quality trigger for Escalation.** No `looks_unreliable`, no empty-answer check, no refusal detection. Explicitly rejected in ADR-0001; the sketch in `reference_model_router.py` is reading material and stays unimported.
- Multi-provider support, an LLM-based Classifier, any agent/tool-calling loop, memory, skills, scheduling.

Additionally out of scope for this spec: no price table or per-tier cost estimate (the guardrail checks accumulated spend, not predicted spend); no persistent or cross-session budget (the Call Log is explicitly not the budget window, `docs/CONTEXT.md`); no per-task or per-tier budget (one session-wide ceiling); no budget warning output before the ceiling is hit; no jitter on the backoff; no configurable Attempt count or backoff schedule (module constants, not environment variables); no retry on the `route()` chain as a whole; no downward Escalation; no change to the Classifier's rules; no change to the REPL's success output; no Call Log rotation or analysis command.

## Further Notes

The three slices land in dependency order and share one function: retry introduces the Attempt and the per-Attempt Call Log entry; Escalation consumes retry's "this tier's Attempts are exhausted" signal; the Budget Guardrail gates the transition Escalation performs. Building them in any other order means writing a signal with no producer or a gate with nothing to gate.

`ROUTER_BUDGET_USD` is validated at startup rather than at the moment of the first Escalation on purpose. The whole point of feature 0001's startup validation was that a config mistake should not be discovered after the user has typed a task; a typo'd budget that silently disables the guardrail would be a worse version of the same failure, because nothing visible would go wrong.

The guardrail deliberately has no way to stop the Classifier's own tier. That is what makes it safe to set: the worst case of a too-low ceiling is that escalations stop happening, never that the tool stops answering.

Accumulated cost depends on OpenRouter reporting `cost` on the completion response. Feature 0001 confirmed it is included automatically on non-streaming responses (`docs/specs/0001-model-router.md`, Further Notes) and kept null-safe parsing as the safety net. If cost is absent, the guardrail accumulates nothing and therefore never blocks — the guardrail degrades to "off", which is the correct direction to fail: a missing usage field should not stop the user getting an answer.
