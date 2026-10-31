# Tickets: 0024-runtime-config

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Edit tier routing configuration in the interactive REPL | none | done |
| 02 | Set Provider API keys and complete missing-key Provider changes | 01 | done |

02 depended on 01 because it extended the `/config` menu, home `.env`
persistence, and active Runtime Configuration established there. Ticket 01
provided model changes and Provider changes where a key was already available;
ticket 02 added the missing-key entry flow.

Requirement coverage: R1, R2, R5 (tier values), R6, R7 (tier values), R8 -> 01;
R3, R4, R5 (API keys), R6 (key updates), R7 (Provider-key values), R8 -> 02.
