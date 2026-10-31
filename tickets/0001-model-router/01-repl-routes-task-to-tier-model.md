# 01: REPL routes a task to its tier's model and prints the answer

**What to build:** the whole path, thin. The user exports their OpenRouter key and three tier model IDs, starts the tool, types a task, and sees the Complexity Tier that was chosen, the model ID that tier maps to, and the model's answer. Each typed line is one independent task. This is the tracer bullet: Classifier, Tier Config, Provider call, Router and REPL all exist for real after this ticket — only the Call Log and the failure handling are deferred.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0001-model-router.md` — Solution; Implementation Decisions (Language and dependencies, Modules, Complexity Tier representation, Classifier rules, Tier Config contract, Provider call contract, System prompt, REPL behaviour); Testing Decisions (Seam, Coverage for Classifier and for Router + Provider call + Tier Config, and for REPL). **ADRs:** none.

Glossary terms are defined in `docs/CONTEXT.md`. The root-level `reference_model_router.py` / `reference_agent_loop.py` sketches are reading material only — do not import, copy wholesale, or carry over their escalation/adapter machinery.

- [x] Repository has a runnable Python 3.12 package with no third-party runtime dependency; `pytest` is the only dev dependency, and a `.gitignore` covers the usual Python noise.
- [x] Complexity Tier is a three-valued enum whose values are the strings `easy`, `medium`, `complex`.
- [x] Classifier is a pure function of the task text with no I/O and no model call, applying, in order: complex if the lowercased task contains any complex signal (`refactor`, `architecture`, `prove`, `debug`, `design a system`) or exceeds 200 words; medium if it exceeds 40 words; easy otherwise. The signal list is a module-level constant.
- [x] Tier Config reads `TIER_EASY_MODEL`, `TIER_MEDIUM_MODEL`, `TIER_COMPLEX_MODEL` and `OPENROUTER_API_KEY` from the environment and exposes the tier-to-model lookup. No model ID appears as a literal anywhere in the code.
- [x] Provider call is one plain function `call_openrouter(model, system, messages)` using `urllib.request` against OpenRouter's chat completions endpoint, with a bearer token header and a 60-second timeout. It returns the answer text from the first choice plus whatever usage/cost the response carried, reading each usage field defensively (absent means `None`, never an exception). No Protocol, no adapter class, no adapter registry.
- [x] Router ties it together: classify the task, look the tier up in Tier Config, call that model with the fixed system prompt `You are a helpful assistant.`, return tier, model and answer.
- [x] REPL loops over an input stream (default `sys.stdin`) writing to an output stream (default `sys.stdout`), both injectable; prints a routing line naming tier and model followed by the answer; skips blank lines without making any call; exits on `exit`, `quit`, or EOF. No conversation history is kept between lines.
- [x] Unit tests cover the Classifier rule table directly: a short task, a >40-word task, a >200-word task, each complex signal, mixed case, and empty/whitespace input.
- [x] Routing tests run everything for real and fake only `urlopen` in the Provider call module, capturing the outgoing request and returning a canned OpenRouter response. They assert that a representative task for each of the three tiers produces a request whose body carries the model ID from the matching environment variable, that the bearer token and the task text are in the request, and that the answer from the response is returned.
- [x] A REPL test drives a scripted multi-line input stream through `StringIO` and asserts one routing line plus one answer per task in the output, that a blank line produces no request, and that `exit` and EOF end the loop.
- [x] README documents running the tool and shows the exact export lines for all four environment variables, with placeholder model IDs the user replaces from their own OpenRouter dashboard, stating plainly that these are placeholders and not real model IDs.
