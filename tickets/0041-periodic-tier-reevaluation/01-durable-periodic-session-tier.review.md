# Review: 0041/01 — Durable periodic Session-tier selection

## Verdict

```yaml
status: approved
ticket: "0041/01"
reviewed_range: "6ab4fd0a0f3d6144700887981efb258201bac0f9..908acbfceee5e94918b64cca3e6392ad38af8fe1"
findings: []
user_scope_decision_needed: false
```

Independent `sdd-reviewer` completed BRANCH security, Standards, Spec and whole-feature verification using the user-authorized current model. All R1–R16 passed; no scope creep or missing criterion was found.

## Acceptance coverage

| Requirement | Result |
|---|---|
| R1 — Scheduled evaluations before 1/5/15, including already-complex Sessions | pass |
| R2 — Exact cumulative user texts; generated/workspace context excluded | pass |
| R3 — Durable submission identity; Retry/follow-ups do not duplicate progress | pass |
| R4 — Initial selection and monotonic later automatic selection | pass |
| R5 — Manual selection suspends evaluation and preserves tracking | pass |
| R6 — Auto retains tier/progress and coalesces evaluation requests | pass |
| R7 — Undo/Compression preserve input; Clear discards it without resetting progress | pass |
| R8 — Resume restores routing independently of Conversation without startup evaluation | pass |
| R9 — Policy-less v2 compatibility and explicit schedule opt-in | pass |
| R10 — Completed failure visibly selects initial medium or preserves the current tier | pass |
| R11 — Cancellation prevents ordinary dispatch and preserves due evaluation | pass |
| R12 — Full request measured; overflow causes no evaluator dispatch or truncation | pass |
| R13 — Durable ordering, replay validation, partial restoration and fatal persistence errors | pass |
| R14 — Attribution, accounting, redaction and ordinary-usage separation | pass |
| R15 — Shared configuration snapshot and retained routing/Provider/Tool guarantees | pass |
| R16 — Notices, model status, pending footer, help and implemented-behavior docs | pass |

## Security and source review evidence

- Both supplied SHAs resolved; sanitized diff/log used the exact range. Checkout HEAD was `091079662912630844c4986fa55550dbda34e5cf`; only `.ai/PROJECT_STATE.md` differed from the reviewed head, and that bookkeeping commit was excluded.
- BRANCH credential review completed via `python3 /tmp/opencode/review0041_setup.py` with Gitleaks 8.30.1. The archive checksum matched the official release checksum and the executable matched that archive.
- Scanned 725 artifacts totaling 6,513,480 bytes: selected-commit changed blobs and message, exact diff/log, and base/head source context, including tests and docs. Used external default rules, no repository-controlled ignores, `ignore-gitleaks-allow`, decode depth 3, archive depth 2 and full redaction. Full history was not scanned.
- Scanner exit 1 represented six matches, with no warnings, errors or skips. All matches were in unchanged base/head test blobs at three locations, not introduced artifacts. Relevant local credential comparison across literal/Base64/hex/URL encodings found no matches. No confirmed credential leaks were found in the reviewed changes.
- Sequential source-only vulnerability discovery and false-positive filtering reviewed changed production paths and unchanged exchange, persistence, redaction and command guards using sanitized snapshots. No high-confidence HIGH/MEDIUM vulnerability findings.
- Standards review found no convention or smell-baseline issue with concrete impact. The implementation uses a small routing state value, shared Provider exchange and existing Call Log; no new dependency, Provider, policy framework or durable file.
- Spec review covered the ticket, R1–R16, implementation/testing decisions, ADR-0007 and retained ADR-0006/0005/0002 guarantees. Acceptance tests use the real Evaluator with fake HTTP and real temporary Call Logs.
- Sanitized security evidence: `/tmp/opencode/review0041/security-evidence.json`. Pinned source snapshots at `/tmp/opencode/review0041/base/<path>` and `head/<path>` preserve original line numbers. Private raw scan exports, reports and diagnostics were removed.

## Independent checks

| Command | Result and evidence |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 uv run --offline pytest -q -p no:cacheprovider tests/test_session_tier.py` | 193 passed in 11.90s |
| `PYTHONDONTWRITEBYTECODE=1 uv run --offline pytest -q -p no:cacheprovider tests/test_session_tier.py tests/test_repl.py tests/test_main.py tests/test_call_log.py tests/test_detailed_audit.py tests/test_audit_local.py tests/test_runtime_config.py tests/test_question_tool.py tests/test_preventive_compression.py tests/test_context_recovery.py` | 769 passed in 34.25s |
| `PYTHONDONTWRITEBYTECODE=1 uv run --offline pytest -q -p no:cacheprovider` | 1801 passed in 96.60s |
| `PYTHONPYCACHEPREFIX=/tmp/opencode/review0041/pycache uv run --offline python -m compileall -q src tests` | Exit 0; bytecode stayed outside the repository |
| `uv build --offline --out-dir /tmp/opencode/review0041/build` | Source distribution and wheel built successfully |
| `git status --porcelain=v1 && git diff --quiet && git diff --cached --quiet && git rev-parse HEAD && test ! -e /tmp/opencode/review0041/private` | Empty status/diffs; HEAD unchanged; private scan artifacts removed |

No dirty-tree artifacts required restoration. The reviewer made no code edits, commits, pushes, merges or PRs.

## Verification boundaries

- Deterministic HTTP fakes were used; no live Provider calls or evaluator judgment-quality benchmark.
- Credential coverage is the selected branch artifacts and base/head context at the stated decoding/archive depths, not a full-history audit.
- Concurrent Runs and crash-proof storage remain outside feature scope.
