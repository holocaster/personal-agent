# Review: 0054 ticket 02

status: approved
ticket: 02-direct-route-cutover
reviewed_range: 5fca40bf6a392cebfcf149725e9b33b14389a70f..dc0a077ab8332c7c19b544717245a8ff895b2840

All eleven acceptance criteria pass. BRANCH security review: no confirmed credential leaks (gitleaks git + dir scans; generic-api-key hits triaged as env-var names/model IDs already in base), no HIGH/MEDIUM vulnerabilities. Full suite 2591 passed. Test-deletion audit: 141 test names removed, 62 added; removed tests are tier/evaluator-only, non-tier coverage was renamed/adapted (retry, call log, config store, submission identity, fatal writes, recovery, compression, affinity, report). Production prompt fixtures unchanged. Implementer deviations accepted against R12/R19 (any-version header for discovery/`last` recency while Resume requires v3; piped Provider/model line; tier-only tests removed; stray old record types ignored).

## Optional suggestion (not required)

1. `src/personal_agent/call_log.py` `_read_entries`: a v3 log containing obsolete v2 record types (e.g. `session_tier_changed`) is ignored rather than refused. Nothing is derived from them; refuse them only if stricter tamper detection is wanted.

## Residual risks

BRANCH scope only. The user's local `.env` has only TIER_* routing settings; startup now stops with new-setting guidance until PA_PROVIDER/PA_MODEL are added. docs/CONTEXT.md still describes tiers (Main-owned).
