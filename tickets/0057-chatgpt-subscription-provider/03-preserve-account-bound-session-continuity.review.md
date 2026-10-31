# Ticket 03 review

```yaml
status: approved
ticket: "0057/03"
reviewed_range: 4f854f5cae14ea519110fd27a601c07c87980c54..42a899bd0a4e3150ad85592655f43e1aac878e65
review_round: 2
```

Standards: no hard violations. Spec: round-1 finding 1 (AC2) is resolved. AC1 through AC9 pass. The range also contains bookkeeping commits 613b0b7 (ticket 02) and 4263653 (`.ai/PROJECT_STATE.md`); neither was reviewed as implementation. Later commit 1505184 is bookkeeping only and is outside the range.

## Criteria

- AC1 additive v3 provenance: pass. Unchanged from round 1. Attempt `access_method`/`registration_ref` are now also validated on read (`_read_entries`). Every writer emits either `api_key`, or `chatgpt_plan` together with a binding registration, so no valid log is newly refused. An Attempt without `access_method` is still accepted.
- AC2 validated replay and rejection before append: **pass**. `validate_items` now keeps the preceding assistant's `(id, name)` calls as an ordered pending list. Each `tool_result` must pop the next call exactly, an assistant cannot arrive while calls are pending, and nothing may stay pending at the boundary. The same function is used on Resume (`call_log._turn`), at Turn End write (`write_turn_end`) and for v2 pending continuations.
- AC3 same-model/registration replay and same-registration reauth: pass.
- AC4 Retry without repeating Tools, with interrupted outcomes: pass. The in-order requirement matches production. `router` runs calls serially and appends completed results first, then interrupted/not-executed results in call order. `test_interrupted_batch_...` still passes.
- AC5 route/account change, portable text and notice: pass. The notice now compares against the last ChatGPT Attempt's registration. A -> API -> A prints no notice. A -> API -> B still differs from A and prints it. A Session that never used ChatGPT still returns `None`, so the first ChatGPT send prints it.
- AC6 Fork: pass. A Fork after an API interlude now carries the last ChatGPT registration as `destination`.
- AC7 Compression/clear/Undo/recovery: pass. Unchanged.
- AC8 redaction and readers: pass. Unchanged.
- AC9 tests: pass. The new regression test covers the round-1 shapes (call answered by another id, duplicated result) and checks that the file is unchanged. A notice test covers the API interlude.

## Findings

None blocking or important.

## Suggestions (optional)

1. `docs/CONTEXT.md` "ChatGPT continuity" still says "The last Attempt's registration is the durable destination". After this round it is the last *ChatGPT* Attempt's registration. Update that one phrase (CONTEXT.md is orchestrator-owned).
2. `call_log.py` `_valid_access` and `_validate_session_origin` import `valid_reference` inside the function. `call_log` already imports `routing.continuation` at module top, and that module imports `chatgpt_auth` at top, so there is no cycle to avoid. A top-level import would be simpler. This has no behavioural impact.

## Checks

- Range: both endpoints resolve. HEAD 1505184 differs from head only in `.ai/PROJECT_STATE.md` and this review file. `git diff --check` over the exact range is clean. The tree was clean before and after; temporary probe files were removed. No commits or pushes.
- Sibling-shape probe (direct `validate_items`, scratch script outside the repo). Rejected: a missing second result followed by a final answer, all results missing, a pending prefix ending with an unanswered call, a result before any call, a mismatched result name, swapped result order, an extra result after all calls were answered, a result answering another id, an item `call_id` that differs from its message, and `complete=True` ending on an assistant with calls. Accepted: a valid two-call completed turn, a valid multi-round turn and a valid `complete=False` pending prefix.
- End-to-end Resume probe (temporary test, since removed). A real ChatGPT Tool turn was written, then its Turn End was damaged in three ways: missing result, result moved before its call, and changed result name. Each `load_conversation` raised `ResumeError` "invalid Responses replay" and left the file byte-identical (3 passed).
- Regression proof: the round-2 tests were run against the pre-fix source of 4263653 (git archive into scratch, module path verified). `test_completed_turn_with_unanswered_or_repeated_tool_result_is_refused[other-call|duplicate]` and `test_notice_tracks_last_chatgpt_registration_across_api_turns` fail there, and the other 15 continuity tests pass.
- Full suite at head code: 3018 passed in 413.13s. This matches the orchestrator's evidence (3018 passed).
- Mandatory BRANCH credential scan, complete for 4 selected commits (4f854f5..42a899b). It covered 22 introduced blobs, the commit messages, per-commit patches, the range diff and the base/head versions of every changed file, including tests, docs and orchestration files: 62 artifacts, 2,088,060 bytes. Scanner: Gitleaks 8.30.1 (the checksum-verified binary from round 1, SHA256 88f91962aa2f93ac6ab281d553b9e125f5197bbbce38f9f2437f7299c32e5509). It used explicit external defaults, no repo ignores, `--ignore-gitleaks-allow`, decode depth 3, archive depth 2 and no size cap. Exit 0, no findings. The populated values from the project and home dotenv files were compared in literal, Base64, hex and URL-encoded forms. The API-key variables had zero matches. The only matches were `PA_MODEL`, a model identifier (not a credential) that is already present at base in `tests/test_repl.py`. No confirmed credential leaks found in the reviewed changes.
- Sequential vulnerability discovery and filtering covered every changed production file. Round-2 deltas checked: stricter replay validation (it only narrows what is accepted), `valid_reference` (same regex, `isinstance` guard kept) and read-time Attempt validation (it refuses but never trusts). No high-confidence HIGH/MEDIUM vulnerabilities found in the reviewed changes.

## Residual risks

Full Git history was not scanned, and decode/archive depth is bounded. Verification is synthetic only: no real login, account or inference. Read-time Attempt validation makes a Session with a hand-corrupted Attempt access field unreadable to every `_read_entries` caller, consistent with openings. `last_destination()` still re-reads the whole Session file on each ChatGPT dispatch with retained context; this is linear in log size and not a finding. Child inheritance (04) and occupancy/usage reporting (05) remain open.
