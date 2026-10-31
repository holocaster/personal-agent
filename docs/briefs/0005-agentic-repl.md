# Agentic REPL

## Goal

Turn the line-oriented router CLI into a usable session REPL with conversation context, local commands, and safe model-requested tools.

## Scope

- Show an interactive prompt and compact routing metadata.
- Keep one in-memory Conversation per REPL process; `/clear` resets it and `/history` displays it.
- Handle `/help`, `/clear`, `/history`, `/models`, and `/exit` locally.
- Send the 20 latest complete Conversation turns on each user request.
- Support provider-normalized tool calls for all four Providers.
- Ship `calculator` and `current_time` as allow-listed tools.

## Out of scope

- Conversation persistence, resume, or cross-session memory.
- Shell, filesystem, network, or user-defined tools.
- Streaming output.
- Context compaction by token count, summaries, or pruning tool outputs. This is the planned next evolution once real sessions demonstrate the need.

## Settled decisions

- A Tool call and every result it produces stay in one complete turn when selecting the Context Window.
- A configured model that cannot use tools fails explicitly rather than silently ignoring tool definitions.
- The Router chooses a Complexity Tier for each new user request; tool-loop follow-up calls remain on that request's selected Provider and model.
