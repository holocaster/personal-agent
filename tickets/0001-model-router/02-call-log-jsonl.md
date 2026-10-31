# 02: Every call appends a JSON line to the Call Log

**What to build:** the deliverable the feature exists for. After the user has typed a few tasks, a log file holds one JSON object per line — what was asked, which Complexity Tier it got, which model ran it, how long it took, and what it cost — so routing can later be judged from data instead of memory. The user can point the log anywhere with an environment variable and read it back with ordinary line-oriented shell tools.

**Blocked by:** 01 (the Router must already classify, route and call before there is anything to log).

**Spec:** `docs/specs/0001-model-router.md` — Implementation Decisions (Call Log line, Provider call contract); Testing Decisions (Coverage for Call Log); Further Notes (defensive cost reading). **ADRs:** none.

- [x] A Call Log module appends one JSON object per line to a log file, opening in append mode and creating the file when it does not exist, so history accumulates across sessions.
- [x] Each line carries: `timestamp` (ISO 8601, UTC, `Z`-suffixed), `task`, `tier`, `model`, `latency_ms`, `cost`, `prompt_tokens`, `completion_tokens`, `ok`, `error`. On a successful call `ok` is true and `error` is null.
- [x] `latency_ms` is an integer measured client-side with a monotonic clock around the Provider call only.
- [x] `cost`, `prompt_tokens` and `completion_tokens` come from whatever usage the Provider reported; any field the response does not carry is written as `null` and never raises. The implementer confirms the real shape of OpenRouter's usage/cost reporting against a live response, and the code stays tolerant of its absence either way.
- [x] The log path comes from `ROUTER_LOG_PATH`, defaulting to `./router_log.jsonl`; the default path is gitignored and the variable is documented in the README alongside the other environment variables (marked optional).
- [x] The Router writes the log entry for every call it makes; the REPL's printed output is unchanged by this ticket.
- [x] Tests assert the log as a file artifact, not through internals: after a routed call the last line of the file parses as JSON and carries every expected key with the expected `task`, `tier` and `model` and a numeric `latency_ms`; a response missing cost/usage yields nulls in those fields with the call still succeeding; two calls append two lines rather than truncating.
- [x] Tests point `ROUTER_LOG_PATH` at a temporary directory and continue to use the single `urlopen` fake from ticket 01 as the only seam.
