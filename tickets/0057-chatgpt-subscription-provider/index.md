# Tickets: 0057-chatgpt-subscription-provider

[Spec](../../docs/specs/0057-chatgpt-subscription-provider.md) · [Brief](../../docs/briefs/0057-chatgpt-subscription-provider.md) · [ADR-0015](../../docs/adrs/0015-chatgpt-subscription-provider.md)

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| [01](01-connect-and-select-account-model.md) | Connect ChatGPT and explicitly select an account model | none | done |
| [02](02-stream-responses-and-tools.md) | Run streamed ChatGPT tasks and local Tools | 01 | done |
| [03](03-preserve-account-bound-session-continuity.md) | Preserve ChatGPT continuity through Retry, Resume, Fork and Compression | 02 | done |
| [04](04-inherit-account-in-subagents.md) | Keep Subagents on the parent's ChatGPT account | 03 | done |
| [05](05-show-context-and-separate-plan-usage.md) | Show current context and separate plan usage from API spend | 03 | done |

Only 01 is initially unblocked. After 03, 04 and 05 are independent frontiers; both must complete before feature verification. Each ticket owns its focused tests and full-suite regression check; there is no implementation authorization in this planning commit. Source files listed in tickets are implementation areas, not permission to discard concurrent work.

## Requirement coverage

| Spec requirement | Primary ticket(s) | Observable proof |
|---|---|---|
| D1 existing seams/dependency strategy | 01, 02 | Declared JWT dependency, existing InputBox/Provider/transport reuse, API regressions |
| D2 unconfigured entry/admission/atomic activation | 01, 02 | REPL/CLI and settings tests; no invalid dispatch or implicit switch |
| D3 secure OAuth/registration/permission | 01 | Synthetic callback/JWKS/identity/scope/cancel/reauthorization cases |
| D4 private storage/rotation/revocation/redaction | 01, 02, 04 | Private-file failure cases, real process races, secret echo tests |
| D5 account models/capacity/output estimate | 01, 02, 05 | Account-bound listing, provenance/formula, request omission and occupancy |
| D6 Responses/SSE/Tools | 02 | Request and adversarial SSE/Tool contract fixtures |
| D7 classified failure/explicit Retry/usage | 02, 03, 04, 05 | Exhaustion/overflow/temporary failures, durable pending work and honest accounting |
| D8 durable replay/Resume/Fork/Compression/account changes | 03 | Call Log round trips and binding/normalized-text notice tests |
| D9 child inheritance/accounting | 04, 05 | Real child identity/refresh/cancel and receipt reconciliation/report tests |
| D10 footer/context/usage/report/first-use UI | 01, 05 | First-use/status and mixed-route rendered UI/report assertions |

| User stories | Tickets |
|---|---|
| 1–10 | 01 |
| 11 | 02 |
| 12 | 02, 03 |
| 13 | 02, 03, 05 |
| 14–16 | 03 |
| 17 | 04 |
| 18 | 01 |
| 19 | 01, 02, 03, 04 |
| 20–22 | 05 |

## Planning validation

Dependency graph: `01 → 02 → 03 → {04, 05}`. All blockers exist, are earlier numbered and form an acyclic graph. D1–D10 and user stories 1–22 are mapped above. The five checkpoints isolate substantial authorization, wire protocol, persistence, process and presentation risks; none is a standalone technical-layer-only refactor. No fast-path ticket exists to supersede.

Implementation and final feature review should recheck the linked official SIWC sources if their contract has changed. Offline deterministic acceptance requires no user credentials, browser login or paid requests. A later authorized real-account smoke run is optional evidence with account-specific eligibility, not a substitute for these checks.
