# 01: `/usage` command — session usage without a Provider call

**What to build:** A new REPL command `/usage` that prints, from state
already held in this Run only (no Provider call, no Call Log file read):

- The last successful answer's Complexity Tier and model (the same pair the
  Status Footer shows), or a local message when no turn has completed yet
  this Run.
- This Session's total spend (`call_log.total_cost()`), marked as estimated
  when the last successful Attempt's cost was estimated (the `cost_estimated`
  flag already defined by Estimated Cost in `docs/CONTEXT.md`).
- The last successful Attempt's `prompt_tokens` and `completion_tokens` -
  the exchange that produced the last shown answer, not a running list of
  every Attempt this Session.
- Turns retained in the Conversation (`len(turns)`) versus turns that fit in
  the Context Window (`min(len(turns), HISTORY_WINDOW)`).

**Blocked by:** None (can start immediately).

**Spec:** none (fast path); **ADRs:** none.

- [x] `RouteResult` (`src/personal_agent/routing/router.py`) carries the last
      successful exchange's `prompt_tokens`, `completion_tokens`, and
      `cost_estimated`. `_run_exchange` already computes these in `usage` for
      the Call Log entry (`router.py` around the `call_log.append_entry`
      call) and currently discards them afterward - thread them through
      instead of recomputing anything.
- [x] `run_repl` (`src/personal_agent/terminal/repl.py`) tracks the last
      successful RouteResult's usage fields the same way it already tracks
      `last_tier`/`last_model`.
- [x] `/usage` is added to `COMMANDS`, `HELP_TEXT`, and `_handle_command`'s
      dispatch.
- [x] `/usage` before any completed turn this Run prints a local message and
      makes no Provider call (same "nothing to do yet" pattern already used
      by `/undo` and `/retry`).
- [x] `/usage` after at least one successful turn prints: tier + model,
      session spend (`$` formatting consistent with `render_footer`, plus an
      "estimated" note when applicable), the last Attempt's prompt/completion
      token counts, and turns retained vs. turns sent.
- [x] `/usage` takes no arguments; extra arguments are rejected the same way
      other no-args commands already are.
- [x] The output-building logic is a small pure function (mirroring
      `render_footer`'s style) with a direct unit test, plus one REPL-level
      test exercising `/usage` both before and after a successful turn.
- [x] README's REPL command list (the `/help` bullets, starting around line
      213) gets a `/usage` bullet in the same style as its neighbors.
