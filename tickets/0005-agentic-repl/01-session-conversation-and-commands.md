# 01: Session Conversation, Context Window, and local commands

**What to build:** A usable REPL in which a user can ask contextual follow-ups, inspect or clear all completed turns, view configured models, and use local commands without a Provider call. This lands a complete text-only session experience across all four existing Providers before adding Tool execution.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0005-agentic-repl.md`, Session interface (R01–R03), Conversation and Context Window (R04–R06), documentation/constraints (R16), Testing Decisions. **ADRs:** ADR-0001 and ADR-0002.

- [x] Interactive input displays and flushes `user> `; iterable/piped input remains supported. A successful request displays one separate compact line with effective Complexity Tier, Provider, and model, followed by the answer prefixed with `llm> `. Tests verify the exact labels and keep metadata out of answer text.
- [x] `/help`, `/clear`, `/history`, `/models`, and `/exit` behave as R02 specifies. Unknown slash commands and arguments to these commands produce a local error. Commands/blank input never classify, call a Provider, append an Attempt, or become Conversation messages. `/models` displays loaded mappings only and no secrets.
- [x] Bare `exit`/`quit`, EOF, idle Ctrl-C, interrupted requests/retry waits, and readable routed errors preserve R03 and existing terminal behavior.
- [x] One Conversation is owned by each `run_repl` invocation. Each successful user/assistant exchange is appended as one complete turn; failures/interruptions discard only the pending turn. No new persistent transcript is written.
- [x] New requests send exactly the latest 20 completed prior turns, in order, plus the current user request, with system instructions kept separate. `/history` still displays every completed turn. Tests exercise the 20/21 boundary and an empty Conversation.
- [x] The Router classifies only the current task once and forwards context across all four Provider wire formats, including a subsequent request selecting another Provider/model. Existing standalone route callers remain valid.
- [x] `/clear` empties context and `/history` but retains configuration, existing Call Log entries, and Budget Guardrail spending. Prove this after one charged request.
- [x] Extend the existing HTTP fake only as needed to inspect complete conversation payloads. Entry-point tests prove output, full-window requests, error rollback, and zero calls/log entries for local commands.
- [x] Concise README usage reflects the session and commands (R16 portion shipped here); the full existing offline suite passes with intentional transcript expectations updated.

**Implementation guidance:** Own the REPL's completed-turn collection and keep a request's pending messages separate. Extend the Router result with the completed messages needed by the REPL so ticket 02 can add intermediate messages without changing ownership. Do not build a persistence abstraction or implement Tool APIs in this slice.

**Validation:** `uv run pytest` plus inspection of captured HTTP payloads in the session tests. Use no real API keys or paid calls.
