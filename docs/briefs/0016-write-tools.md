# 0016 — Write tools

## Goal

Give the agent two Mutating Tools — `write` and `edit` — so it can act on the Workspace Root, not just inspect it. This closes the largest gap identified against the reference project `opencode` (see `docs/research/done/2026-09-23-opencode-feature-comparison.md`), and deliberately reverses the prior "Tools are read-only" decision in `docs/CONTEXT.md`.

## Scope

- **`write(path, content)`**: creates a new file or overwrites an existing one with the full given content. Only inside a directory that already exists — no implicit parent-directory creation.
- **`edit(path, old_string, new_string, replace_all=False)`**: replaces the one exact occurrence of `old_string` with `new_string`. Errors on zero or on more than one match unless `replace_all=True`, in which case every occurrence is replaced.
- Both reuse the exact path validation already in `src/personal_agent/tools/workspace.py` (`_resolve_workspace_path`, `_is_excluded`): confined to `ROUTER_WORKSPACE`, relative paths only, no path traversal, no symlink escape, `.env`/`*.pem`/`*.key` excluded.
- New **Tool Confirmation**: before either Tool executes, the REPL shows the user a diff (or, for a `write` creating a new file, the full content) and requires explicit approval. This is the project's first Tool-execution gate — every other built-in, including the three Workspace Tools, runs without one.
- New `ROUTER_MAX_WRITE_BYTES` config (default 64KB, same order of magnitude as `ROUTER_MAX_READ_BYTES`), rejecting a write past the limit.
- Logging: the existing Tool execution Call Log entry (arguments + result) is the audit trail. No new entry type.

## Out of scope

- Fuzzy/similarity-based matching for `edit` (opencode's multi-strategy Levenshtein matcher) — exact-match-or-error is enough; adding tolerance for whitespace/indentation drift is real engineering surface this project doesn't need yet.
- Implicit parent-directory creation on `write` — opencode does this (`fs.writeWithDirs`); deliberately not replicated here to keep the change minimal.
- Automatic before-image / backup / versioning of overwritten content. Git is the revert mechanism when the workspace is a repo. A workspace without Git accepts that an overwrite via `write` is irreversible — this is a known, accepted gap, not an oversight.
- Everything already out of scope for Tools in general and unaffected by this feature: MCP, arbitrary shell/commands, environment-variable access, patches.

## Settled decisions

1. The "writing... remains out of scope" line in `docs/CONTEXT.md`'s "Tool boundary" decision is reversed, not kept alongside a new one. MCP, commands, and environment-variable access remain out of scope — this reversal is scoped to writing only.
2. Both `write` and `edit` ship together (not just one), because they cover different needs (new-file/full-rewrite vs. surgical change) and share all their path-validation plumbing.
3. Tool Confirmation is mandatory for both, and shows the diff/content, not a bare yes/no — verified against opencode's own `ctx.ask({permission: "edit", metadata: {diff}})` pattern before adopting it.
4. `edit` requires exact, unique match (or `replace_all`) — checked opencode's actual `edit.ts` (9-strategy fuzzy matcher with Levenshtein similarity) and explicitly chose not to replicate that complexity.
5. `write` never auto-creates parent directories — checked that opencode's `write.ts` does (`fs.writeWithDirs`) and explicitly chose not to replicate that either.
6. No new Call Log entry type or backup mechanism — the existing Tool execution entry plus Git (when present) is accepted as sufficient audit/revert story.

## Open questions

None — grilling frontier closed and confirmed by the user on 2026-09-24.
