# 01: Use local MCP Resources during routed tasks

**What to build:** A user can configure one local stdio server and the model can discover and read its text Resources through the normal Tool loop, with mode-specific approval before launch, bounded results, visible failures and reliable cleanup.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0034-mcp-resources.md`, Requirements R1–R9, Implementation Decisions and Testing Decisions. **ADRs:** ADR-0002 (Provider boundary) and ADR-0005 (Call Log replay).

- [x] R1: Parse and validate `PA_MCP_SERVER` at startup, snapshot the single server configuration, use executable plus arguments without shell parsing, and keep disabled startup process-free. Use the R1 minimal SDK environment allowlist, never the full parent environment; verify a parent sentinel secret is absent. Report invalid configuration without exposing its raw values.
- [x] R2: Advertise and execute exactly the three named MCP resource Tools in plan/build/auto when configured; reject invalid/extra arguments and unavailable calls before launch. Keep command, server, environment and cwd outside model schemas; support direct and template-derived read URIs.
- [x] R3: Reuse the Tool Registry's prepare/confirm/apply path. Every plan/build call identifies server/operation/read URI and requires approval before process creation; rejection, EOF and missing callback cause no launch or request. Auto still validates but does not ask.
- [x] R4: Add the official current stable v2 MCP SDK dependency (`mcp>=2,<3`) and lock update, encapsulate one connection per approved operation, negotiate with default SDK protocol `auto` (2026-07-28 discovery with legacy fallback) and capability-check, enforce the 30-second deadline and bounded cleanup, and prove child exit on success/error/timeout/Ctrl-C. Support no server-driven host actions or application retries; modern input-required results return an unsupported-interaction Tool error. Verify modern negotiation and legacy fallback offline.
- [x] R5: Both list Tools follow cursors in the same connection within 100 entries, 10 pages and output/deadline limits; repeated cursors terminate. Return the specified metadata/provenance and truthful truncation, including empty catalogs.
- [x] R6–R7: Read ordered text contents, reject blobs including mixed responses, preserve URIs, and enforce the exact 32 KiB serialized-content cap on results/errors with UTF-8-safe text truncation. Normalize documented failures into Tool errors and keep raw stderr/error payloads out of model and terminal output.
- [x] R8: Reuse normal Tool display, Conversation and Call Log/Resume behavior; show server identity and read URI, provide truthful model guidance, and keep server content as untrusted data. Existing built-in Tool gates and Provider contracts pass regression checks.
- [x] R9: Add the concise README configuration example and boundaries, including per-call lifetime, supported content, defaults and host access outside Workspace Root confinement.
- [x] Testing Decisions: An offline stdio fixture plus scripted fake-Provider REPL tests demonstrate discovery → template URI → read, all mode/denial paths, failure/cleanup cases and output bounds. Run the full offline suite; record commands and results for independent review. No live server, credentials or network needed in tests.
