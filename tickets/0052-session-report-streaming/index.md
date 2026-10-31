# Tickets: 0052-session-report-streaming

| # | Title | Blocked by | Status |
|---|-------|-----------|--------|
| 01 | Report recorded activity across the current Session's Runs | none | done |
| 02 | Stream OpenRouter and OpenAI text safely through the terminal | 01 | done |
| 03 | Stream Anthropic and Gemini while preserving native completion and replay | 02 | done |

Spec: `docs/specs/0052-session-report-streaming.md`.

Coverage: 01 → R01–R05 and report parts of R16–R17; 02 → R06–R13/R16–R17 for Chat Completions; 03 → R14–R15 plus all-Provider integration of R06–R08/R10–R13/R16–R17. Blocking edges exist and form the acyclic chain 01 → 02 → 03.

Ticket 01 delivers a useful local report before streaming. Ticket 02 delivers a complete streaming path with independent review of output safety, accounting and keyboard ownership. Ticket 03 adds the remaining native APIs and their signature/replay risks after that common path is proven. Review each streaming slice independently; do not split transport, Providers and terminal into non-demoable layer tickets.
