# 02: Continuation Turn after Auto-Compress, with notice and one-cycle cap

**What to build:** After a successful automatic Compression, the REPL prints
one notice line and sends one Continuation Turn - a fixed synthetic message
asking the model to continue or ask if anything is unclear - at the tier that
answered the crossing turn (a Tier Pin still wins). At most one
Auto-Compress-and-continue cycle runs per user-initiated turn.

**Blocked by:** 01 (Auto-Compress a turn that nears the Context Limit) - the
Continuation Turn follows the automatic Compression it adds.

**Spec:** `docs/specs/0020-auto-compress.md` (Requirements R6-R9;
Implementation Decisions: REPL, Router, Call Log; Further Notes); **ADRs:**
ADR-0001, ADR-0005.

- [x] After a successful automatic Compression the REPL sends
  `CONTINUATION_TASK` (exact text in spec R6) through the normal turn path;
  after a failed one, it sends nothing.
- [x] The Continuation Turn starts at the Tier Pin if set, else at the tier
  that answered the crossing turn; the Classifier is not called for it.
  Escalation and the Budget Guardrail apply as to any turn.
- [x] It is a normal turn otherwise: Call Log Attempts and Turn End, tier line
  and `llm>` answer, appended to the Conversation, shown by `/history`,
  removable by `/undo`, the most recent routed task for `/retry`, and the last
  answer for `/usage` and the Status Footer.
- [x] When a Continuation Turn follows, the confirmation line reads
  `Compressed N turn(s); continuing automatically.` (singular/plural as
  manual `/compress`), printed once, before the Continuation Turn's output.
- [x] If the Continuation Turn itself crosses the threshold, it is compressed
  (with the plain `Compressed N turn(s).` line, or the same error on failure),
  but no second Continuation Turn is sent and control returns to the prompt.
  The cap resets on the next typed task or `/retry`.
- [x] Call Log order is: crossing turn's Turn End, `conversation_compressed`,
  Continuation Turn's Attempts and Turn End; Resume rebuilds the same
  Conversation, including the Continuation Turn. No Call Log schema change.
- [x] The README documents the Continuation Turn, its notice, and the
  one-cycle cap.
- [x] Tests at the `run_repl` seam with the fake Provider: continuation sent
  with the synthetic text at the crossing turn's tier model; Tier Pin wins;
  notice precedes the continuation's output; no continuation after a failed
  Compression; a continuation that crosses again is compressed but not
  continued; `/undo` removes the Continuation Turn; Resume after a
  continuation. Full offline suite passes.
