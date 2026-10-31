```yaml
status: approved
ticket: tickets/0055-fork-jobs-claude-cache/01-claude-prompt-caching.md
reviewed_range: 401962468078aaa1b9478f65e17bb9dd01c8c79a..ed4ecfc9b60d77a8b63f8693bd735c66985a5acd
criteria:
  - criterion: "Direct Anthropic adds top-level cache_control {type: ephemeral} to every payload, streaming and non-streaming; no ttl, no block markers, no beta header"
    result: pass
  - criterion: "OpenRouter adds the field only when the exact model id starts with anthropic/; other routes unchanged; provider prefs and session_id unchanged"
    result: pass
  - criterion: "Marker outside prepared input; token counts, budgets, audit request and prompt surface fixtures unchanged"
    result: pass
  - criterion: "Offline Provider tests incl. Compression on a Claude route; accounting, affinity and prompt surface suites green"
    result: pass
  - criterion: "README caveat; research proposal marked delivered"
    result: pass
  - criterion: "Focused and full installed suite pass; no live or paid call"
    result: pass
findings:
  - severity: suggestion
    location: docs/research/done/2026-10-14-cache-and-session-routing.md:34
    impact: "Body still says no cache_control is sent, unlabelled as historical. Documentation only."
    required_change: "Optional: label as historical evidence."
checks:
  - "Security BRANCH mode over 4019624..ed4ecfc: gitleaks 8.30.1 (2 pre-existing false positives at tests/test_provider.py env var name line), known-secret comparison found no confirmed leaks; no HIGH/MEDIUM vulnerabilities."
  - "Standards and Spec axes: no violations; R1-R3 and ticket share of R17 met; out-of-ticket test key-list edits accepted."
  - "Focused run: 294 passed. Full run: 2628 passed in 168.78s, offline."
residual_risks:
  - "Live acceptance of top-level cache_control by every OpenRouter Anthropic host with require_parameters: true is unproven offline."
  - "Real cache hits depend on minimum cacheable length; README caveat covers it."
```
