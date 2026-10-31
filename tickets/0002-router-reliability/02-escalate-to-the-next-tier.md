# 02: An exhausted tier escalates to the next one up

**What to build:** a task whose Complexity Tier cannot answer it — every Attempt there failed technically — is retried at the next tier up instead of failing, walking easy → medium → complex until one answers or the ladder runs out. The user sees a normal answer with the routing line naming the tier that actually produced it, so a recovered task is indistinguishable from one that worked first time, except that the Call Log shows the chain. When even `complex` is exhausted, the user gets exactly today's single `Error:` line.

**Blocked by:** 01 (Escalation consumes retry's "this tier's Attempts are exhausted" signal and the per-Attempt Call Log entry; there is nothing to escalate from until Attempts exist).

**Spec:** `docs/specs/0002-router-reliability.md` — Solution (Escalation); Implementation Decisions (Escalation; Call Log schema); Testing Decisions (Coverage for Escalation, Call Log, REPL). **ADRs:** `docs/adrs/0001-escalate-on-technical-failure-only.md`.

- [x] Complexity Tier order (easy → medium → complex) is an explicit ordered sequence in the Tier module — not the enum's declaration order used implicitly, and not a `next_tier` field on each member.
- [x] `route()` walks the ladder from the Classifier's tier upward, running a full set of Attempts at each tier and returning immediately on the first success.
- [x] Escalation is triggered only by technical failure — every Attempt at the tier exhausted, `error is not None`. There is no content-quality, empty-answer or refusal check anywhere in the path (ADR-0001), and `reference_model_router.py` stays unimported.
- [x] Each escalated tier gets its own full Attempt budget with the same retry and backoff rules as the initial tier.
- [x] A task the Classifier sent straight to `complex` has no Escalation path: its Attempts are exhausted and it fails, with no attempt to invent a tier beyond the top.
- [x] When the top tier's Attempts are exhausted, `route()` returns a `RouteResult` carrying that tier's tier/model and the last Attempt's error text — the same shape the REPL already prints as one `Error:` line.
- [x] On success at an escalated tier, the returned result names the tier that answered, so the REPL's existing routing line shows the escalated tier and model with no REPL change.
- [x] The Call Log's `attempt` counter restarts at 1 on each Escalation, so a chain reads as 1,2,3 at `easy` then 1 at `medium`; `tier` and `model` identify which rung each entry belongs to.
- [x] Tests through the existing `urlopen` fake assert the *sequence* of model IDs that reached the wire: exhausting `easy` sends the next requests to the medium model and then the complex model, in that order.
- [x] Tests cover: success at `medium` after `easy` is exhausted (answer returned, routing line names `medium`); a task classified to `complex` exhausting its Attempts (exactly three requests, no Escalation); all tiers exhausted (error result carrying the last Attempt's error, one `Error:` line printed); and a REPL session through `StringIO` where the first task escalates and succeeds and a later task fails entirely, with the loop continuing either way.
- [x] A Call Log test reads the written file for a chain that retried then escalated and succeeded, asserting one line per Attempt in order with the expected `tier`, `attempt`, `ok` and error values and the same `task` on every line.
- [x] The README describes Escalation — the ladder, that the trigger is technical failure only, and that nothing follows `complex`.
