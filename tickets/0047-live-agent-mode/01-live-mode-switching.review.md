# Feature 0047 independent review, correction round 2

```yaml
status: approved
ticket: tickets/0047-live-agent-mode/01-live-mode-switching.md
reviewed_range: deb9abbac7c13a42c651dfc33ee6c718a81338a9..cf6bd9ac41062ce7cd93a2d91e3c70a9c24f479c
review_scope: whole feature folded into its sole fast-path ticket; no spec
supplemental_candidate:
  kind: complete_supplemental_uncommitted_round2
  manifest: /tmp/pa-0047-round2-correction-manifest.json
  manifest_sha256: 17af81cdf268098345c994bf7fc22a8e71c48943afccc6c67f75973d2725e1af
  patch: /tmp/pa-0047-round2-correction.patch
  patch_sha256: 90d451446baf118b445d2b25976ae1aba339e84be1e9f8ae38c4200733dde3c8
  files:
    src/personal_agent/routing/router.py: 51ac4f673d2183a52e7367de2f74d405ba5eae5303bbc96aa2c290e0ded41d47
    src/personal_agent/terminal/input_box.py: 53eb7366a9264fb55d1716f8b03f1cdac14f41b5e6732b727b0c5d3895cf7c5e
    src/personal_agent/tools/registry.py: 02b1f805c4f721462940c7c3d3c2f1e52cda1d845e94d91de57b41453dabac0a
    tests/test_agent_mode.py: 50119e22cb7e7b716ae09d153b0f4818c2a963f90f30eff4081cfdc98cea8758
    tests/test_input_box.py: 15e1d2086b6988e0cbe82ad44660dfd174a2629a68d38201678295dd38694505
  verified_before_and_after: true
  complete_head_to_five_file_diff_matches_patch: true
criteria:
  - criterion: AC1 cycling, prompt/preview/busy feedback, drafts, secret/history isolation
    result: pass
  - criterion: AC2 current mode at every subsequent tool boundary and provider exchange; running operation completes
    result: pass
  - criterion: AC3 explicit pending answer, dangerous exact yes, plan denies approved mutation, question text preserved
    result: pass
  - criterion: AC4 exclusive keyboard consumer, live busy input, ordinary queued input, cancellation and reader cleanup
    result: pass
  - criterion: AC5 deterministic regressions and relevant terminal/router/registry/continuation/audit checks
    result: pass
  - criterion: AC6 concise README/context timing and approval documentation, no new dependency/unnecessary comment
    result: pass
findings: []
checks:
  - Exact immutable range resolves; HEAD equals supplied head. Manifest, patch, all five file hashes and exact head-to-five-file diff verified before source assessment and again after every verification test.
  - Required BRANCH security review completed before Standards and Spec; discovery and independent false-positive filtering performed sequentially without agents or exploit execution.
  - Fresh Gitleaks 8.30.1 scan: 759 artifacts / 6662818 bytes; selected commit message, all 13 modified blobs, exact committed diff/log, base/head snapshots, complete five-file supplement and patch, current references. External useDefault configuration, no repository ignore files, ignore-gitleaks-allow, redact=100, decode depth 5, archive depth 2.
  - Scanner exit 1 solely for six model-ID fixture detections in unchanged base/head context; no skipped/error indicators, binary context or unsupported credential configuration lines. Zero findings in selected changed/supplemental artifacts.
  - Local OPENROUTER_API_KEY and OPENAI_API_KEY values compared in memory as literal/Base64/hex/URL forms; zero matches. Values never printed or persisted.
  - Six scanner matches triaged as three unchanged provider/model literal lines repeated across base/head; literal AST checks and identical blob SHAs recorded in fixture-triage.json.
  - No confirmed credential leaks found in the reviewed changes. No high-confidence HIGH/MEDIUM vulnerabilities found in the reviewed changes.
  - Original direct Router and full interactive REPL F3 reproductions plus recovery/cancellation/bounds companion probes: 6 passed in 7.68s. Plan selected before followup dispatch; actual request offers no write and contains no Build policy.
  - Independent focused agent/routing/detailed-audit/context-recovery/preventive-compression/continuation/context-overflow tests: 424 passed in 21.90s.
  - Independent complete tests/test_input_box.py: 70 passed in 47.41s, including blocked provider/tool switching, cancellation, CPR and temporary reader cleanup.
  - Original F1/F2/typeahead/confirmation/preview/secret probes: all four passed. Queued draft preserved, build approval restored before effects, secret masked and history isolated, question preserved, plan/build/auto cycle correct.
  - Implementer full-suite evidence inspected: /tmp/pa-0047-f3-full-suite-final.log, 2002 passed in 107.22s. Independent focused checks above cover the corrected class; no redundant full-suite rerun.
  - Exact committed and supplemental git diff --check pass; all five supplemental Python files AST-parse; no configured repository typecheck command.
  - Dirty repository status and HEAD preserved; no staging/commit/push or production/test/tracking edits. Raw private scanner artifacts removed by finally; only sanitized review context remains.
residual_risks:
  - Approval applies only to the supplied exact range plus this pinned complete supplement; candidate remains uncommitted by instruction.
  - Full Git history was not scanned; no full-history or remote audit was requested.
  - Native input behavior was verified with prompt_toolkit pipe and VT100/CPR fixtures, not a human terminal session.
```

## Standards

No findings. The implementation reuses the installed terminal facilities and existing shared Router/Tool Registry boundaries. Router and providers remain independent of prompt_toolkit. The temporary input thread stops and joins before later prompts; no persistent reader or dependency is introduced. The shared dispatch correction refreshes prepared input through the existing preparation flow, with one additional recovery-state flag to preserve already committed compression. The provider retry counter advances on completed/failed attempts rather than policy refreshes. No unjustified abstraction or concrete baseline smell requires a change. Existing explanatory shell-cleanup comments were moved, not newly added.

## Spec

No findings. The ticket's six criteria are satisfied by source assessment and independent execution. All three previous blocking findings are corrected:

- F1: ordinary queued draft is collected one key at a time, allowing subsequent eager Shift+Tab controls to run while work remains active. The draft and later ordinary input remain ordered for subsequent prompts.
- F2: the shared apply boundary rechecks current mode. Stale implicit auto approval returns to an explicit confirmation after the busy reader stops; plan denies mutation; network confirmation is restored in build/plan. Existing explicit approval remains required and dangerous commands retain exact-yes handling.
- F3: the provider dispatch guard now runs inside busy startup, before assessment, detailed attempt start and provider call. If mode changed, it refreshes system, tool definitions, prepared input, estimate and assessment without consuming a provider retry. The original actual Router and REPL reproductions pass. Auto/plan regression variants additionally check full prepared request, attempt audit, question text and all retry attempts. Completed recovery compression persists across refresh; refreshed requests must still strictly reduce rejected input and fit the ceiling. Startup cancellation creates no orphan detailed attempt end.

README and docs/CONTEXT.md explain prompt/busy timing, subsequent boundaries, already-running operations, pending explicit approval and plan gating concisely. Bookkeeping files were excluded from application review while retained in credential coverage.

Standards: 0 findings, worst none. Spec: 0 findings, worst none.

## Independent runnable evidence

From the repository root (local path anonymized), with repository writes disabled for Python bytecode and pytest cache:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q -s -p no:cacheprovider /tmp/pa-review-0047-final/test_provider_boundary.py /tmp/pa-0047-f3-recovery-probe.py /tmp/pa-0047-f3-cancel-probe.py /tmp/pa-0047-f3-recovery-bounds-probe.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agent_mode.py tests/test_routing.py tests/test_detailed_audit.py tests/test_context_recovery.py tests/test_preventive_compression.py tests/test_continuation.py tests/test_context_overflow.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_input_box.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/pa-review-0047/probe_typeahead.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/pa-review-0047/probe_build_boundary.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/pa-review-0047/probe_confirmation.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /tmp/pa-review-0047/probe_preview_secret.py
```

All commands exited zero. Runtime checks exercise the actual frozen implementation and isolated temporary fixtures. Security assessment remained separate and read-only; these ordinary correctness checks followed its completion.

Fresh sanitized security and source context: `/tmp/pa-review-0047-round2/evidence.json`, `source-mapping.json`, `fixture-triage.json`, `frozen-verification.json`, `committed.diff`, `committed.log`, `supplement.diff`, `base/`, `head/`, `supplement/`, and `references/`. All later source/diff reads used this sanitized context. Scan runner: `/tmp/pa-review-0047-round2-prepare.py`; raw scanner exports/reports removed after completion.

Context7 resolved `/prompt-toolkit/python-prompt-toolkit` and queried primary eager-key-binding documentation: https://github.com/prompt-toolkit/python-prompt-toolkit/blob/main/docs/pages/advanced_topics/key_bindings.rst . It confirms eager matching behavior; lifecycle and policy conclusions above are established by the actual implementation and executed checks.
