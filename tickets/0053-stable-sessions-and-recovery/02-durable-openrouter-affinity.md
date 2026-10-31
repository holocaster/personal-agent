# 02: Durable OpenRouter affinity

**What to build:** OpenRouter can associate ordinary requests across a Session's turns, Tool follow-ups, retries and Resume using its durable Session Id; auxiliary evaluator/Compression exchanges have separate stable identities.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0053-stable-sessions-and-recovery.md` — Session cache affinity R8–R10, Delivery R32, Existing ownership and seams, Testing Decisions. **ADRs:** 0009 and existing 0002 Provider contract.

- [x] OpenRouter streaming and nonstreaming payloads carry top-level `session_id` equal to current durable Session Id for every ordinary request, including Tool follow-ups, technical retries, overflow recovery, explicit Retry, new turn and Resume. Two Sessions differ.
- [x] Evaluator uses `<Session Id>:tier_selection`; all manual/preventive/overflow Compression blocks/combinations use `<Session Id>:compression`, including retries and Resume. Auxiliary calls never borrow ordinary affinity.
- [x] Thread one optional identity keyword through existing exchange/Provider seam and callers. All four Providers and fake Providers remain callable; direct standalone calls without identity omit OpenRouter metadata. Other Providers never send OpenRouter's session_id field.
- [x] Preserve prepared prompt/token budget/replay input and existing provider preferences (`sort: price`, throughput 85, require_parameters), headers, streaming behavior and opt-in diagnostics. Identity must contain no credential/path/task data and satisfy OpenRouter's 256-character bound.
- [x] Tests capture actual fake HTTP request payloads across required ordinary/maintenance paths and Resume; shared fake transport detects any unexpected lookup/network request. Assert exact ordinary/purpose keys rather than only their presence.
- [x] Document best-effort per-model affinity without guaranteed cache hit, idle survival or cross-model reuse; retain explicit configuration/selection ability to change model. Update concise README and dated research status; propose exact CONTEXT contract changes to orchestrator.
- [x] Run focused Provider, routing, session-tier, REPL, Compression/preventive/overflow and streaming suites, then full `uv run --offline pytest -q` using escalation for existing socket/MCP tests. No paid calls, new cache-control behavior, metadata polls, dependencies or config options.

**Implementation reach:** Router exchange and all summary/evaluator callers, OpenRouter payload, other Provider optional signatures and test fakes. Current Session identity already exists; do not invent a parallel Session/request identity framework.

**Standalone value:** Actual OpenRouter requests gain consistent affinity without depending on new selection policy or reports.
