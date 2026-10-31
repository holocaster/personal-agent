# Ticket 04 review

```json
{
  "status": "approved",
  "ticket": "tickets/0053-stable-sessions-and-recovery/04-task-routes-and-cache-accounting.md",
  "reviewed_range": "9c8214d78c543c020d0f73d63a5f0433d0790cee..ba965838a3a1a36146dfd32062f3fcb934ed0475",
  "criteria": [
    {
      "criterion": "R15: latest 20 explicit opened executions, original ordinal, submission/Retry, Run/opening/outcome and at most 16 route groups",
      "result": "pass",
      "evidence": "Execution deque/route bounds in session_report.py; independent test_report_correlates_routes_by_explicit_openings_and_not_text and bounds test passed."
    },
    {
      "criterion": "R15/R16: physical Attempt attribution uses explicit boundaries; duplicate text, Retry ordinal, process death, maintenance and legacy evidence stay truthful",
      "result": "pass",
      "evidence": "Openings, Turn End, next opening and Run close reset current execution; damaged records stop attribution. Ordinary and auxiliary purpose groups retained. Existing multi-Run tests and new duplicate-text/damage tests passed."
    },
    {
      "criterion": "R16: per-route Attempts/retries, duration, first-text coverage, tokens/cache and cost provenance; observed changes with no causality claims",
      "result": "pass",
      "evidence": "_Group.compact includes independent coverage and reported/estimated/unknown cost; only known ordinary Provider/model comparisons mark changes. Rendering code inspected and production render assertions independently passed."
    },
    {
      "criterion": "R17: compatible same-sample cache-read fraction and independent missing/invalid coverage",
      "result": "pass",
      "evidence": "Fraction excludes nonpositive denominators, noninteger/negative counters and inconsistent subsets. Independent fixed sample test passed: 20/200 = 10%, coverage 2/7; other valid metrics retained."
    },
    {
      "criterion": "R17: bounded rendering/scanning, aggregates before details, redaction and terminal sanitization",
      "result": "pass",
      "evidence": "16 KiB rendering bound; latest 20 executions, 16 route groups, bounded route labels and 8 diagnostics; reuse existing session_logs.records bounded reader. 414-Attempt/23-execution bound and redaction tests passed."
    },
    {
      "criterion": "R18: four-Provider stream/nonstream/failure cache normalization and Anthropic TTL preservation",
      "result": "pass",
      "evidence": "Independent stream/failure matrix passed. Anthropic prompt sums disjoint input/read/write; other providers retain inclusive prompt. Invalid stream evidence preserves independent counters and existing error semantics."
    },
    {
      "criterion": "R19: locked local LiteLLM cache read/write/TTL accounting, unavailable unsupported/incomplete prices and authoritative OpenRouter cost",
      "result": "pass",
      "evidence": "Independently inspected actual LiteLLM 1.102.0 cost_per_token/provider/generic calculator and original model_cost guard. Real calculator fixed-price assertions passed: Anthropic split TTL $1.52, default write/OpenAI $1.12, Gemini cached input $0.22. No fixed multiplier. OpenRouter amount remains exact."
    },
    {
      "criterion": "R19: documented omitted-zero policy, missing report coverage, estimated provenance, one Run-spend charge and unchanged historical costs",
      "result": "pass",
      "evidence": "Official contracts independently fetched through Context7 and primary source fallback. OpenAI requires both supplied cache counts for estimate; Anthropic requests no cache_control and supports omitted uncached categories; Gemini scalar zero can be omitted per proto/ProtoJSON. Spend and failure tests passed."
    },
    {
      "criterion": "R20: no-argument local-only report preserves routing/input, Conversation/pending work, usage, spend and configuration",
      "result": "pass",
      "evidence": "Independent state-preservation test forbids transport/tokenizer access and verifies unchanged state with only existing Audit Events; existing no-argument and Resume tests passed."
    },
    {
      "criterion": "R32: all affected callers/fakes/tests updated; concise README/research and glossary proposal; no dependency/configuration changes",
      "result": "pass",
      "evidence": "14-file exact diff inspected; shared HTTP and stream paths cover all four Providers. Existing doubles now accept kwargs and assert inclusive Anthropic totals; regression assertions retained. Glossary proposal is in implementation handoff for Main to apply."
    },
    {
      "criterion": "R32: focused and full offline regression evidence",
      "result": "pass",
      "evidence": "Reviewer independently ran 896 focused tests, all passed in 39.13s. Inspected implementer final full-suite log at /tmp/0053-ticket04-final-retry-pytest.log: 2644 passed in 139.56s, plus handoff matching final code. Existing .venv fallback authorized because offline uv rebuild lacks hatchling."
    }
  ],
  "standards": {
    "status": "pass",
    "findings": [],
    "evidence": "Read pinned CLAUDE.md and CONTEXT, applied supplied AGENTS simplicity/comment constraints and smell baseline; no hard standard violations or concrete structural-risk smell found. Existing module seams, dependencies and provider callers are reused."
  },
  "spec": {
    "status": "pass",
    "in_scope_findings": [],
    "evidence": "Every active ticket criterion assessed against R15-R20, R32 and local correlation/accounting decisions. Optional upstream diagnostics appropriately omitted rather than looked up."
  },
  "findings": [
    {
      "severity": "suggestion",
      "scope": "preexisting/outside active ticket acceptance criteria; does not affect verdict",
      "location": "src/personal_agent/providers/http.py:112-127; baseline http.py:109-115; unchanged tests/test_context_budget.py:172",
      "impact": "Existing Gemini cost/output accounting omits separately reported thought tokens. This predates ticket04 and is independent of cache-read/write pricing. Cache-specific R19 obligations are satisfied; this approval does not establish complete Gemini billed-output accounting.",
      "evidence": "Read actual baseline and implementation normalized usage plus locked LiteLLM Gemini transformation at lines1895/1919-1920. Independent probe ran actual sanitized base and head functions with synthetic local rates input=.01/output=.02, prompt10/candidates5/thought20/cache0. Both return completion_tokens5 and estimate$0.20; candidate+thought output would be$0.60. Existing regression test explicitly preserves candidate-only semantics. Brief current review section records accepted separate limitation.",
      "required_change": "Track a separate Gemini output/reasoning normalization change with candidate-inclusive detection and stream/nonstream/failure evidence; retain this limitation in current feature documentation."
    }
  ],
  "checks": [
    {
      "check": "Mandatory sdd-security-review BRANCH",
      "result": "passed",
      "range": "9c8214d78c543c020d0f73d63a5f0433d0790cee..ba965838a3a1a36146dfd32062f3fcb934ed0475",
      "scanner": "Gitleaks 8.30.1",
      "evidence": "Verified cached official release archive SHA256 against published checksum file and executable against archive. Fresh external-config scan of 876 private selected-artifact/base/head context exports, including selected commit message and all 14 changed-file blobs, diff/log, tests/docs and relevant unchanged sources. No repository ignore/baseline, --ignore-gitleaks-allow, decode depth3/archive depth2/redact100. Seven repeated public Anthropic model identifier matches classified false positives. Four populated relevant credential values compared locally in literal/Base64/hex/URL-encoded forms: zero artifact matches. Two current bookkeeping reference files additionally scanned: zero candidates. Raw exports and raw findings removed. Full Git history was not scanned."
    },
    {
      "check": "Vulnerability discovery and false-positive filtering",
      "result": "passed",
      "evidence": "Sequential source-only assessment of changed cost.py, HTTP/stream usage normalization and session_report.py with unchanged provider callers/guards and bounded storage scanner. No confirmed credential leaks found in reviewed changes. No high-confidence HIGH/MEDIUM vulnerabilities found in reviewed changes. Security assessment executed no repository code/exploit."
    },
    {
      "check": "sdd-code-review Standards then Spec",
      "result": "passed",
      "evidence": "Exact pinned sanitized diff/log and base/head snapshots used throughout. Context: /tmp/review04-h95sphuv/context; mapping.json pins exact SHAs and source paths. Current-only implementation handoff and accepted brief separately sanitized under context/current. No implicit HEAD review."
    },
    {
      "check": "Locked LiteLLM and provider contracts",
      "result": "passed",
      "evidence": "uv.lock pins1.102.0; independently inspected installed cost_calculator.py dispatch, per-provider calculators, generic_cost_per_token, parse_prompt_tokens_details, calculate_cache_writing_cost, original price lookup. Context7 resolved/queried /berriai/litellm, /websites/developers_openai_api, /anthropics/anthropic-sdk-python, /websites/ai_google_dev_api. Primary docs confirm Anthropic total input and5m/1h TTL split, OpenAI optional read/write subsets, Gemini implicit-presence cached scalar and ProtoJSON omitted-zero semantics."
    },
    {
      "check": "Independent focused pytest",
      "result": "passed",
      "command": ".venv/bin/pytest -q tests/test_cache_accounting.py tests/test_session_report.py tests/test_provider.py tests/test_streaming.py tests/test_native_streaming.py tests/test_context_recovery.py tests/test_context_budget.py tests/test_compression.py tests/test_call_log.py tests/test_session_tier.py tests/test_detailed_audit.py",
      "evidence": "896 passed in39.13s; require_escalated used for existing localhost fixtures."
    },
    {
      "check": "Final full-suite available evidence",
      "result": "passed",
      "evidence": "Read /tmp/0053-ticket04-final-retry-pytest.log and implementation handoff. Final observed implementer run:2644 passed in139.56s. Reviewer did not repeat full suite; independently reran896 relevant cases."
    },
    {
      "check": "Preexisting Gemini output diagnosis",
      "result": "failed",
      "scope": "out of scope; preexisting",
      "evidence": "Symptom-specific actual base/head probe reproduced identical$0.20 instead of candidate+thought$0.60 under synthetic rates. Existing candidate-only completion semantics unchanged; recorded as separate known limitation."
    },
    {
      "check": "Exact code/checkout parity and cleanliness",
      "result": "passed",
      "evidence": "git diff --quiet ba965838a3a1a36146dfd32062f3fcb934ed0475 -- src tests exited0. HEAD is later bookkeeping ce36d20121621f43ec708aabeeb020619190d2ba. Final git status --porcelain clean; reviewer made no tracked changes or commits."
    }
  ],
  "sources": [
    "https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create",
    "https://developers.openai.com/api/docs/guides/deployment-checklist",
    "https://platform.claude.com/docs/en/build-with-claude/prompt-caching",
    "https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/usage.py",
    "https://raw.githubusercontent.com/googleapis/googleapis/master/google/ai/generativelanguage/v1beta/generative_service.proto",
    "https://protobuf.dev/programming-guides/json/#presence-and-default-values"
  ],
  "residual_risks": [
    "Preexisting Gemini thought-token/output undercount is retained and separately documented; approval covers ticket04 cache accounting only.",
    "Conservative OpenAI policy leaves cost unavailable unless both cache categories are supplied; missing evidence remains unknown rather than fabricated free input.",
    "No paid Provider calls or real cache-hit/latency/savings experiments. Current-source contracts and synthetic fixed-rate offline cases establish accounting behavior, not production savings.",
    "Full Git history intentionally not scanned. Existing ignored local credential configuration was comparison input, not a leak finding.",
    "Full suite independently inspected rather than rerun;896 relevant tests were independently executed. No standalone lint/typecheck configured."
  ]
}
```
