# 0056: Isolated subagents

## Goal

Let Personal Agent execute the named, isolated agents required by `sdd-main`: `sdd-planner`, `sdd-implementer`, and `sdd-reviewer`. Develop this capability through the SDD workflow in the current coding harness.

## Discovery status

The user confirmed this scope and authorized the complete SDD workflow on 2026-10-18. Proceed with specification, tickets, implementation, and independent review.

## Settled scope

1. Execute subagents natively through Personal Agent's existing Providers and Tool loop, with isolated context and process state. Do not invoke external coding-agent CLIs.
2. Execute one subagent at a time in the first version.
3. Discover named agents automatically from `.agents/agents`, `.claude/agents`, and `.codex/agents`, including workspace-local and user-global definitions. Preserve existing source files rather than copying their instructions.
4. Each child uses the immutable Provider/model configuration of the parent task and the existing credentials. No per-role model selection in this version.
5. Children inherit the parent's Agent Mode and confirmation requirements. Enforce each role's declared Tool restrictions; route confirmations through the parent terminal. Children return product questions in their handoff instead of talking directly to the user.
6. Valid workspace definitions take precedence over global definitions. Within each scope use `.agents/agents`, then `.claude/agents`, then `.codex/agents`. Select one complete definition per name; do not merge instructions or permissions from duplicate files or interpret natural-language TOML pointers as imports.
7. A definition without a Tool allowlist inherits only the Tools available to the parent. An explicit allowlist narrows that set. Metadata naming another model does not override the inherited Provider/model selection.
8. Each child has its own Session/Call Log linked to the parent. Include child spend in the parent's visible total without double-counting Attempts. Ctrl+C stops the child and its jobs; do not resume interrupted children automatically.
9. Required skills and their relative support files must be readable through bounded skill access, including global symlinked skills. Preserve ordinary Workspace Tools' path boundaries. Make the installed SDD dependency skills discoverable through symlinks to their existing sources; do not duplicate instruction files or add an installer product.
10. Each delegation starts with fresh Conversation state, the project rules, the selected role instructions, and the supplied task/references. Do not copy the parent conversation or activate its orchestrator skill in the child. Children cannot delegate further or contact the user directly.

## Confirmed facts

- Personal Agent can now load the installed `sdd-main` through a global directory symlink and accepts skill files up to 32 KiB. This prerequisite shipped in `b0a8e3f`.
- `routing/router.py:route` already runs the Provider/Tool loop and returns a structured result. Call Log, workspace, Tool Registry, and Background Jobs contain process-global state; calling the REPL recursively or running child tasks in threads would not isolate them.
- The installed SDD roles need fresh context and restricted Tools, share the workspace and Git, and do not need nested subagents. Implementers must remain sequential.
- The original `.claude/agents/sdd-*.md` files declare names, descriptions, Tool lists, and instructions. The installed `.codex/agents/sdd-*.toml` files contain instructions pointing to those Markdown files.
- Several required `sdd-*` skills are installed under `~/.codex/skills` but are not yet discoverable under `~/.agents/skills`. Skill support files also need a readable access path.

## Open questions for the planner

None from the product side. Implementation seams and ticket boundaries belong to the planner.

## Scope constraints

Keep the implementation general enough to execute the three named roles without hardcoding the SDD workflow. Do not substitute generic agents for missing named roles or simulate independent review inside the parent conversation.

Parallel children, nested delegation, per-role model selection, external coding-agent CLIs, automatic child recovery, and a new agent/skill installation system are out of scope.

## Known unrelated installation issue

The existing global `grill-workflow` Skill description exceeds 1024 characters and is skipped. It is unrelated to the SDD dependency set and remains unchanged.
