# 04: Recorded task routes and cache-aware accounting

**What to build:** `/report` shows a bounded chronological task/model/cache sequence from recorded evidence, and direct-provider cache counters/cost estimates correctly account for known reads and writes.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0053-stable-sessions-and-recovery.md` — Recorded task/model/cache evidence R15–R20, Delivery R32, Local report correlation and accounting, Testing Decisions.

- [x] Retain existing Session/purpose aggregates and coverage first; add chronological detail for latest 20 explicit opened executions with Run/opening identity, ordinal, submitted versus Retry, recorded outcome/unresolved, actual tier/Provider/model routes and at most 16 route groups per execution. Bound state and omission notices.
- [x] Attribute physical Attempts by explicit opening/Turn End/next opening/Run boundary, never task-text matching. Repeated same text, original ordinal reused by Retry, partial process death, maintenance inside/outside task and legacy unattributed entries remain truthful.
- [x] Show ordinary route Attempt/retry counts, Provider duration, first-text known coverage, prompt/output/cache-read/cache-write totals and cost provenance; keep evaluator/Compression separate. Mark observed route changes and adjacent recorded cache evidence without claims of causality/savings/cache erasure.
- [x] Compute cache-read fraction only across compatible same samples with known positive prompt denominator and nonnegative consistent cache counters, displaying sample coverage. Missing/partial/invalid fields stay separate from zero; invalid subset does not erase other valid metrics.
- [x] Bound rendering to 16 KiB with aggregates/coverage retained before optional details; retain bounded scanner behavior, partial/truncation diagnostics, known-key redaction and control-character sanitization. Optional upstream evidence is used only if already recorded and safely correlated; no lookup.
- [x] Normalize supplied cache counters equivalently for streaming/nonstreaming/failure usage in all four Providers. Anthropic total includes noncache+read+write; OpenAI/OpenRouter/Gemini reads are subsets of total. Preserve applicable write fields/TTL breakdown; do not double-add or coerce invalid/missing to zero.
- [x] Cache-aware direct-provider estimates use locked local LiteLLM semantics verified for each Provider, including write TTL where reported; no fixed price multiplier. OpenRouter reported cost is preserved exactly. Unsupported/invalid/incomplete pricing evidence yields unavailable estimate, never zero; omitted-zero assumptions for calculation require Provider contract evidence while report coverage stays unknown.
- [x] Verify against fake fixed pricing/usage cases that cache reads/writes bill exactly once and normalized prompt totals are correct; include all-uncached, known-zero, missing, malformed, streamed-partial and failed Attempt samples. Direct costs remain `cost_estimated: true`, available spend is charged once, and legacy log costs are not rewritten.
- [x] `/report` remains no-argument/local-only across Runs, adding no Attempt or remote/metadata/tokenizer/configuration call. Assert unchanged routing/input/Conversation/pending work/latest `/usage`/spend and existing Audit Event only.
- [x] Update shared HTTP/stream normalization and estimator callers plus tests, concise README reporting/cost explanation and dated research status; propose exact Estimated Cost/Session Report glossary edits to orchestrator. No dependency/configuration changes.
- [x] Run focused session-report, Provider, native/shared streaming, routing/Call Log, audit and cost contract checks, then full `uv run --offline pytest -q` using escalation for existing socket/MCP tests. Handoff includes synthetic rendered route-change report, cost input/output evidence and partial-coverage case.

**Implementation reach:** Existing Session Report, Call Log boundary scanner and recorded fields, Provider HTTP/chat-completions/native stream normalization and local cost estimator. No new report framework, database or model lookup path.

**Standalone value:** Recorded observations become inspectable and estimates include cache work irrespective of whether other 0053 priorities landed.
