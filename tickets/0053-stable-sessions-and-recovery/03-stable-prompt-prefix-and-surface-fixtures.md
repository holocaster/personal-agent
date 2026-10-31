# 03: Stable prompt prefix and reviewed surface fixtures

**What to build:** Stable application/project instructions precede changing context while all commands and live gates keep working. Review complete production prompt/Tool surface fixtures for plan, build and auto offline.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0053-stable-sessions-and-recovery.md` — Prompt surface and fixtures R11–R14/R29–R31, Delivery R32, Existing ownership and seams, Testing Decisions.

- [x] Order ordinary prompt content as fixed application/Tool/trust/mode/language rules, task Project Instructions, Memory, active Skills, Summary and Todo. Preserve all content, priorities and gates; do not freeze changing context.
- [x] A Todo, Memory, Skill or Summary-only change preserves preceding stable bytes for production prepared input in OpenRouter, Anthropic, OpenAI and Gemini. Document/test the common prefix; do not claim cache hits, savings or unchanged full-history input.
- [x] `/remember`/`/forget` next-request effects, Skill activation/order/precedence, unfinished/finished Todo follow-ups and manual/preventive Compression remain effective. Reload Project Instructions per task/Retry and retain snapshot within task.
- [x] Mode changes remain effective at subsequent Provider/Tool boundaries, including pending confirmation and busy work; project/mode/catalog changes may legitimately alter the prefix. Keep current_time outside system text. Preserve Provider replay/signatures and complete-input budget accounting.
- [x] Make identical effective Tool catalogues/Skill descriptions deterministically ordered without changing availability, schemas or meaningful argument-array ordering. Provider translations retain advertised order; effective plan catalogue excludes mutating Tools.
- [x] Commit exactly three readable fixtures under tests for plan/build/auto. Render full system text and ordered canonical Tool schemas from production request paths captured by fake Provider/HTTP, including synthetic project, Memory, Skill, Summary and Todo content. Do not copy the builder into fixture generation.
- [x] Isolate temporary home/workspace, fake model configuration/credentials and optional Tool gates/catalogue. Forbid network, real config/credentials/user context and machine-specific paths. Re-render under changed clock/root/home/environment credential/hash seed with byte-identical output.
- [x] A deliberate real prompt-text/schema edit fails fixture comparison until explicit regeneration. Document one small developer offline regeneration command under tests; outputs are reviewable diffs, with no REPL command or model-family variants.
- [x] Preserve behavioral Agent Mode/Tool confirmation, Project Instructions, Memory, Skills, Todo, replay, budgets and Compression tests in addition to fixtures. Update affected existing prompt expectation tests without replacing behavioral checks with snapshots.
- [x] Update concise developer README/testing guidance and dated reference/routing-research status; propose exact System Prompt glossary changes to orchestrator. No runtime config/dependency change.
- [x] Run focused routing, Tools/agent-mode, project-instruction integration, Memory/Skill/Todo, compression/context and Provider tests plus fixture isolation tests; then full `uv run --offline pytest -q` using escalation for existing socket/MCP tests. Include fixture diffs and prepared-prefix evidence in handoff.

**Implementation reach:** Production Router prompt builder, effective Tool Registry/Skill catalogue ordering, existing Provider input preparation, tests/fixtures and a small regeneration helper under tests. Combine ordering and fixtures in one ticket so the final intended surface is reviewed once.

**Standalone value:** Stable reusable instructions and visible model-facing regressions, with the existing user commands and gates still honored.
