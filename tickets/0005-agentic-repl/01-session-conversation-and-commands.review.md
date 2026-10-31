# Review: ticket 0005-agentic-repl/01

status: approved
reviewed_range: 3094a95df56f640543ac496ca772aa78e58690a1..5018a494d6463d744ac4d5aab4ee6875772b852e

## Standards axis

No repo linter/formatter config exists. Added lines respect the de-facto
~110 char width. CLAUDE.md's "no comments unless necessary" respected —
only added comment is a justified one-line docstring on `_handle_command`.
Layering unchanged. No new dependency (ADR-0002 holds); no content-based
escalation added (ADR-0001 holds). No hard violations.

## Spec axis

R01-R06 and the R16 portion owned by this ticket are implemented and
covered. No scope creep. `route()` cannot return `ok=True` with
`messages=None`, so the REPL can never append `None` to `turns`.

## Test/evidence verification

The reported suite failures are environmental and pre-existing (see
out-of-scope finding below); the implementer's stated root cause
(`model_router/dotenv.py`) was wrong. Proven root cause: `litellm`
auto-loads the repo-root `.env` on import, mid-suite, injecting real
`TIER_*_PROVIDER`/API key values into `os.environ`.

- base `3094a95` clean worktree: 5 failed, 137 passed.
- head `5018a49` clean worktree: 6 failed, 154 passed (the one extra
  failure is this ticket's new `/models` test, same ambient-env cause).
- head with the repo `.env` keys neutralised: 160 passed, 0 failed.

The ticket's "full existing offline suite passes" claim holds on a clean
environment; it does not hold on this developer machine, for a cause that
predates the ticket.

## Extension point for ticket 02

`RouteResult.messages: tuple[dict, ...] | None` is variable-length, so
ticket 02 can return the full Tool turn without changing ownership or the
REPL's append site. Only `repl._render_history` hard-unpacks a 2-tuple —
not a defect, since ticket 02 must rewrite that renderer anyway (R02
requires distinguishable Tool request/result entries).

## Findings

- suggestion — `model_router/router.py:26` (`RouteResult.messages`):
  Mysterious Name — reads as the messages sent to the Provider but holds
  only the completed turn. Rename to `turn`, or leave as-is if ticket 02
  will widen it to hold the whole Tool turn.
- suggestion — `model_router/repl.py:32,79,107`: `turns` annotation
  (`list[tuple[dict, dict]]`) is narrower than the router's contract
  (`tuple[dict, ...]`); `_render_history` hard-unpacks exactly two
  messages. No effect in this ticket; ticket 02 must touch the renderer
  anyway.
- suggestion — `tests/test_repl.py`: cross-provider history test only
  parametrises OpenRouter/Anthropic, not all four. Low risk — Gemini's
  assistant->model translation is covered at the provider layer
  (`tests/test_provider.py:92-93`); OpenAI shares OpenRouter's shape.
- suggestion — `tests/test_repl.py` command tests: spec's Testing
  Decisions bullet 1 asks for zero Provider calls AND zero log entries
  for every command; only `/help` and `/clear` assert on the log file
  directly (others assert `len(calls) == 0`, which already implies it).
- **important, out of scope** — `model_router/cost.py` -> `litellm`
  import: on any machine with a populated repo-root `.env`, importing
  `litellm` inside `cost.estimate()` loads that `.env` into `os.environ`
  mid-test-run, turning the offline suite red and echoing real API keys
  into pytest assertion diffs. Root cause confirmed via an
  `os.environ.__setitem__` tracer:
  `model_router/cost.py:5` -> `litellm/__init__.py:30`
  `_dotenv.load_dotenv(override=...)` -> `dotenv/main.py:108`
  `os.environ[k] = v`. Predates this ticket; does not gate it. Needs its
  own fix (e.g. an autouse conftest fixture clearing `TIER_*`/`*_API_KEY`
  before each test, or `tier_env` setting `TIER_*_PROVIDER` explicitly).

## Residual risks

- Offline suite is red on this developer machine until the `litellm`/`.env`
  issue above is fixed; `uv run pytest` locally shows 6 failures and can
  echo real API keys into assertion output.
- Tool-turn rendering and the variable-length turn shape are unproven here
  by construction; ticket 02 must widen `repl._render_history`.
