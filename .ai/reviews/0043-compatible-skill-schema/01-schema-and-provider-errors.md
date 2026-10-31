# Independent review: ticket 0043

```yaml
status: approved
ticket: 0043/01-schema-and-provider-errors
reviewed_range: frozen-before0043..frozen-after0043 (uncommitted six-file delta)
git_head: 72821bbf2cabccbb514c46035054af5b053bda91
head_sha: unavailable; no commit was created
criteria:
  - criterion: Advertised skill parameters are an object without prohibited root-level combinators; scalar name and array names remain supported across Providers.
    result: pass
    evidence: registry.py removes only root oneOf and retains both properties; eight Provider/argument-form cases inspect actual OpenAI/OpenRouter/Anthropic/Gemini requests and results.
  - criterion: Local validation requires exactly one selector, preserves length/count/unique/extra-field constraints, and rejects malformed input before instruction loading.
    result: pass
    evidence: registry.execute_batch retains Draft202012Validator validation and adds the selector XOR before workspace_skills.load; eleven malformed-input cases replace load with pytest.fail.
  - criterion: Captured invalid_function_parameters rejection remains a readable non-retryable request/schema error with original evidence, never ToolsUnsupportedError.
    result: pass
    evidence: test_openai_invalid_skill_schema_remains_original_nonretryable_http_error asserts the original HTTPError object, exact rejection message/code and is_retryable False.
  - criterion: Tool support classification requires positive evidence; unrelated 400/404/422 stay HTTP errors; positive unsupported cases, context-overflow priority and usage remain covered.
    result: pass
    evidence: twelve unrelated-Tool errors preserve diagnostics/usage; four explicit support rejections preserve cause/usage; existing four-Provider unsupported and context-overflow precedence tests remain, and overflow handling still runs before Tool detection.
  - criterion: Actual advertised skill wire-shape regressions and focused/existing checks pass without live API calls.
    result: pass
    evidence: eight request-shape integration cases; verified focused tool output exit 0, 257 passed in 9.14s; combined 1940-test full-suite result already independently verified in review 0044.
findings: []
checks:
  - All twelve endpoint SHA256 hashes match manifest.json; four live code/test files still match the fixed after snapshot. README/CONTEXT assessed from the pinned after copies, excluding later 0044 additions.
  - Standards and Spec reviewed sequentially using current AGENTS.md/CLAUDE.md and ticket acceptance criteria; fixed six-file delta excludes inherited 0042 and subsequent 0044 implementation.
  - BRANCH security review used the explicitly authorized frozen local-change fallback. Full Git history was not scanned.
  - Reused Gitleaks 8.30.1 official binary with published SHA256 previously verified; external default rules, ignores disabled, decode depth 3, archive depth 2, redaction enabled.
  - Credential scan covered 29 selected artifacts / 531174 bytes, plus one unchanged context-overflow test / 8380 bytes. Two generic-api-key candidates were the identical unchanged Provider tuple at tests/test_provider.py:745 in both endpoints; local AST inspection confirmed a Claude model identifier, not a key. Zero matches against local credential comparison variants. No confirmed credential leaks found in reviewed changes.
  - Sequential vulnerability discovery and false-positive filtering found no high-confidence HIGH/MEDIUM vulnerabilities introduced by this delta.
  - Focused result verified from actual custom_tool_call_output, transcript line 389, timestamp 2026-10-05T11:17:22.173Z, call_77ITPYyihTKx7MfGLipFDCJk, exit 0, 257 passed in 9.14s.
  - Existing combined full result is available in /tmp/personal-agent-0044-security/sanitized/test-results.json: transcript line 941, exit 0, 1940 passed in 94.85s. It includes subsequent 0044 and is integration regression evidence, not a claim that the fixed 0043 snapshot alone ran 1940 tests.
  - No full-suite rerun, real Provider calls, production edits, ERP operations, commits, branches, stash, reset, or Git changes were performed.
residual_risks:
  - Exact scope is a SHA256-verified uncommitted snapshot delta, not an immutable Git base..head commit range; caller explicitly prohibited creating commits.
  - Provider compatibility is verified against captured rejection evidence, source and mocked HTTP wire shapes; live Provider integrations were intentionally not invoked.
  - Security coverage excludes unrelated local changes and full history. Raw private scan artifacts/reports were removed; sanitized context remains under /tmp/personal-agent-0043-security/sanitized.
```

## Standards

No documented-standard violation or concrete costly smell found. The correction stays in existing registry/HTTP seams, introduces no dependency, and adds no source comments.

## Spec

All five acceptance criteria pass. The root schema rejection is addressed directly; local selection validation preserves the argument API. Error classification now uses explicit unsupported-support phrases while preserving the captured schema error and earlier overflow precedence.

Findings: Standards 0 (none); Spec 0 (none).
