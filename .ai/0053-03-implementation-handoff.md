# Feature 0053: stopped after ticket 03 implementation

User requested stopping after the current implementer, then saving the resume point on 2026-10-14. No reviewer or subsequent ticket was started after that request.

Canonical state: `.ai/PROJECT_STATE.md`; spec: `docs/specs/0053-stable-sessions-and-recovery.md`; ticket statuses: `tickets/0053-stable-sessions-and-recovery/index.md`. The brief records scope and local commit authorization; pushes, paid API calls and sudo remain unauthorized.

## Completed versus pending

- Tickets 01 and 02 are independently approved, with their exact ranges and security evidence in their `.review.md` files. CONTEXT includes their accepted selection and Provider-affinity changes.
- Ticket 03 is **ready_for_review**, not approved or done. It implements stable prompt/catalogue ordering and exactly three production-surface fixtures for plan/build/auto.
- Tickets 04 (report/cache-aware accounting) and 05 (file recovery) remain unimplemented. Recovery must receive its own isolated review.
- After resuming, review ticket 03 before starting another implementer; complete all remaining tickets and final feature verification through `sdd-main`.

## Exact ticket 03 handoff

Status: `ready_for_review`.

Ticket: `tickets/0053-stable-sessions-and-recovery/03-stable-prompt-prefix-and-surface-fixtures.md`.

Immutable base/resumed-from: `796b253e5822b1a41a444fa093ad5d7471511616`.

Implementation head: `db492807c36814e551efae1dee2e290fda42df89`.

Review exactly that two-dot range; later commits only record the orchestrator handoff. No code review/security verdict for this range exists yet.

Fourteen intended files changed: production `routing/router.py` and `tools/registry.py`; README and the two dated research notes; `tests/README.md`, `tests/prompt_surface.py`, `tests/test_prompt_surface.py`; three fixtures under `tests/fixtures/prompt-surface/`; routing, detailed-audit and REPL tests. Source and test paths are relative to their established directories.

## Verification evidence

- Surface checks: 26 passed in 13.93s. Production request capture includes all four Providers' complete input, prefix and budget assertions.
- Focused integration: 1,501 passed in 89.25s; `/tmp/feature0053-ticket03-focused.log`.
- First full sweep: 2,555 passed and three obsolete ordering expectations failed; independently reproduced at `/tmp/feature0053-ticket03-expectations-red.log`.
- Named calculator/schema/advertised-order assertions and immediate Memory assertions preserve prior behavioral coverage; 243 passed in 18.48s at `/tmp/feature0053-ticket03-expectations-green.log`. Sibling assumptions were searched; meaningful Tool execution/result order remains unchanged.
- Final full suite: **2,558 passed in 132.88s**; `/tmp/feature0053-ticket03-full-green.log`.
- Compilation, exact-range whitespace and post-commit clean-tree checks passed.
- Plan fixture advertises 14 Tools; build/auto 18. Active Skills preserve beta→alpha activation order; catalogue descriptions sort alpha→beta. Changed clock/root/home/credentials and hash seeds 1/991 produce byte-identical fixtures; real prompt/schema changes fail comparison.
- Memory-only common system prefix is 1,563 bytes (prepared: OpenRouter/OpenAI 1,605; Anthropic 1,660; Gemini 1,698). Todo-only is 2,098 (prepared: 2,154/2,154/2,209/2,247). These are structural observations, not cache-hit/savings evidence.

Use installed `.venv/bin/pytest`; batches containing local HTTP/MCP/process fixtures need `require_escalated`. Default sandbox socket restrictions were proved on the unchanged baseline. Offline uv metadata rebuild requires uncached hatchling, so installed pytest is the authorized offline fallback; no dependency/build-cache change is needed. Temporary logs/tools may disappear between sessions; their absence is not a successful verification.

Mandatory reviewer security capability currently available: verified official Gitleaks 8.30.1 at `/tmp/personal-agent-0053-tools/gitleaks` (archive SHA256 `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`). Run a fresh BRANCH scan for the exact ticket 03 range, with sanitized context; earlier ticket scans do not cover this commit. Full Git history and live model/cache behavior were not checked.

## Proposed CONTEXT changes after approval

The implementer left parent-owned CONTEXT untouched. Apply its accepted changes only after the independent review:

**System Prompt:** The instruction text sent to the Provider ahead of the Conversation. Rebuilt for every Provider exchange. Ordinary exchanges order application identity, fixed Tool/trust rules, current Agent Mode and language behavior, the task's Project Instructions snapshot, Memory, active Skills in activation order, Conversation Summary and unfinished Todo List. Changing only variable context preserves preceding stable bytes; project, mode or catalogue changes may alter them. Compression offers no Tools. Current date and time come from current_time rather than a changing prefix. Prepared-input budgets and Provider replay remain complete; stable prefix does not guarantee cache hits, savings or unchanged full-history input.

**Prompt surface snapshot:** A deterministic offline fixture of complete system text and ordered canonical Tool schemas captured through production Router/Provider requests. Three fixtures cover plan/build/auto with isolated synthetic context/configuration and blocked network. Deliberate regeneration: `.venv/bin/python -m tests.prompt_surface tests/fixtures/prompt-surface`, then review diffs. Catalogue names/effective Skill descriptions are deterministic; active Skill order and meaningful arrays preserve semantics. Snapshots complement behavioral tests and do not measure quality or cache savings.

Suggested skills: `sdd-main` to orchestrate; fresh `sdd-reviewer` with `sdd-security-review` and `sdd-code-review` for ticket 03; `sdd-implement`/TDD for remaining tickets; Context7 and deep-analyse for uncertain Provider/LiteLLM semantics. Durable file/commit state takes precedence over this narrative.
