# 0049: Project instructions with recursive file references

## Problem Statement

Ordinary tasks do not automatically receive the Workspace Root's conventions or build/test guidance. Those instructions may themselves refer to other files: a `CLAUDE.md` containing only `[@Narquia.md]` must work, including further references inside `Narquia.md`. Requiring a specific imported basename or extension would lose the user's actual instructions.

## Solution

Select root `AGENTS.md`, or root `CLAUDE.md` when `AGENTS.md` is absent, and recursively expand supported file references. Include the full result as protected, lower-priority instructions for ordinary tasks. Show source paths, reload before each task and explicit Retry, and stop visibly on invalid imports before any evaluation or ordinary Provider dispatch.

## User Stories

1. As a user, I want root AGENTS.md loaded automatically so that repository conventions accompany my tasks.
2. As a user, I want CLAUDE.md used when AGENTS.md is absent so that existing projects work.
3. As a user, I want a workspace without either file to keep working so that instructions remain optional.
4. As a user, I want `[@Narquia.md]` expanded so that my existing reference syntax works.
5. As a user, I want arbitrary UTF-8 text filenames and extensions accepted so that references match my project layout.
6. As a user, I want quoted filenames with spaces and recursive relative references so that related guidance can live in subdirectories.
7. As a user, I want email addresses and code examples preserved literally so that documentation does not trigger unintended reads.
8. As a user, I want ordered expansion and source provenance so that I can tell which guidance was loaded.
9. As a user, I want cycles, inaccessible files and unsafe paths rejected clearly so that broken guidance cannot silently disappear.
10. As a user, I want instructions refreshed between tasks and Retry so that repairing or changing files takes effect immediately.
11. As a user, I want a task to retain its initial instructions across Tool exchanges and transient Attempts so that mid-task file edits cannot change its guidance.
12. As a user, I want complete instructions to survive Compression and count toward Context Budget so that context pressure cannot silently remove project rules.
13. As a user, I want explicit requests and application execution gates to retain priority so that repository text cannot authorize Tools or change Agent Mode.
14. As a user resuming a Session, I want current workspace instructions with my existing pending task so that Retry preserves attribution without replaying completed Tools.

## Implementation Decisions

### R1 — Root selection and explicit loader seam

- Add one cohesive stdlib loader at the package root, `project_instructions`, with an explicit Workspace Root input and an immutable result containing expanded instruction text and ordered source paths. A dedicated load error identifies the containing source, offending reference when applicable, and reason. Parsing, confinement, bounded reads and graph traversal belong behind this function.
- Select only root `AGENTS.md`, falling back to root `CLAUDE.md` only when AGENTS.md is absent. An existing directory, broken symlink, inaccessible file or invalid AGENTS.md is an error, never a reason to fall back. Neither file produces empty text and no sources; an empty valid file is allowed.
- CLI `main` passes its resolved configured Workspace Root explicitly to `run_repl`. REPL callers that omit this optional argument retain existing behavior and do not consult process-global Workspace Tool configuration for instructions. `route` accepts optional already-loaded instruction text, defaulting to empty, and performs no filesystem discovery.

### R2 — Reference syntax

- Recognize bare `@path`, bracketed `[@path]`, and quoted `@"path with spaces"`, `@'path with spaces'`, `[@"path with spaces"]`, `[@'path with spaces']`. `[@Narquia.md]` alone in a root file is a valid complete instructions file. Imported regular text files may be extensionless, non-Markdown, or use arbitrary UTF-8 names.
- Outside code, a bare or quoted reference starts at the beginning of the text or immediately after whitespace or `(`. Bracketed forms start with `[@` at the same boundary. This excludes embedded email addresses, including `person@example.com`, and URI fragments containing an embedded `@`.
- Unquoted paths end at whitespace, parentheses, square brackets, quote characters or backticks. Other punctuation is part of the filename; use quoting to disambiguate a filename from sentence punctuation or to include those delimiters. Quotes enclose the exact path; escaping the enclosing quote or a backslash with a backslash is supported, and other backslashes remain literal. Bracketed forms require their closing `]` directly after the path or closing quote. A recognized quoted/bracketed form with an empty path or missing closing delimiter is a visible syntax error. An isolated `@` is literal text.
- References inside fenced code and inline backtick code remain unchanged. Supported fences start with up to three leading spaces and at least three backticks or tildes; a matching-character closing fence has at least the opening run length and only trailing whitespace. An unclosed fence protects the rest of that file. Inline code uses equal-length backtick delimiters; unmatched backticks remain literal. No full Markdown engine, Markdown link interpretation or glob expansion is added.

### R3 — File boundaries and bounded reads

- Resolve references relative to their containing source file's resolved parent directory, not the process directory or workspace root. `.` and `..` are permitted only when the resulting path remains within Workspace Root. Absolute references and URI references are rejected. Shell commands, environment variables and tildes are never expanded; they are literal filename characters rather than authorization to evaluate or fetch anything.
- Require every selected root/import to resolve inside Workspace Root to a regular file. Reject missing/inaccessible files, directories, special files, external symlink targets, `.env`, `*.pem`, and `*.key`; apply exclusions to both the named path and its resolved target. Internal file symlinks may work under these checks. No Workspace Tool path rules are relaxed: instruction imports have their own source-relative confinement because Tools reject `..` lexically.
- Use bounded binary reads, strict UTF-8 decoding and NUL rejection. Fixed limits are 64 KiB per source file, 256 KiB of distinct source bytes per load, 64 distinct sources and an active chain of at most 16 files including the root. Bound the final expanded UTF-8 text, including provenance, to 512 KiB. Oversize/over-depth graphs fail completely, without partial results, truncation, new environment variables or configuration settings.

### R4 — Expansion and provenance

- Expand depth-first at each reference position, in source order, preserving surrounding source text and literal code/email content. Every included contribution remains attributable to its workspace-relative source path in the expanded text.
- Track canonical resolved paths separately for the active chain and completed imports. A reference to an active source is a cycle error with its chain; a completed source contributes its text only once, including when referenced through a different relative path or symlink alias.
- The immutable source list records first encounter order, root first, without duplicates. Terminal output reports loaded workspace-relative paths and errors using existing control-character sanitization; it never prints instruction bodies. Source provenance is part of the ordinary model-facing instructions, rather than a new historical snapshot store.

### R5 — Startup, reload and snapshot lifetime

- Validate and display the graph at startup, including Resume, before starting/resuming REPL Session activity or making any Provider call. Invalid startup graphs exit with a clear error and zero evaluator/ordinary/summary calls.
- Reload before every newly accepted ordinary task and each explicit Retry, before its due evaluation or ordinary dispatch. Use a single immutable text snapshot throughout that execution, including transient Attempts, all Tool follow-ups, mode changes, automatic Compression and Context Overflow Recovery. A mid-execution instruction edit affects only a later task or explicit Retry.
- Re-run root selection during each load so additions/removals or AGENTS.md/CLAUDE.md precedence changes take effect. Local-only commands and manual Compression do not trigger task reloads.

### R6 — Repairable failure and existing persistence

- A reload error stops only that execution before evaluator or ordinary Provider calls. Report the source/reference and reason, keep the REPL usable, and show repair plus `/retry` guidance. Never continue using a stale successful snapshot.
- Preserve normal accepted-submission counting/input and Retry attribution from ADR-0007: a newly accepted task remains the submitted task even when loading fails; Retry reuses its ordinal and does not append evaluator text. An unperformed due evaluation remains due. The locally stopped task must be retryable immediately and after Resume through existing pending-turn persistence.
- Preserve an existing continuation's completed prefix, replay, Todo state and fetched-content attribution on reload failure. Retain current routing/configuration/mode and existing fatal persistence behavior. Use the current version-1 continuation and existing Call Log contracts, with no new field for instruction text or snapshots.

### R7 — Priority and ordinary prompt integration

- Carry loaded text from REPL into `route`, then the Tool loop and exchange preparation. Include it in every ordinary System Prompt with an explicit lower-priority label: explicit user requests, Agent Mode, Tool Registry, Tool Confirmation and Workspace Root boundaries take precedence.
- The instructions cannot register Tools, enable capabilities, change confirmation decisions or bypass validation. Existing application enforcement remains at its current Tool/execution boundaries; this feature supplies guidance only.
- Preserve Memory, Skills, Conversation Summary, Todo and Provider replay behavior. Loading instructions adds no independent model call or dependency.

### R8 — Context Budget and auxiliary-call isolation

- Include the exact same full instructions in ordinary Provider prepared input and estimates, the protected baseline used to reserve summary space, and the Compression candidate estimate. Count provenance and the priority wrapper too. Never omit, summarize or truncate project instructions to fit.
- After automatic Compression or Context Overflow Recovery, the next ordinary exchange still includes the snapshot. If the complete protected input cannot fit, the existing visible Context Budget failure applies before ordinary dispatch.
- Tier evaluation and both manual/preventive summary construction omit project instructions, as they omit active Skills. Their own budget estimates also omit them. Evaluator instructions, summary requests and continuation schemas need no change.

### R9 — Small implementation and user documentation

- Use the existing explicit execution seams and leaf module organization; no dependency, plugin registry, general import framework or additional configuration system. No ADR is needed: this applies existing instruction-priority, persistence and Context Budget decisions.
- Add concise README guidance for root precedence, supported bare/bracketed/quoted forms, literal email/code content, recursive relative references, exclusions/fixed bounds, reload/Retry and error behavior. Do not print file content as a loading announcement or add unnecessary code comments.

## Testing Decisions

- Exercise loader behavior with temporary real filesystem trees through its public function, asserting independent expected text/order/provenance or diagnostic outcomes. Cover root absence/precedence, exactly `CLAUDE.md -> [@Narquia.md] -> @subdir/rules`, extensionless/non-Markdown/Unicode files, quoted spaces/delimiters, source-relative nested/parent paths, repeated imports/aliases and genuine cycles.
- Parameterize confined-file failures and bound cases: external parent/symlink, excluded named/resolved targets, directory/special file, missing/inaccessible file, invalid UTF-8/NUL, per-file/aggregate/expanded bytes, distinct-file count and chain depth. Demonstrate bounded reads rather than only checking file metadata. Check email addresses, inline backticks and both fence characters are literal, including references to missing files inside code.
- Test the highest existing integration seams, `main` and `run_repl`, with explicit temporary roots and fake Providers. Prove startup failure makes zero calls; later failure makes no evaluation/ordinary call, retains pending attribution and can succeed after repair via `/retry`, including Resume. Assert sanitized path-only output and no stale global-workspace loading for omitted arguments.
- Use existing fake Provider callbacks to change instruction files during a transient failure or Tool follow-up. Compare actual prepared ordinary requests: one execution keeps its old snapshot across Attempts/Tools/mode changes; a new task and explicit Retry use the changed snapshot. Check current root precedence on reload.
- Reuse existing preventive Compression and Context Overflow Recovery fixtures: actual ordinary requests before/after reduction retain full instructions; protected baseline and candidate preparation include them; protected overflow blocks visibly. Summary requests and evaluator requests exclude the instruction sentinel and their estimates do not gain its bytes/tokens.
- Preserve existing mode gates, Skills/Memory/Todo integration, Retry continuation and persistence failure tests. Prior art is `test_workspace_skills`, `test_main`, `test_session_tier`, `test_continuation`, `test_agent_mode`, `test_preventive_compression` and `test_context_recovery`. Avoid private-parser tests or algorithm-mirroring assertions. Run focused affected tests incrementally, then the existing full suite and repository-required checks.

## Out of Scope

Nested instruction-file discovery; files outside Workspace Root; instruction editing UI; autonomous memory; streaming; plugins; historical instruction snapshots; a full Markdown parser; new settings, dependencies, persistence schema or execution gates.

## Further Notes

Canonical brief: `docs/briefs/0049-project-instructions.md`. ADR-0007 governs accepted-submission and Retry attribution; ADR-0005 governs the Call Log as durable Conversation record. Feature 0048's traversal fix must pass independent review before implementation of this feature begins. Planning is independent. Implementation remained uncommitted during review; the user authorized commit and push on 2026-10-06. Preserve concurrent work.
