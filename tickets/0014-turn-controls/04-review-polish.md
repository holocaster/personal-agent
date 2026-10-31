# 04: Polish from ticket 03 review

**What to build:** Three small fixes that the ticket 03 review suggested and
the user asked for.

**Blocked by:** 03 (done).

**Spec:** `docs/specs/0014-turn-controls.md` (Compression); **ADRs:** none.

- [x] `/compress` confirms with correct grammar: `Compressed 1 turn.` for one
  replaced turn, `Compressed N turns.` otherwise. Update the test that
  asserts the old text.
- [x] The summary call's System Prompt leaves out the rules for using Tools,
  since the call advertises no Tools. Routed turns keep today's System
  Prompt unchanged. Add a test that captures the summary request's system
  text.
- [x] Rewrap the README lines added by ticket 03 that run past the file's
  usual wrap width. No content change.
- [x] Full offline suite passes.
