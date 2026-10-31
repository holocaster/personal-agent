# 0049: Project instructions with recursive file references

## Goal

Automatically supply repository conventions and build/test guidance to ordinary agent tasks. The user explicitly requires arbitrary referenced filenames: a `CLAUDE.md` containing only `[@Narquia.md]` must load that file, including recursively referenced files.

## Scope and intended decisions

- Automatically select Workspace Root `AGENTS.md`, falling back to `CLAUDE.md` only when AGENTS.md is absent. No root file is valid and preserves current behavior. If AGENTS.md exists but is invalid, do not silently use CLAUDE.md.
- Expand bare `@file`, bracketed `[@file]`, and quoted paths for filenames with spaces. References may name any regular UTF-8 text file, not just CLAUDE.md or Markdown. Resolve each reference relative to its containing file; nested relative paths and parent paths that remain inside the workspace are useful. Do not evaluate shell/environment/tilde expansions or fetch URLs.
- Keep expansion inside the Workspace Root, retaining existing `.env`/`.pem`/`.key` and symlink-escape exclusions. Reject directories, binary/non-UTF-8 files, missing/inaccessible references and cyclic imports visibly. Use bounded reads and finite graph depth/size to prevent unbounded import expansion. Imports inside fenced/inline code and email addresses are literal content, not references. Document exact supported reference syntax rather than implement a Markdown engine.
- Deterministic depth-first inclusion in source order; completed repeated imports appear once while genuine active-chain cycles are errors. Preserve source provenance without printing file contents.
- Reload before each ordinary task and explicit Retry. Keep one immutable snapshot across that execution's transient retries, Tools, mode switches and automatic compression. Resume reloads current workspace instructions; no continuation-schema change is needed. Show loaded source paths, with terminal control characters sanitized.
- Invalid startup references prevent startup/model calls. A later reload failure stops that execution before evaluator/ordinary dispatch, reports the source/reference clearly, and allows the user to repair files and retry. Preserve existing task/retry attribution and persistence behavior.
- Repository instructions are lower priority than explicit user requests and the application's Agent Mode, Tool Registry, confirmations and workspace boundaries. They cannot authorize tools or alter any execution gate.
- Include the full expanded instructions in every ordinary prepared input and all protective/candidate context-budget calculations. They are protected content, never compressed away or silently truncated. Evaluator and manual/preventive summary calls omit them, like active Skills; ordinary exchanges after compression still include them.
- Keep the change small: stdlib, no new dependency, no plugin registry or extra configuration system. Preserve existing direct Router/REPL callers without implicitly loading files from stale global test workspace state.

## Discovery

The user confirmed stopping startup on invalid references and reloading before every task. Implementation remained uncommitted during review; the user authorized commit and push on 2026-10-06.

Read-only exploration found the smallest seam: `main` passes its configured Workspace Root explicitly into `run_repl`; execution passes loaded text through `route`, `_run_tool_loop`, `_run_exchange`, and the three ordinary `_build_system_prompt` calls (initial, protected baseline, compression candidate). `evaluate_tier`, `compress`, and version-1 continuation schemas can stay unchanged.

## Out of scope

Automatic discovery of nested instruction files, files outside the workspace, instruction editing UI, autonomous memory, streaming, plugins, and persistence of historical instruction snapshots.

## Sequence

Implement only after feature 0048's traversal fix passes independent review. Planning may proceed independently; execution must remain sequential.
