# 01: Browse and refresh the local Models.dev catalog

**What to build:** Browse/search eligible models and refresh their local catalog without Provider keys, inference, Session creation or changing the current route. This is independently useful setup behavior before ticket 02's cutover.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0054-direct-provider-model-selection.md`, R1–R4 and Implementation Decisions (catalog/cache and CLI contract); supports R6–R7/R13/R19. **ADRs:** ADR-0012; preserve ADR-0002 dispatch boundaries.

- [x] Add the small catalog interface and credential-free `--models <provider> [--search <text>]` / `--refresh-models` early-exit CLI paths before Session/Tool/key initialization. Combined flags refresh then list; errors remain visible/nonzero with no Session effects.
- [x] Use the fixed public endpoint, exact four-Provider/Google mapping and exact offering IDs. Implement spec eligibility/reasons for text/Tools, limits/status, specialized type, model overrides and unsupported interleaved replay; unknown capability evidence is unsupported, absent pricing is allowed, alpha/beta is visible. Never adopt remote auth/SDK/endpoint/body/header instructions or promise account/System/Streaming compatibility.
- [x] Enforce spec bounded reads/time/schema/identity/count/string limits and duplicate-key refusal. Validate the complete four-Provider map; ignore unknown optional fields, retain well-formed ineligible offerings/reasons and distinguish malformed responses.
- [x] Implement any-age cache-first loading, one fetch if unusable, explicit refresh, timestamps/offline/retry guidance and no fallback catalog/polling. Publish only after private temp write/flush/fsync/atomic replacement; refuse linked/nonregular targets and preserve prior bytes/in-memory catalog on failure.
- [x] Implement literal case-insensitive ID/name search with exact case-sensitive lookup, deterministic ordering, terminal sanitization, bounded rows/output and omission guidance. Expose useful missing/incomplete/incompatible/unavailable reasons for ticket 02.
- [x] Verify via CLI/catalog seams with temporary home/small representative JSON/fake HTTP: all mappings, cache hit zero requests, metadata/filter matrix, unknown optional fields, missing/corrupt/oversize cache, failed refresh, timeout/HTTP/media type/redirect/size/truncation, duplicate/mismatched IDs and write/replace faults preserving bytes. No real credentials/network/live catalog dependency.
- [x] Document working CLI/cache behavior concisely in README/ENV_VARS as applicable, retaining current routing descriptions until ticket 02. Run focused catalog/CLI tests plus relevant existing startup checks; no dependency installs/model calls.

**Boundary:** Own catalog/CLI/tests and matching docs only. Existing routing stays testable; do not add direct-route/tier compatibility adapters or a generic framework. Ticket 02 reuses this exact catalog interface.
