# 04: Keep Subagents on the parent's ChatGPT account

**What to build:** A parent task delegates to an isolated child that uses the same pinned account/model and capacity, refreshes safely and returns attributed plan usage once. This slice isolates the process/credential boundary and is independently verifiable using a synthetic child process.

**Blocked by:** 03 — Preserve ChatGPT continuity through Retry, Resume, Fork and Compression.

**Spec:** [0057](../../docs/specs/0057-chatgpt-subscription-provider.md), D4 credential generations/redaction, D7 exhaustion/usage, D8 child evidence and D9; **ADRs:** [0015](../../docs/adrs/0015-chatgpt-subscription-provider.md), [0014](../../docs/adrs/0014-native-subagent-process-isolation.md).

**Areas:** Subagent snapshot/payload/worker/receipt reconciliation, child Runtime Configuration, Call Log attribution and synthetic process tests. Reuse the shared account lifecycle module; do not build a credential broker or another agent runtime.

- [ ] A real child process receives the parent's exact Provider/model, `chatgpt_plan`, opaque registration/session generation and capacity snapshot. OAuth tokens are not serialized as API keys or placed in model context/role instructions/receipts. Worker credential resolution uses private storage and the shared cross-process lock.
- [ ] Refresh rotation stays within the inherited session. Another REPL's model/account change cannot retarget parent or child; disconnect/replacement generation blocks future child/follow-up inference and returns a safe failure/handoff rather than adopting the global active account. Test the switch between parent admission and worker dispatch as well as concurrent parent/child refresh.
- [ ] Existing role Tool narrowing, Agent Mode/confirmation delegation, one-child limit, child Session linkage, cancellation/background-job cleanup and fatal evidence propagation remain intact. A failed/exhausted child does not auto-resume or select a billing fallback. Child plan exhaustion propagates its classified condition to stop further parent inference on that pinned plan in the current execution, preserving retryable parent/child evidence instead of attempting another plan request for synthesis.
- [ ] Receipts and disk reconciliation preserve access-method/registration identity, valid observed token details and unknown monetary cost. Each physical child Attempt contributes once to parent visible usage across receipt/reconcile paths, including error/interruption/duplicate receipt. ChatGPT child cost stays null; API child spend aggregation remains unchanged.
- [ ] Register dynamically refreshed secrets inside each process and protect streamed output, parent/child errors, IPC results/receipts and detailed logs against original/replacement/retired token echo. Preserve valid compatible child replay without crossing account bindings.
- [ ] Use real process tests with temporary private credential storage and synthetic transport/worker bootstrap for inherited identity, refresh race, disconnected generation, plan exhaustion, duplicate reconciliation and parent cancellation. Run focused Subagent/account/session tests and the full suite; no real OAuth or inference.
