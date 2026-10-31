# Tickets 04 + 05 review (Batch)

```yaml
status: approved
ticket: ["0057/04", "0057/05"]
reviewed_range: dd628b1db2238c264d837c7435e57c913f2baa7a..84766d9e267f115293c0e2854ad77133dca1674b
review_round: 2
```

Round 2 covers the whole Batch range. The only code change since round 1 is correction commit 84766d9 (`repl.py`, `session_report.py`, `tests/test_chatgpt_usage.py`). Commit 74a291d and the parts of 84766d9 under `.ai/**` are bookkeeping and were not reviewed as implementation. Commit ea6a168 is outside the range.

Both round-1 important findings are resolved, and so is the Skill sibling. I found no new blocking or important issues. Ticket 04 still passes all six criteria and ticket 05 now passes all eight. Standards: no new code comments, `git diff --check` is clean, and the long lines follow the file's existing style (the repo has no line-length standard).

## Criteria: 04 Keep Subagents on the parent's ChatGPT account

Round 2 did not touch ticket 04's code paths (`subagents/`, `call_log.py`, `router.py`, `worker.py`). All 10 `tests/test_chatgpt_subagents.py` tests still pass in the round-2 full suite.

- AC1 inherited identity without tokens: pass. No change since round 1.
- AC2 rotation within generation and no retargeting: pass. No change since round 1.
- AC3 preserved delegation semantics and propagation of exhaustion: pass. No change since round 1.
- AC4 receipts and reconciliation once: pass. No change since round 1.
- AC5 dynamic secret protection and child replay: pass. No change since round 1.
- AC6 tests: pass. No change since round 1.

## Criteria: 05 Show current context and separate plan usage

- AC1 footer per route: pass. No change since round 1.
- AC2 occupancy formula and provenance: pass. No change since round 1. Suggestion 2 below is a narrow labelling edge case.
- AC3 invalidation of stale assessments: **pass** (round-1 finding 1 resolved).
  - Memory: `context_key()` now keys on `tuple(note["text"] for note in notes)`. Note text is the only Memory field that reaches the model; `router._build_system_prompt` renders only `note['text']`.
  - Skills: active Skills are keyed on `tuple(active_skills.items())`. `Skill` is a frozen dataclass, so equality compares instructions and fingerprint.
  - Todos are covered indirectly. They derive from `turns` and `todo_baseline`, which are already in the key or cleared by `/clear`.
  - The new regression test fails on the pre-fix source and passes at head.
  - A scratch probe (activate Skill, run a task, turn the Skill off, edit SKILL.md, re-activate it) shows `ctx ~N` reused before the fix (`[F,F,T,F,T]`) and `unknown` at head (`[F,F,T,F,F]`).
- AC4 `/usage` separation: pass. No change since round 1.
- AC5 `/report` grouping: **pass** (round-1 finding 2 resolved).
  - Plan-only delegation now renders `Delegated API cost subtotal: no API Attempts; delegated ChatGPT plan Attempts 1: cost unavailable`.
  - Mixed delegation renders `Delegated API cost subtotal: $0.5; coverage: 1/1 ...`.
  - API-only delegation keeps `Delegated cost subtotal: $X`, and the API-only scope is legitimate there.
  - Related money lines were checked: Session and group `recorded API $...`/`no API Attempts`, access-method and route compact rows (`no API Attempts` when every Attempt is plan use, under the header "API costs exclude ChatGPT plan use"), and `/usage` `spend: ... API cost ...; API-only subtotal`. No unscoped plan `$` figure remains.
- AC6 `/usage` and `/config` Manage usage, status and guidance: pass. No change since round 1.
- AC7 integration test: pass. No change since round 1, and it is still green.
- AC8 focused and full suite, docs: pass. The full suite gives 3038 passed. The README is unchanged in round 2.

## Findings

None blocking or important.

## Round-1 suggestions not applied

None of these needs to block.

1. "Context budget blocked:" prefix on ChatGPT session/auth errors. This dates from ticket 02 and is outside this Batch. The guidance stays actionable and dispatch is still blocked. Route it as a follow-up if wanted.
2. `repl._provenance` returns `manual` whenever any source is manual. With an assumed total and a manual output-only override, the label reads `manual` instead of `assumed`. This only happens with a user-chosen manual override, and the count is still shown as approximate (`~`). Optional: let `assumed` take precedence when `total_source` is assumed.
3. `/report` label duplication ("ChatGPT plan ChatGPT account ..."). Cosmetic only.
4. `credit_delegated_attempt` does not compare the receipt's `registration_ref` with the parent's pinned registration. This is defense in depth; it is not exploitable today, because the child config is pinned and the identity cannot be retargeted (04 AC2 tests).
5. `render_context_usage` drops a line by index (`usage[1:-1]`). This is positional coupling with no current defect.
6. New, optional: the Skill-content fix has no committed regression test. The scratch probe above shows that it works. A test like the Memory one would stop it regressing.

## Feature-level coverage (index.md requirement table)

Every row has deterministic proof across tickets 01 to 05: D1 to D10 and user stories 1 to 22.

- D9 (children inherit the account; accounting) is covered by real spawned-child tests for identity, refresh race, cancellation and exhaustion, plus receipt reconciliation, `/usage` and `/report` tests.
- D10 (footer, `/usage`, `/report`, `/config`) is now fully covered, including the two round-1 gaps.
- D7 (honest accounting) is covered for children and the report.

Remaining items, none of which affect the verdict:

- No authorized real-account smoke run has been done. The spec makes it optional and the README discloses this.
- The index still shows 04 and 05 as `ready`. That is orchestrator bookkeeping.
- Round-1 suggestion 6 (the CONTEXT.md Status Footer glossary entry) was addressed in bookkeeping commit ea6a168, outside the range.

## Checks

- Range: both SHAs resolve, dd628b1 is an ancestor of 84766d9, and the range has 4 commits (e6a16e6, b1eca1a, 74a291d, 84766d9). HEAD ea6a168 differs from head only in `.ai/PROJECT_STATE.md`, `docs/CONTEXT.md` and this review file. `git diff --check` over the range is clean.
- Regression proof: I ran a `git archive` snapshot of 84766d9 with `repl.py` and `session_report.py` restored from b1eca1a, with module path verified via `personal_agent.__file__`. `tests/test_chatgpt_usage.py` gave 3 failed and 7 passed: the two new tests, plus the updated linked-child label assertion. At head, all of them pass.
- Sibling probe: the scratch test for re-activating a Skill with changed content failed before the fix and passes at head. It ran outside the repo and was removed afterwards.
- Full suite on a snapshot of the head code (84766d9): 3038 passed in 452.18s. This matches the orchestrator's evidence (3038 passed in 457.22s).
- Mandatory BRANCH credential scan, complete for the 4 selected commits:
  - Coverage: 19 introduced blobs, commit messages, per-commit patches, the range diff and base/head versions of the changed files (tests and docs included). That is 56 artifacts, 2,031,301 bytes.
  - Scanner: Gitleaks 8.30.1 (binary SHA256 88f91962...5509, the same binary as round 1). It used explicit external defaults, no repo ignores, `--ignore-gitleaks-allow`, decode depth 3, archive depth 2 and no size cap.
  - Result: exit 0, no findings.
  - Comparison: 3 populated local credential values were compared in literal, Base64, hex and URL-encoded forms. The only matches were `PA_MODEL`, a model identifier already present at base in `tests/test_repl.py`, which is not a credential.
  - No confirmed credential leaks found in the reviewed changes.
- Vulnerability discovery and filtering were run in sequence. Round 1 already assessed every changed production file in the range. Round 2 adds only an in-memory equality key and report label strings, with no new trust boundary, sink or logging. No high-confidence HIGH/MEDIUM vulnerabilities found in the reviewed changes.
- Working tree: clean before and after. No commits, no pushes, and no live auth or inference.

## Residual risks

- Full Git history was not scanned, and decode/archive depth is bounded.
- Verification is synthetic only: no real login, account or inference.
- Readiness after an out-of-process disconnect is re-checked only on `/connect`, `/disconnect`, `/config` and at admission. An idle footer may lag, but dispatch stays blocked.
- Occupancy still does not track on-disk project-instruction edits made between tasks. That was noted in round 1 and is unchanged.
- Child exhaustion propagation depends on the child's result message. A child that dies before handoff leaves the parent un-exhausted until its own next plan request classifies the exhaustion.
