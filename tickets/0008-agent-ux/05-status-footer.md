# 05: Status Footer

**What to build:** Under the Input Box's lower rule, one line shows the last answer's tier and model, what the Session has spent, the Budget Guardrail limit when set, and a `/help` hint, e.g. ` easy · minimax/minimax-m3 · $0.0009 / $1.00 · /help`. It updates after every answer.

**Blocked by:** 04 (Input Box) - the footer renders inside its bottom toolbar.

**Spec:** `docs/specs/0008-agent-ux.md` (R12, R13, R14).

- [x] A pure function renders the footer: `<tier> · <model> · $<spent>[ / $<limit>] · /help`; spent with 4 decimals, limit with 2 decimals and only when a Budget Guardrail is configured; the tier/model segment omitted before the first successful answer. Unit-tested for before-first-answer, after an answer, with and without limit.
- [x] Tier and model are those of the last successful answer in this Session; a failed request does not change them.
- [x] Spend is read from `call_log` through one new public function returning the existing running total (the value `session_end` reports as `total_cost`). No third counter; the Budget Guardrail's own counter is untouched.
- [x] The REPL supplies the footer to the Input Box's bottom toolbar callable, so it re-renders on every draw.
- [x] Driven `run_repl` with a pipe-input Input Box: after a routed answer with a scripted cost, the rendered footer text shows that tier, model and the Call Log total.
- [x] Piped mode shows no footer; full offline suite passes.
- [x] README mentions the footer's fields in one line.
