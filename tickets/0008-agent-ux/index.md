# Tickets: 0008-agent-ux

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | System Prompt with the current date, time and Tool rules | none | done |
| 02 | Tool Registry with jsonschema validation | none | done |
| 03 | Live Tool display | none | done |
| 04 | Input Box | none | done |
| 05 | Status Footer | 04 | done |
| 06 | Sanitize model- and Provider-controlled terminal output | none | done |

Spec: `docs/specs/0008-agent-ux.md`
Brief: `docs/briefs/0008-agent-ux.md`
ADRs: `docs/adrs/0004-prompt-toolkit-input-box.md` (this feature), `docs/adrs/0002-hand-rolled-provider-contract.md`, `docs/adrs/0003-call-log-per-session.md`.

## Coverage

| Spec requirement | Tickets |
|---|---|
| R01 | 01 |
| R02 | 01 |
| R03 | 02 |
| R04 | 02 |
| R05 | 03 |
| R06 | 03 |
| R07 | 03 |
| R08 | 04 |
| R09 | 04 |
| R10 | 04 |
| R11 | 04 |
| R12 | 05 |
| R13 | 01, 02, 03, 04, 05 |
| R14 | 01, 02, 03, 04, 05, 06 |
| R15 | 06 |

R13 (dependencies, README) is split: each ticket declares the dependency and documents the behavior it adds. R14 (unchanged behavior) is a standing constraint every ticket re-proves with the full suite.

## Shape

The brief asks for independent tickets for its four items, and the code supports it: 01 touches only the Router's System Prompt, 02 only the Tool module's declarations and validation, 03 adds an optional callback to `route` plus REPL/spinner output, 04 adds a new input module and an optional `run_repl` parameter. None gates another, so 01-04 are all on the frontier. 02 and 03 both touch the Tool loop area but not the same contract (03 consumes Tool results, whose shape 02 keeps), so ordering is a merge concern, not a blocking edge; running them in number order is fine.

The Input Box is split into 04 and 05 because 04 carries the risk (new dependency, key bindings, TTY activation, `run_repl` input path) and is a natural checkpoint, while 05 is a separately verifiable piece (footer format and the single spend source). 05 is blocked by 04 because the footer lives in the Input Box's bottom toolbar.

06 was added after ticket 03's review found model-controlled text reaching the terminal unescaped (brief, "Added after review"). It is one ticket because the sanitizer and its call sites share one root cause and fit one context window. It has no blocking edge: 01-05 are done, and it only amends their display paths.

No pre-existing fast-path ticket exists for this feature. Status lives only in this index.
