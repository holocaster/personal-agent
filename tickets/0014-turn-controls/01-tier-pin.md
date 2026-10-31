# 01: Pin a Complexity Tier with /model

**What to build:** The user types `/model <easy|medium|complex>` and every
later routed turn of the Run skips the Classifier and starts at that tier;
`/model auto` removes the pin and `/model` shows it. Escalation and the
Budget Guardrail behave as today, starting from the pinned tier. The Status
Footer shows an active pin. `/help`, Tab completion and the README cover
`/model`.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0014-turn-controls.md` (Implementation Decisions:
Router start tier, Tier Pin state, `/model` command, Status Footer, Commands
list, README; Testing Decisions); **ADRs:** ADR-0001.

- [x] `route()` accepts an optional starting Complexity Tier; when given the
  Classifier is skipped and the Escalation ladder starts there. When absent,
  behavior is unchanged (existing routing tests still pass).
- [x] `/model easy|medium|complex` sets the pin for the rest of the Run and
  confirms it; later routed turns reach the pinned tier's Provider and model
  regardless of what the Classifier would pick.
- [x] `/model auto` removes the pin and confirms it; later turns are
  classified again.
- [x] `/model` with no argument prints the pinned tier name or `auto`.
- [x] Any other argument (including a raw model id) or more than one argument
  prints a local error naming the valid values and leaves the pin unchanged.
  `/models` keeps its current behavior.
- [x] A pinned tier that fails technically still Escalates (ADR-0001), and the
  Budget Guardrail still blocks that Escalation when exceeded.
- [x] The Status Footer carries a segment naming the pinned tier while a pin
  is set, and is exactly today's text without one.
- [x] The pin is not written to the Call Log and a Resume starts at `auto`.
- [x] `/help` lists `/model`, Tab completes it in the Input Box, and the
  README's REPL commands section documents it.
- [x] Tests cover the above at the `route()`, `run_repl` and `InputBox`
  seams. Full offline suite passes.
