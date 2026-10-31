# 0001 - Model router

## Goal

A terminal tool that takes a task, classifies its complexity, routes it to the matching model tier on OpenRouter, and logs the decision — so routing cost/latency data exists before any smarter (LLM-based, cascading) classifier is built.

## Scope (v1)

- Terminal REPL: `input()` loop, one task per line, prints the chosen tier + model + the model's answer. No session/conversation history — each line is one independent `route(task)` call.
- `Classifier`: deterministic heuristic (e.g. word count / keyword signals) mapping a task string to a `Complexity Tier` (`easy` / `medium` / `complex`). No model call involved in classifying.
- `Tier Config`: each tier's OpenRouter model ID comes from an environment variable (e.g. `TIER_EASY_MODEL`, `TIER_MEDIUM_MODEL`, `TIER_COMPLEX_MODEL`), not hardcoded. No default model IDs are shipped — attempts to look up real OpenRouter model IDs returned unreliable/contradictory data (see Open questions), so the user fills these in from their own OpenRouter dashboard before first run.
- `Router`: looks up the tier's model in Tier Config and calls it via a plain `call_openrouter(model, system, messages) -> str` function. No provider interface/Protocol — there is exactly one provider.
- Logging: append one JSON line per call to a log file (tier, model, cost, latency, timestamp). No database.
- Requires an `OPENROUTER_API_KEY` environment variable. No other provider credentials needed.

## Out of scope (this feature)

- Escalation cascade (retrying a task on a higher tier when the cheap tier's answer "looks unreliable"). Revisit once real usage data from the JSONL log shows the heuristic classifier is wrong often enough to matter.
- Tool-calling / function-calling support, and the cross-provider `tool_use`/`tool_result` normalization it would require.
- Any provider besides OpenRouter (no direct Anthropic API adapter, no LiteLLM).
- Multi-turn conversation history / session memory in the REPL.
- Any UI beyond a terminal REPL (no TUI library, no web UI).
- Forking, cloning, or depending on `NousResearch/hermes-agent` — see `CLAUDE.md` and `docs/CONTEXT.md`. It is reference reading only.
- Messaging-platform integrations (Telegram, Discord, etc.) and the Hermes "skills" self-improvement loop mentioned in `HANDOFF.md` — both explicitly deferred, no ticket for either in this feature.

## Settled decisions

See `docs/CONTEXT.md` for the durable glossary (`Complexity Tier`, `Router`, `Classifier`, `Tier Config`, `Provider`) and the two cross-cutting decisions (OpenRouter-only scope, hermes-agent as inspiration-only). Feature-specific decisions not durable enough for `CONTEXT.md`:

- No provider abstraction/interface for a single provider — add one if/when a second provider is actually built, not preemptively.
- Classifier is heuristic-only in v1; no LLM-as-judge classifier yet.
- Logging format is JSONL (append-only file), not SQLite — zero new dependency, good enough for the field count needed now.

## Open questions

- Exact OpenRouter model IDs for each tier: two lookup attempts (WebFetch on the OpenRouter models page, WebSearch + WebFetch on the hermes-agent GitHub repo) both returned contradictory/implausible results in the same session (e.g. repo star count and feature claims changed between two fetches of the same page) and were discarded as unreliable rather than used. The user will confirm real model IDs from the OpenRouter dashboard; v1 ships with placeholder env var values documented in the README/setup instructions.
