# 0001 - Model router

Brief: `docs/briefs/0001-model-router.md`
Glossary and cross-cutting decisions: `docs/CONTEXT.md`

## Problem Statement

Every task the user throws at an LLM today goes to one model, chosen by habit. Trivial tasks ("summarize this line") pay frontier-model prices and latency; genuinely hard tasks sometimes land on a model too weak for them. The user has no data about which is happening or how often, so there is no basis for deciding whether a smarter routing strategy (an LLM-based classifier, an escalation cascade) would be worth building.

The user wants a terminal tool that makes the routing decision explicit and records it, so that after some real usage there is a log to look at instead of an intuition to argue with.

## Solution

A small Python terminal REPL. The user runs it, types a task, and sees three things: the Complexity Tier that was chosen, the model that tier maps to, and the model's answer. Each line typed is one independent task — there is no conversation history.

Behind the prompt, the Router runs the task through the Classifier (a deterministic heuristic over the task text, no model call), looks the resulting Complexity Tier up in Tier Config (three model IDs read from environment variables), and calls that model through the Provider (OpenRouter). Every call appends one JSON line to a Call Log file recording the task, the tier, the model, the latency, and whatever cost/usage the Provider reported.

The user supplies their own model IDs via environment variables, because the point of the tool is to compare tiers the user actually cares about, and because correct current OpenRouter model IDs could not be established at planning time (see Further Notes).

## User Stories

1. As a terminal user, I want to start the tool with a single command, so that I can use it without a setup ritual.
2. As a terminal user, I want a prompt that accepts one task per line, so that I can fire off tasks as fast as I can type them.
3. As a terminal user, I want each line I type to be handled independently, so that a previous task never contaminates the next answer.
4. As a terminal user, I want to see which Complexity Tier my task was assigned, so that I can judge whether the Classifier got it right.
5. As a terminal user, I want to see the concrete model ID that was called, so that I know exactly what produced the answer.
6. As a terminal user, I want to see the model's answer printed below the routing line, so that the tool is actually useful and not just a classifier demo.
7. As a terminal user, I want to leave the REPL cleanly by typing an exit command or pressing Ctrl-D, so that I do not have to kill the process.
8. As a terminal user, I want a blank line to be ignored rather than sent to a model, so that a stray Enter does not cost me money.
9. As a terminal user, I want short, simple tasks to be routed to the cheap tier, so that I stop paying frontier prices for trivia.
10. As a terminal user, I want long tasks to be routed to a stronger tier, so that length-heavy work is not handed to an undersized model.
11. As a terminal user, I want tasks containing hard-work signals (refactor, architecture, debug, prove, design a system) to be routed to the complex tier regardless of length, so that a one-line hard question is not mistaken for an easy one.
12. As a terminal user, I want the Classifier to be deterministic, so that the same task always routes the same way and the Call Log is interpretable.
13. As a terminal user, I want classification to cost nothing, so that routing overhead never exceeds the savings it produces.
14. As a terminal user, I want each tier's model ID to come from an environment variable, so that I can retune tiers without editing code.
15. As a terminal user, I want the tool to refuse to start when a required environment variable is missing, and to name every variable that is missing, so that I fix my setup once instead of discovering it one failed call at a time.
16. As a terminal user, I want the tool to refuse to start when `OPENROUTER_API_KEY` is absent, so that I do not type a task and then lose it to an auth error.
17. As a terminal user, I want the README to show the exact export lines with placeholder model IDs, so that I know precisely which values to fill in from my OpenRouter dashboard.
18. As a terminal user, I want no model IDs baked into the code, so that the shipped defaults can never silently send my traffic somewhere I did not choose.
19. As a terminal user, I want every call appended as one JSON line to a log file, so that I can analyze routing with standard line-oriented tools.
20. As a terminal user, I want the log line to include the task text, so that I can later review which tasks the Classifier routed wrongly.
21. As a terminal user, I want the log line to include the tier and the model ID, so that I can group cost by tier.
22. As a terminal user, I want the log line to include measured latency, so that I can compare tiers on speed and not just price.
23. As a terminal user, I want the log line to include the cost and token usage the Provider reported, so that I can total my spend per tier.
24. As a terminal user, I want a missing cost or usage field to be recorded as null rather than crashing the call, so that an unexpected Provider response never loses me an answer.
25. As a terminal user, I want the log line to include a UTC timestamp, so that I can slice usage over time.
26. As a terminal user, I want the log file location to be configurable by environment variable with a sane default, so that I can keep logs outside the repo.
27. As a terminal user, I want the log file to be created if it does not exist and appended to otherwise, so that history accumulates across sessions.
28. As a terminal user, I want a failed Provider call to print a readable error and return me to the prompt, so that one bad call does not end my session.
29. As a terminal user, I want a failed call to still be logged with its error, so that failures are visible in the same data as successes.
30. As a terminal user, I want Ctrl-C during a call to abort that call and return me to the prompt, so that I am not stuck waiting on a slow model.
31. As a terminal user, I want a bounded request timeout, so that a hung Provider call cannot freeze the REPL indefinitely.
32. As a maintainer, I want the Classifier to be a pure function from task text to Complexity Tier, so that its rules can be tested without any network.
33. As a maintainer, I want the whole routing path tested through one fake at the HTTP boundary, so that tests assert the real outgoing request rather than a mock of my own abstraction.
34. As a maintainer, I want tests to assert which model ID was sent in the request body, so that a Tier Config or Router regression fails loudly.
35. As a maintainer, I want the Call Log asserted by reading the written file, so that the log format is tested as the artifact a user will actually parse.
36. As a maintainer, I want no runtime third-party dependency, so that the tool runs on a bare Python install.
37. As a maintainer, I want no Provider interface or Protocol while there is exactly one Provider, so that the code does not carry an abstraction nothing uses.
38. As a maintainer, I want the escalation cascade left unbuilt, so that the decision to build it is made from Call Log evidence rather than from the sketch it came from.

## Implementation Decisions

**Language and dependencies.** Python 3.12, standard library only at runtime — the Provider call uses `urllib.request`, not `requests`. `pytest` is the only development dependency. This keeps the "zero new dependency" posture already settled for the Call Log format consistent across the feature.

**Modules.** Six small modules inside one package, named after glossary terms:

- *Classifier* — `classify(task) -> Tier`. Pure, no I/O, no model call.
- *Tier Config* — reads the three tier model IDs and `OPENROUTER_API_KEY` from the environment, validates them, and exposes the tier-to-model lookup.
- *Provider call* — `call_openrouter(model, system, messages) -> (answer, usage)`. A single plain function. No `ProviderAdapter` Protocol, no adapter registry: there is exactly one Provider (`docs/CONTEXT.md`, Provider scope).
- *Call Log* — appends one JSON object per line to the log file.
- *Router* — `route(task)`: classify, look up, call, time it, log it, return tier + model + answer.
- *REPL* — the input loop and the printing.

**Complexity Tier representation.** A three-valued enum (`easy` / `medium` / `complex`) whose values are the strings used in the Call Log and in the environment variable names. Tier is never passed around as a bare string.

**Classifier rules (v1, deterministic).** Evaluated in order against the lowercased task:

1. `complex` if the task contains any complex signal (`refactor`, `architecture`, `prove`, `debug`, `design a system`) or has more than 200 words.
2. `medium` if it has more than 40 words.
3. `easy` otherwise.

Word count is whitespace-split length. The signal list is a module-level constant so it can be tuned from Call Log evidence later. These thresholds are a starting point to generate data, not a claim of accuracy — the brief's whole premise is that they are wrong often enough to be worth measuring.

**Tier Config contract.** `TIER_EASY_MODEL`, `TIER_MEDIUM_MODEL`, `TIER_COMPLEX_MODEL`, and `OPENROUTER_API_KEY` are all required. There are no hardcoded model defaults anywhere in the code — placeholder values live only in the README. Validation happens once at startup, before the first prompt is shown, and reports every missing variable in one message, then exits non-zero.

**Provider call contract.** `POST https://openrouter.ai/api/v1/chat/completions` with `Authorization: Bearer <key>`, JSON body carrying `model` and `messages`, and a bounded timeout (60s). The answer is read from the first choice's message content. Usage/cost is read defensively: any of cost, prompt tokens, completion tokens that the response does not carry is recorded as `null` rather than raising. The exact shape of OpenRouter's cost reporting was not verifiable at planning time, so the implementer confirms it against a live response and the code tolerates its absence either way.

**System prompt.** A single fixed system message ("You are a helpful assistant.") for every tier in v1. `call_openrouter` still takes `system` as a parameter so per-tier prompts need no signature change later.

**Call Log line.** One JSON object per line, keys: `timestamp` (ISO 8601, UTC, `Z`-suffixed), `task`, `tier`, `model`, `latency_ms` (integer, measured client-side with a monotonic clock around the Provider call), `cost`, `prompt_tokens`, `completion_tokens`, `ok` (bool), `error` (string or null). The task text is logged because the stated goal is to find out how often the Classifier is wrong, which is unanswerable from tier counts alone. Log path comes from `ROUTER_LOG_PATH`, defaulting to `./router_log.jsonl`; the file is opened in append mode and created on demand. `router_log.jsonl` is gitignored.

**REPL behaviour.** Reads from an injected input stream defaulting to `sys.stdin` and writes to an injected output stream defaulting to `sys.stdout`, so tests can drive it without a pty. Blank lines are skipped without any call. `exit` / `quit` and EOF (Ctrl-D) end the loop. Output per task is a routing line naming tier and model, then the answer. A `KeyboardInterrupt` during a call aborts that call, prints a notice, and returns to the prompt; a `KeyboardInterrupt` at the prompt ends the loop.

**Error handling.** Any exception from the Provider call is caught in the Router, printed by the REPL as a one-line error, and written to the Call Log with `ok: false` and the error text. The REPL keeps running. Errors never lose the log entry.

**Not built.** No escalation cascade, no `looks_unreliable` check, no `next_tier` field on tiers, no LLM classifier, no second Provider, no session history, no tool calling. The root-level `reference_model_router.py` and `reference_agent_loop.py` sketches contain several of these; they are reading material and are neither imported nor extended.

## Testing Decisions

**What a good test looks like here.** A good test drives the system at its outermost useful entry point and asserts what a user or an external system could observe: the text printed to the REPL's output stream, the bytes of the HTTP request that left the process, and the lines in the Call Log file. It does not assert that Router called Classifier, does not mock internal functions, and does not assert on internal data structures that no consumer sees.

**Seam — one, at the HTTP boundary.** Tests replace `urlopen` in the Provider call module with a fake that (a) captures the outgoing `Request` and (b) returns a canned OpenRouter JSON response. That is the only fake in the suite. Everything above it — Classifier, Tier Config, Router, Call Log, REPL — runs for real. This is the highest available seam: it lets a single test assert "this task text produced a request carrying `TIER_COMPLEX_MODEL`'s value" end to end, which is the feature's actual claim. Injecting a fake `call_openrouter` instead was rejected because it would stop verifying that the chosen model ID reaches the wire.

Everything else is parameterization rather than mocking: environment variables are set with `monkeypatch.setenv`, the log path points at `tmp_path`, and the REPL is handed `StringIO` streams.

**Coverage.**

- *Classifier*: direct unit tests of the rule table — short task, >40-word task, >200-word task, each complex signal, case-insensitivity, empty/whitespace input.
- *Tier Config*: startup validation fails with a message naming every missing variable; succeeds when all are present.
- *Router + Provider call + Tier Config, through the seam*: each of the three tiers routes a representative task to the model ID from the corresponding environment variable; the request carries the bearer token, the model, and the task as a user message; the answer is returned from the response.
- *Call Log*: after a successful call the written file's last line parses as JSON and carries every expected key with the expected tier/model/task and a numeric `latency_ms`; after a failed call it carries `ok: false` and an error string; two calls append two lines rather than truncating.
- *REPL*: a scripted input stream of several lines produces one routing line plus one answer per task in the output; blank lines produce no request; `exit` and EOF terminate; a Provider error prints an error line and the loop continues to the next task.

**Prior art.** None — this is the first code in the repository. This spec's seam choice is therefore the prior art for the next feature: fake at the process boundary, run everything inside for real.

## Out of Scope

Everything listed under "Out of scope" in the brief, restated for the implementer: no escalation cascade, no tool/function calling and no cross-provider `tool_use` normalization, no Provider other than OpenRouter (no direct Anthropic adapter, no LiteLLM), no multi-turn conversation history, no UI beyond the terminal REPL, no dependency on or copying from `NousResearch/hermes-agent`, no messaging-platform integration and no skills self-improvement loop.

Additionally out of scope for this spec: no cost budget or spend cap, no rate limiting or retry-with-backoff, no streaming of model output, no analysis or reporting command over the Call Log (the log is read with ordinary shell tools for now), no log rotation, no packaging or distribution beyond running from the repo, and no `.env` file loading (environment variables are exported by the user).

## Further Notes

The three tier model IDs ship unset on purpose. Two attempts during discovery to establish current OpenRouter model IDs returned contradictory and implausible results and were discarded as unreliable rather than guessed at; the user fills in real IDs from their own OpenRouter dashboard. The README carries placeholder export lines, and startup validation turns "I forgot to set them" into a clear message instead of a confusing Provider error.

The same caution applies to OpenRouter's cost reporting: the code reads cost and token usage defensively and records `null` when a field is absent, so the tool works correctly whether or not cost arrives on the completion response.

**Resolved during ticket 02.** OpenRouter's "Usage Accounting" docs (openrouter.ai/docs/use-cases/usage-accounting, checked 2026-09-21) confirm no request-side opt-in is needed: usage details (`prompt_tokens`, `completion_tokens`, `cost`, plus nested detail objects) are included automatically in every non-streaming response's `usage` object with no additional parameters. The `usage: { include: true }` and `stream_options: { include_usage: true }` flags are explicitly documented as deprecated and now have no effect. This was confirmed against OpenRouter's published documentation, not a live API call (no key was available in this environment); the defensive null-safe parsing already in `provider.py` stays as the safety net in case a given upstream model or account tier omits fields.

This feature deliberately ships a Classifier that is expected to be wrong sometimes. The Call Log is the deliverable that matters most — it is what turns "should we build an escalation cascade / an LLM classifier?" from an argument into a query.
