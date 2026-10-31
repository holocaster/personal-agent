# Review: 0037/03

status: approved
ticket: 0037/03
base_sha: be1b25159f69d72b40fa18d5feb6d9c7e6e9ceb2
head_sha: 27236ba9390441a307666cfda87f1de1034fbbe7
reviewed_range: be1b25159f69d72b40fa18d5feb6d9c7e6e9ceb2..27236ba9390441a307666cfda87f1de1034fbbe7

## Criteria

- AC1 common gate, input-only thresholds, mandatory ceilings, protected turns and unchanged-request suppression: pass.
- AC2 actual-route candidate measurement before commit, best-effort target and failure preservation: pass.
- AC3 Gemini historical replay/consumed rebasing, exact active signatures and Tool correlations, no Tool reruns: pass.
- AC4 commit before pending Turn End, synchronized state, Resume/Undo/Clear/Todo and Tool evidence: pass.
- AC5 notices in both terminal modes, pending exchange only, isolated diagnostics and normal costs: pass.
- AC6 required boundaries, source coverage, failures, real offline replay and focused/full suites: pass.

## Findings

None on Standards or Spec/ADR-0001/0002/0005. The common gate is inside the retry loop at `router.py:555-637`; candidate measurement precedes commit at `:596-605`. Local obstruction does not Escalate. Gemini tracks active boundaries and rebases consumed positions at `gemini.py:100-110,142-145`. REPL reuses the log-before-mutation commit at `repl.py:328-334`.

## Independent evidence

- Exact SHAs resolved. Tested HEAD `fd2e228b33cdabf112ddaa6bf7e4e9d68c5a6ef2` differs from implementation head only in `.ai/PROJECT_STATE.md`.
- `uv run --offline pytest -q tests/test_preventive_compression.py tests/test_compression.py tests/test_repl.py tests/test_routing.py tests/test_provider.py tests/test_tools.py tests/test_todo.py tests/test_call_log.py tests/test_detailed_audit.py`: 559 passed in 24.32s.
- `uv run --offline pytest -q tests/test_preventive_compression.py`: 40 passed in 3.60s.
- `uv run --offline pytest -q tests/test_preventive_compression.py -k real_offline_gemini`: 2 passed, 38 deselected in 3.26s. Socket/DNS denied with zero attempts; once-only prepared input, exact signatures, grouped responses, ids and state preservation verified.
- Locked counting libraries verified: LiteLLM 1.102.0, tiktoken 0.14.0, tokenizers 0.23.2.
- `uv run --offline pytest -q`: 1413 passed in 83.24s.
- Exact-range `git diff --check`: passed. Final tree clean; no reviewer edits or commits.

## Route

Mark 0037/03 done and continue 0037/04. Provider transport is scripted, not paid live API verification; local estimates remain approximate. Provider overflow recovery belongs to 04. Optional `uv build --offline` was unavailable to the implementer because hatchling was not cached; no packaging/dependency changes were made.
