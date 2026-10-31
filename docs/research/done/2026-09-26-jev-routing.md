# TypeSafe AI Jev for next-turn tier routing

**Status (2026-10-17):** research only; no Jev API call or integration. Jev was rejected during [Session-tier discovery](2026-10-02-session-tier-selection.md); features 0039/0041 used the configured easy-route Evaluator instead, and feature 0054 (2026-10-16) removed tiers and the Evaluator entirely. The interface facts and integration notes below preserve the 2026-09-26 research, before the Classifier and Budget Guardrail were removed. Deleted source files are referenced by name.

**Research verdict (2026-09-26):** the API call is straightforward, but selecting the right model for the *next agent turn* still requires a tested rubric and relevant conversation context. Jev returns decisions, not answers or tool calls: it could classify the work needed for the agent's next response after receiving the user's message, before the existing answering Provider call. [TypeSafe: coding agents](https://docs.typesafe.ai/introduction/coding-agents.md), historical `classifier.py`, [local `router.py`](../../../src/personal_agent/routing/router.py)

## Interface and fit

- HTTP: `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer <API_KEY>`, `Content-Type: application/json`. Required JSON fields are `state` (string/object/array), `model` (`jev-latest` or version ID), and a nonempty `questions` map. A Choice requires `type`, `instructions`, and `criteria` (option-name → description or `null`); it returns the highest-probability `choice`, per-option `probabilities` summing to 1, and `confidence`. The response also includes resolved `model` and `usage.input_tokens`/`output_tokens`. [API reference](https://docs.typesafe.ai/api.md), [Choice](https://docs.typesafe.ai/primitives/choice.md)
- **Proposed request shape** (an adaptation of the documented schema, not a tested Jev result):

  ```json
  {
    "state": "Please debug why this Python service fails after the latest refactor.",
    "model": "jev-latest",
    "questions": {
      "tier": {
        "type": "choice",
        "instructions": "Which model capability tier is needed to answer the user's task well?",
        "criteria": {
          "easy": "A simple factual reply or a small, well-specified task",
          "medium": "Several steps or moderate judgment, without deep investigation",
          "complex": "Debugging, architectural tradeoffs, or sustained multi-step reasoning"
        }
      }
    }
  }
  ```

  **Response shape** (illustrative numbers only; not an observed response):

  ```json
  {
    "model": "jev-1.13.0",
    "answers": {
      "tier": {
        "type": "choice",
        "choice": "complex",
        "probabilities": {"easy": 0.02, "medium": 0.18, "complex": 0.80},
        "confidence": 0.70
      }
    },
    "usage": {"input_tokens": 300, "output_tokens": 30}
  }
  ```

  Actual probabilities, confidence, tokens, and model version must be read from the service response. [API reference: Choice answer](https://docs.typesafe.ai/api.md#choice-answer), [Models: aliases](https://docs.typesafe.ai/models.md#aliases)
- Python: official `typesafe-sdk` (`pip install typesafe-sdk` / `uv add typesafe-sdk`, Python ≥3.10) offers `TypeSafeClient().system_one(state=..., questions={"tier": Choice(...)})` and `response.answers["tier"].choice`; both sync and async clients exist. It reads `TYPESAFE_API_KEY`, defaults to `jev-latest`, and provides typed responses/retries. Direct HTTP avoids a new SDK and matches this repo's existing stdlib-`urllib` Provider approach, but requires local response validation, timeout/backoff and error handling. Jev would be a classifier dependency, not a drop-in answering Provider. [Quick start](https://docs.typesafe.ai/introduction/quickstart.md), [Python SDK](https://docs.typesafe.ai/sdk/python.md), [SDK constants](https://docs.typesafe.ai/sdk/python/api/constants.md), [local Provider decision](../../CONTEXT.md#decisions)
- A `Choice` maps directly to the closed set `easy`/`medium`/`complex`; `Score` instead yields a probability-weighted position that may fall *between* levels and needs a policy to map it to a tier. Intent (what action is requested) and complexity (how hard it is) are distinct judgments; the official intent-routing example asks both in one request. If insufficient information should prompt clarification, ask a separate question or include an explicit `unclear`/`other` option and let application code decide; a three-option Choice alone always selects one of those tiers. Jev does not generate the clarification text. [Primitives](https://docs.typesafe.ai/primitives.md#choose-a-question-type), [Intent routing](https://docs.typesafe.ai/patterns/intent-routing.md), [Choice: other option](https://docs.typesafe.ai/primitives/choice.md#good-practice-ask-more-than-one-question-per-call), [Coding agents](https://docs.typesafe.ai/introduction/coding-agents.md)
- **Local integration points:** `route()` currently calls `classify(task)` when `start_tier` is absent; the REPL already passes recent Conversation messages and a Conversation Summary to `route()`. A request like “pode seguir” is impossible to classify meaningfully from `task` alone; a bounded, relevant summary of the user's current goal and the latest exchange would be needed. The existing `/model` Tier Pin and Auto-Compress Continuation Turn supply `start_tier`, so they should bypass the Jev call. Jev is a pre-routing classifier, not a fifth answering Provider. [local `router.py`](../../../src/personal_agent/routing/router.py), [local `repl.py`](../../../src/personal_agent/terminal/repl.py), [State guidance](https://docs.typesafe.ai/concepts/state), [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
- **Operational work beyond the HTTP call:** choose an opt-in/API-key configuration, a short timeout and failure fallback, and how to account for and record a classifier call. Existing Provider retries, the Call Log Attempt entry, and Budget Guardrail apply to answering models, not automatically to a new pre-routing service; the common `post_json()` currently has a 60-second timeout. Decide what to store without exposing credentials or unnecessarily logging extra conversation text. These are repository-specific implications, not TypeSafe guarantees. [local `http.py`](../../../src/personal_agent/providers/http.py), [local `router.py`](../../../src/personal_agent/routing/router.py), historical `budget.py`, [local `call_log.py`](../../../src/personal_agent/call_log.py)

## Operational constraints and evidence gaps

- Published Jev 1.13 price: **$0.042 per million input tokens**, output tokens free; limits: **250,000 tokens/s and 1,200 requests/min**, subject to change without notice; 64k tokens per request, and 32k for `state` plus the longest question. The vendor claims **70–500 ms end-to-end** in its launch post, measured largely from West Coast laptops; this is not a latency guarantee for this local CLI or for every input. Every new turn would incur an extra network round trip and input-token charge, including easy turns. [Models](https://docs.typesafe.ai/models.md#current-models), [TypeSafe launch post](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- The launch announcement calls Jev **early access** and says developers are being admitted from a waitlist; the quickstart points to the console dashboard for an API key. Public documentation does not establish whether this operator has an enabled account, a free allowance, payment requirements, or an account-specific quota. No credential or authenticated endpoint was checked. [Launch post](https://typesafe.ai/blog/introducing-system-one-models-and-jev), [Quick start](https://docs.typesafe.ai/introduction/quickstart.md), [Models: listing models per account](https://docs.typesafe.ai/models.md#listing-models)
- Choice `confidence` is a **0–1 summary of how peaked the probability distribution is**, not a measured chance that the selected tier will produce a good answer. TypeSafe says calibration is a group property, not a correctness guarantee for an individual decision, and recommends testing thresholds on one's own data. Its Jev 1.13 limitations include literal interpretation, weak numerical precision, degradation with irrelevant state, adversarial state, and weak numeric calibration for Score levels. Keep rubric boundaries explicit, restrict state to relevant user text/context, and evaluate misroutes and threshold behavior on actual task examples before replacing the current deterministic classifier. Pin a version if thresholds are tuned to it: `jev-latest` can move. [Confidence](https://docs.typesafe.ai/confidence.md), [System One](https://docs.typesafe.ai/concepts/system-one.md), [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md), [Models: aliases](https://docs.typesafe.ai/models.md#aliases)
- Jev's own limitation page says it can struggle with multi-hop reasoning and tasks needing extended deliberation. Inferring the full implementation effort from a vague request could be such a task; the desired question here is narrower: what level of model is needed for the agent's *immediate next action*, perhaps asking for missing requirements. This fit is a hypothesis to test, not a demonstrated capability. A useful evaluation should include short broad requests (“crie um sistema de emissão de nota fiscal”), long but easy discussion, and context-dependent follow-ups (“continue”), with explicit target behaviors, false-cheap/false-expensive routing, latency, and actual per-turn cost. [System One](https://docs.typesafe.ai/concepts/system-one), [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13), historical `classifier.py`
- English is the primary training language and currently has the best accuracy. Other languages are handled but not equally well; **Portuguese-specific accuracy is not published**. Test Portuguese and mixed-language user turns separately rather than treating low/high confidence as proof of performance. [Models: language support](https://docs.typesafe.ai/models.md#language-support), [Confidence](https://docs.typesafe.ai/confidence.md)
- HTTP errors include `401` invalid/missing key, `422` malformed request, `429` rate limit, and `529` overload; the API recommends exponential backoff for `429`/`529`. The SDK defaults to two retries on `408`, `429`, and 5xx plus connection/timeouts, respects retry headers, has a 10-second **per-operation** timeout and a 30-second **total retry** budget. For a latency-sensitive pre-routing call, choose a shorter explicit budget and deterministic fallback policy; never interpret a failed response as a valid low-confidence classification. SDK response-validation failures and `403` permission errors are also exposed. SDK debug logs redact secret headers but **not request/response bodies**. [API reference: errors](https://docs.typesafe.ai/api.md#errors), [SDK retries](https://docs.typesafe.ai/sdk/python/api/retries.md), [SDK constants](https://docs.typesafe.ai/sdk/python/api/constants.md), [SDK exceptions](https://docs.typesafe.ai/sdk/python/api/exceptions.md), [SDK usage: logging](https://docs.typesafe.ai/sdk/python/usage.md#logging)

**Open questions:** actual account/key eligibility and applicable quota; real latency, per-turn token cost, and accuracy across easy/medium/complex and Portuguese; rubric and clarification/fallback thresholds. These require account access or representative evaluation, neither performed here. [Quick start](https://docs.typesafe.ai/introduction/quickstart.md), [Models](https://docs.typesafe.ai/models.md), [Confidence](https://docs.typesafe.ai/confidence.md)
