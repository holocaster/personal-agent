# 01: Stable selection with historical replay

**What to build:** A fresh Session evaluates initially and then keeps its tier until explicit user action. `/model auto` requests one keep/raise evaluation, including Retry, and Resume removes old schedules without losing history, input or pending work.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0053-stable-sessions-and-recovery.md` — Stable selection R1–R7, Delivery R32, Routing policy version 2, Testing Decisions. **ADRs:** 0009; retain historical 0007 and existing 0005/0006 guarantees.

- [x] Fresh pending Session evaluates once before first task; tasks 5, 15 and beyond do not evaluate. Manual tier before first task bypasses evaluation.
- [x] `/model auto` retains tier/count/corpus and coalesces a one-shot request; no schedule is enabled. Selected tiers only keep/raise automatically, and manual selection can lower/cancel requests.
- [x] Accepted submission identity/input remains independent of Conversation, including duplicate text, manual periods, failed/interrupted tasks and unfinished submissions. Retry retains ordinal and adds no corpus text; local commands, Tool follow-ups and Question answers add none.
- [x] Clear drops corpus and continuation, preserving count/tier/request; Undo and Compression retain corpus. Cumulative full bounded evaluation, isolated purpose/usage/accounting and current-task attribution remain.
- [x] Initial failure chooses medium; later completed failure keeps tier and consumes request. Cancellation stops ordinary dispatch and retains initial/explicit request through Retry/new task/Resume.
- [x] Implement additive policy version 2 and strict exact historical version-1 validation. First Resume durably migrates selected old Sessions without scheduled evaluation, retaining old count/texts/tier/Conversation/Summary/Todo/continuation. Retain genuine initial/explicit outstanding requests, including cancellation, but discard obsolete scheduled-only due state.
- [x] Valid historical logs before/at checkpoints 5/15, already complex and manual, policy-less selected/pending/missing-tier and mixed old→new logs all Resume correctly. Missing-tier warning remains once, absent old tracking starts empty, and subsequent Resume does not migrate again.
- [x] Invalid policy types/versions/transitions, submission order and inconsistent migration fail strictly. Version-1 replay must not use new runtime transition rules; backward migration is invalid. Do not rewrite old lines.
- [x] Persist submission, policy migration/commands, Clear and completion before live state/dispatch. Inject partial append and failed prefix restoration; failures halt with no dependent dispatch or evaluator fallback. Preserve existing immutable task configuration, same-route retries/overflow, budgets, spend and pending continuation semantics.
- [x] `/model`, HELP_TEXT, completion/footer notices and piped/interactive outcomes state initial/explicit evaluation and show retained selection separately from pending evaluation; no remaining-checkpoint claim persists.
- [x] Update production CLI/Call Log/REPL state callers, shared evaluator stubs and affected fixture expectations together. Keep old scheduling tests as historical replay tests or replace runtime expectations with equivalent new coverage; do not remove persistence/identity assertions.
- [x] Update concise README/CLAUDE/package identity and dated routing-research status for implemented behavior; propose exact CONTEXT glossary/decision edits to orchestrator. No Runtime Configuration or dependency changes.
- [x] Run targeted session-tier, continuation, Call Log, REPL/main, runtime configuration, input-box, detailed-audit and compression/context checks, then full `uv run --offline pytest -q` with sandbox escalation for existing local socket/MCP tests. Report actual results, committed files, range and known limitations.

**Implementation reach:** `routing/session.py`, Call Log replay/writers, terminal REPL and footer/CLI callers. Preserve layer ownership: REPL owns selection lifetime, Router executes an explicit Tier. Add a small version boundary, not a generalized policy framework.

**Standalone value:** Users receive stable selection immediately, and valid historical Sessions remain readable independently of affinity, reporting and recovery.
