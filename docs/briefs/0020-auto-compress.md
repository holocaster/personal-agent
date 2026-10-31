# 0020 — Auto-compress

## Goal

Trigger Compression automatically when a Conversation's token usage gets close to the answering model's context limit, so the user does not have to remember to run `/compress` manually before hitting a provider error. Closes the "compaction automática" gap noted against the reference project `opencode` (see `docs/research/done/2026-09-23-opencode-feature-comparison.md`), reusing the `compress()`/`_compress()` machinery built for manual `/compress` (feature 0014).

## Scope

- **Trigger**: checked right after a routed turn completes successfully (inside `_execute_task`, after `turns.append(...)`). Fires when that turn's `prompt_tokens > 0.8 * context_limit`.
- **Context Limit**: `litellm.get_model_info(model).get("max_input_tokens")` for the model that answered the turn, wrapped the same defensively as `cost.py`'s `cost_per_token()` call (`try`/`except Exception`); a missing value, an unrecognised model, or a raised exception all fall back to a fixed 128,000-token limit. (`litellm.get_max_tokens()` was tried first and rejected during planning — it returns the model's max *output* tokens, e.g. 16,384 for `gpt-4o` versus its real 128,000-token input limit, which would have fired Auto-Compress far too early.)
- **Action on trigger**: run the existing Compression path unchanged (`KEPT_TURNS=2`, same `compress()` call, same `write_conversation_compressed` Call Log entry), then send one Continuation Turn — a synthetic message (not the user's original task) asking the model to continue or ask if anything is unclear. Sent through the normal turn path at the same Complexity Tier that answered the turn that crossed the threshold (a Tier Pin still wins; not re-classified from the synthetic text itself, which is too short to classify meaningfully). A normal turn in every other respect: appears in `/history`, undoable with `/undo`, logged like any other.
- **Edge cases**: `prompt_tokens is None` (Provider returned no usage) never triggers Auto-Compress. A threshold crossing with `len(turns) <= KEPT_TURNS` (too few turns to compress) is skipped silently — no error, unlike manual `/compress`'s "nothing to compress" message. A failed or interrupted automatic Compression shows the same error manual `/compress` shows, and sends no Continuation Turn.
- **Anti-loop cap**: at most one Auto-Compress-and-continue cycle per user-typed task. If the Continuation Turn's own response also crosses the threshold, it is compressed but not followed by a second continuation — control returns to the user.
- **Visible notice**: one line printed before the Continuation Turn's own output (e.g. `"Compressed N turns; continuing automatically.\n"`), since the user did not ask for that turn.
- **On by default**, no environment variable to turn it off — matches `/undo`/`/retry`/manual `/compress`'s always-on posture, not `ROUTER_ENABLE_SHELL`'s opt-in pattern.

## Out of scope

- A configurable threshold percentage or a per-tier context-limit override env var — the 80% margin and the 128k fallback are fixed constants, like `KEPT_TURNS`/`HISTORY_WINDOW` already are.
- Turn-count-based triggering — superseded by the token-vs-context-limit approach during grilling; `HISTORY_WINDOW`/`KEPT_TURNS` remain unrelated, unchanged constants.
- Tracking a cumulative token count across the Conversation — `prompt_tokens` of the most recent turn already reflects the full resent history (the REPL resends complete history every call, never incrementally), so no new accumulator is needed.
- A new Call Log entry type distinguishing "automatic" from "manual" Compression or turns — the Continuation Turn's own synthetic task text is self-descriptive in `/history` and the Call Log; no schema change.
- Auto-compressing on Resume before any new task runs — the trigger point stays "right after a turn completes," so a resumed Session already past the threshold waits for its first new turn like any other check.
- Disabling Auto-Compress for a single task or Run — no opt-out mechanism at all, matching the "on by default" decision.

## Settled decisions

1. **Metric is tokens vs. the answering model's context limit, not turn count.** Rejected turn-count triggering (simpler, no new dependency) after researching how `opencode` does this — the user chose the more faithful, higher-cost-to-build approach knowingly.
2. **Context Limit comes from `litellm.get_model_info(model).get("max_input_tokens")`, not a new manual env var**, because this project's models are free-form strings (`TIER_<TIER>_MODEL`) with no built-in catalog, and `litellm` is already a dependency used the same defensive way for Estimated Cost. `get_max_tokens()` was the first candidate (matching `cost.py`'s naming) but returns the model's max *output* tokens, not its context/input size — caught during planning by directly probing `litellm` in this project's `.venv`, not assumed. See ADR-0002's amendment.
3. **Unknown-model fallback is a fixed 128k**, not "skip Auto-Compress for that tier" — the user chose to keep protection active even for models `litellm` doesn't recognise, accepting the risk of an ill-fitting threshold for those models.
4. **Threshold margin is 20% of the limit (fires at 80% usage)**, a percentage rather than a flat token count, so it scales correctly whether the limit came from `litellm` or the 128k fallback.
5. **After compressing, the REPL auto-continues with a synthetic Continuation Turn**, not a re-send of the user's original task (which already got its answer) and not silence (which would leave the compression invisible). Mirrors `opencode`'s behavior, confirmed via direct source research rather than assumption (`packages/opencode/src/session/compaction.ts`).
6. **The Continuation Turn starts at the tier that answered the turn that crossed the threshold**, not re-classified — its own synthetic text is short enough that the Classifier would likely misroute it to `easy` regardless of what tier the real conversation was running at. A Tier Pin still overrides it, same as any turn.
7. **Capped at one cycle per user-typed task** — a recursion/anti-loop guard the user asked for explicitly, since nothing otherwise bounds a model that keeps answering near the threshold.
8. **A visible one-line notice precedes the Continuation Turn** — an answer appearing without the user having typed anything needs a signal, or it reads as a bug.

## Open questions

None — grilling frontier closed and confirmed by the user on 2026-09-24.

## Known issues

None yet — feature not yet implemented.
