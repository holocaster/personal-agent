# Escalate only on technical failure, not answer quality

Superseded by [ADR-0006](0006-persist-session-tier-and-remove-escalation.md), implemented in feature 0039. Automatic Escalation is removed; the text below records the prior decision.

`route()` needed a trigger for Escalation between Complexity Tiers. `reference_model_router.py` sketches a content heuristic (`looks_unreliable`: empty answer or refusal-like text) — we considered adopting it and rejected it. Judging an answer's *quality* from its text is a classifier/judge problem in its own right (false positives on short-but-correct answers, no principled way to detect "wrong but well-formed"), and `docs/CONTEXT.md` already defers a model-based Classifier ("judge") as future work, not built yet. Escalation instead triggers only when a Tier's Attempt budget is fully exhausted by technical failures — a deterministic, verifiable condition with no heuristic tuning.

## Consequences

A technically successful but substantively wrong answer will never trigger Escalation under this design. Revisit only alongside building a real judge/classifier, not by bolting a content heuristic onto `route()`.
