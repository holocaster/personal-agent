# 03: Fail fast on missing config, survive a failed call

**What to build:** the tool stops punishing the user for setup mistakes and transient Provider failures. Starting it with an environment variable unset produces one clear message naming every missing variable and a non-zero exit, before any prompt appears — so the user never types a task only to lose it to an auth error. Once running, a failed or interrupted Provider call prints a readable error, is recorded in the Call Log like any other call, and drops the user back at the prompt instead of ending the session.

**Blocked by:** 01 (startup and REPL loop must exist), 02 (a failed call has to be recorded in the Call Log).

**Spec:** `docs/specs/0001-model-router.md` — Implementation Decisions (Tier Config contract, REPL behaviour, Error handling); Testing Decisions (Coverage for Tier Config and REPL). **ADRs:** none.

- [x] Tier Config validates `OPENROUTER_API_KEY`, `TIER_EASY_MODEL`, `TIER_MEDIUM_MODEL` and `TIER_COMPLEX_MODEL` once at startup, before the first prompt is shown. An unset or empty value counts as missing.
- [x] When anything is missing, the tool prints a single message naming every missing variable at once (not the first one it hits) and exits non-zero without entering the REPL.
- [x] Any exception raised by the Provider call — HTTP error, timeout, malformed response — is caught by the Router, surfaced by the REPL as one readable error line, and the loop continues to the next task.
- [x] A failed call still appends a Call Log line, with `ok: false`, the error text in `error`, the tier and model that were attempted, and the measured `latency_ms` up to the failure.
- [x] `KeyboardInterrupt` during a call aborts that call, prints a notice, and returns to the prompt; `KeyboardInterrupt` at an idle prompt ends the loop cleanly.
- [x] Tests assert the startup message names every missing variable when several are unset, and that startup succeeds when all four are present.
- [x] Tests make the `urlopen` fake raise, then assert the REPL printed an error line, continued to process the next scripted task normally, and that the Call Log holds a line with `ok: false` and a non-null `error` followed by a successful line.
- [x] README's setup section reflects the fail-fast behaviour, so a user who sees the message knows exactly what to set.
