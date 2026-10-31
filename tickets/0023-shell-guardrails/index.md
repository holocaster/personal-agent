# Tickets: 0023-shell-guardrails

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Dangerous Command with Strong Confirmation and logged rules | none | done |
| 02 | Fetched-Content Warning for the rest of a turn after webfetch | 01 | done |
| 03 | webfetch drops hidden HTML elements | none | done |

02 depended on 01 because both extended the same `confirm` contract
(spec R3: 01 adds `dangerous_rules`, 02 appends `fetched_urls`) and the same
REPL confirm callback. 03 was independent but touched `README.md`; all three
were implemented and reviewed as one batch in order 01, 02, 03.

Requirement coverage: R1-R6 -> 01; R7-R8 -> 02; R9 -> 03; R10 split by topic
across 01 (Dangerous Command rules, Strong Confirmation, known limits, `shell`
section sentence), 02 (Fetched-Content Warning) and 03 (hidden-element
dropping).
