# Feature 0052 independent verification

status: approved
tickets: 01, 02, 03
reviewed_range: e1a05429a48e2072043ef2c4a2e97742ffe369ff..5b03e0f960594a86b191dfb53b38eb42387b571a
working_tree_patch_sha256: cb70728e6aeee41f4a0be4a5b94cfd2c5d20f102b82ddac0ff11eff82d205374
observed_HEAD: 2aa1a0e063e14fd5c3a4ff1ff2e1239015041a45

Approval was issued for the committed baseline plus the exact correction patch before committing it. The baseline alone retains the original filtered-completion defect.

## Standards and Spec

No remaining findings. All R01–R17 pass for the combined snapshot. The previous R08/R09/R16 finding is resolved: both OpenAI and OpenRouter accept valid `content_filter`, preserve completed termination, drain final accounting and `[DONE]`, and record one successful Attempt/Turn End with known token/cache usage and reported OpenRouter cost. Missing `[DONE]`, unsupported finish reasons and filtered Tool completions still fail safely. Help now names all four Providers.

R01–R07, R10–R15 and remaining R17 evidence is unchanged and verified against the exact full-feature range. Existing Provider, Router, replay, Call Log and terminal seams remain intact; no new dependencies, architecture or unnecessary comments.

## Security and verification

- Mandatory BRANCH security completed: retained verified Gitleaks 8.30.1 baseline evidence for 12 commits/424 artifacts; eight matches were unchanged fixture/model identifiers. Fresh patch/source/test/reference scan covered 13 artifacts/210,052 bytes, exit 0, with no candidates.
- External default rules, repository-ignore bypass, decode depth 3/archive depth 2; private literal/encoded configured-key comparison found zero occurrences. Sequential vulnerability discovery/filtering found no high-confidence HIGH/MEDIUM vulnerabilities.
- Red regressions proved the defect before correction: four expected failures. Focused correction checks: 503 passed; nine sandbox socket failures all passed with permitted local sockets.
- Fresh reviewer independently ran 21 original-scenario/malformed-protocol cases: 21 passed in 2.66s. Evidence: `/tmp/review0052-filter-independent.log`.
- Full installed suite after correction: `.venv/bin/python -m pytest -q`, 2441 passed in 113.80s with permitted local sockets. Independent reviewer inspected `/tmp/review0052-filter-full.log`; no duplicate full-suite run.
- Actual production/test diff exactly matched `/tmp/review0052-filter.patch`; hashes were verified before and after independent tests. `git diff --check` passed. Reviewer made no edits, staging, commits, pushes or reverts.

## Reviewed correction hashes

| File | SHA256 |
| --- | --- |
| `src/personal_agent/providers/chat_completions.py` | `d5749921adfb401af6a6f842e8823d08a8970625e828dc12191df2be192822e9` |
| `src/personal_agent/terminal/repl.py` | `7edef78ea5fee4fe3f13be974e0ab174845677882442b57ce141964fd3d3a6a3` |
| `tests/test_streaming.py` | `412ab38bc61ddf54166c01e3b1e7fbff64e09c3f6ee278937f392e625418bc17` |

## Limits

Simulated Provider streams; no paid/live requests or full-history credential audit. The correction was independently reviewed before user authorization to commit and push. Sanitized evidence: `/tmp/review0052-full-security/safe` and `/tmp/review0052-filter-security/safe`; raw correction exports/reports removed.
