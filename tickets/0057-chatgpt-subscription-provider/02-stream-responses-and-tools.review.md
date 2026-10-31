# Ticket 02 review

```yaml
status: approved
ticket: "0057/02"
reviewed_range: f110c053659a6fc5e03ea055d925b742076b56ec..6e82522effe007f6e6e65a76d93b9ac1b130cd8a
review_round: 4
```

Standards: no findings. Spec: no blocking or important findings; AC1–AC11 pass. The round-3 finding is resolved: `observe()` (`src/personal_agent/providers/chatgpt.py:223-228`) gives initial `output_item.added` text, deltas, part/text done events and item/completion snapshots one shared prefix state. Earlier corrections still hold (exact finalized-text equality, stable content types, hidden refusal).

## Round-3 finding verification

- New Router regressions `test_initial_item_text_must_be_kept_by_snapshots_before_tools` (item/completion x different/same/extended) and `test_initial_item_text_plus_delta_completes_answer` pass at head. With only `chatgpt.py` reverted to `6e82522^`, they fail (3 failed, 4 passed in 3.81s): both contradictory cases and the initial-plus-delta case.
- Independent probe, 19 passed: initial + delta + exact `output_text.done`/`content_part.done` completes, and streamed text is emitted exactly once. Wrong, shorter, extended or replaced finalized text is rejected before Tools run. A closed part followed by an extended snapshot is rejected. Losing initial text in a snapshot is rejected. Initial-prefix snapshot extension emits only the suffix. An inline refusal and a refusal delta stay hidden. An inline output_text followed by a refusal delta at the same index is rejected. A non-string inline text is rejected. The standard public shape (`content: []`, then `content_part.added` empty, delta, done events) completes.

## Suggestions (optional)

- `chatgpt.py:365-366`: a `content_part.added` for a part already declared inline in `output_item.added` is now rejected as `Duplicate Responses content part`. This fails closed and only affects a shape that is not the documented public wire shape (message items start with `content: []`), so it does not block. An identical re-declaration could be accepted idempotently if a real stream ever shows that shape.
- `chatgpt.py:225`: the condition `A and B and C or D` is correct under Python precedence, but explicit parentheses would make the two rejection rules easier to read.

## Checks

- Exact endpoints resolved. HEAD 04aaaa8 differs from head only in `.ai/PROJECT_STATE.md`. The exact-range `git diff --check` is clean. The tree was clean before and after the checks. No commits or pushes.
- Provider file: 128 passed in 14.34s. Focused text/type/initial subsets: 70 passed. Full suite: 3000 passed in 404.62s, which matches the orchestrator's evidence (3000 passed).
- Mandatory BRANCH credential scan is complete for 13 selected commits and 30 changed blobs: 1,092 artifacts and 9,953,924 bytes, covering messages, per-commit patches, the range diff and exact base/head trees, including tests, docs and orchestration files. Scanner was Gitleaks 8.30.1, binary SHA256 88f91962aa2f93ac6ab281d553b9e125f5197bbbce38f9f2437f7299c32e5509 (the same verified binary as round 3). It used explicit external defaults, no repo ignores or inline allows, decode depth 3, archive depth 2 and no file-size cap. Exit 1 came from the same six pre-existing fixture false positives, unchanged in base and head: `tests/test_provider.py:763` and `tests/test_routing.py:27,160` (Claude model identifier next to an API-key label). The two populated API-key values from the project and home dotenv files were compared in literal, Base64, hex and URL-encoded forms: zero matches. Separate matches were for the non-secret `PA_MODEL` model identifier in unchanged docs/tests, not credentials. No confirmed credential leaks found in the reviewed changes.
- Sequential vulnerability discovery and filtering covered the changed production files, focused on the round-4 delta. No high-confidence HIGH/MEDIUM vulnerabilities found in the reviewed changes. Inline initial text uses the same `StreamText` secret filter as deltas.

## Residual risks

Full Git history was not scanned, and decode/archive depth is bounded. Verification is synthetic only: no real login, account or inference. Undocumented `response.metadata` compatibility is still unverified and is not a finding. Durable continuity, child inheritance and full reporting remain for tickets 03–05.
