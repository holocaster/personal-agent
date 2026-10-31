# 0050: Project session discovery and explicit question answers

## Goal

Let Personal Agent find and inspect its own previous Sessions directly, scoped by project, and prevent invalid Question Tool option numbers from silently becoming free-text answers.

## Confirmed scope

- Organize new Call Logs and their Detailed Audit Payload companions in project folders derived from an absolute directory path.
- Add a read-only model-facing Tool for finding Sessions and searching their logs.
- Make custom Question Tool answers discoverable and distinguish them from invalid numeric selections.
- Remove `PA_LOG_PATH` and `PA_WORKSPACE` configuration, including their runtime handling, documented examples and environment-dependent tests.
- Legacy-log compatibility and migration are out of scope; this project is not in production. This does not request deletion of existing logs.
- Keep the implementation small and reuse existing Call Log and Tool Registry facilities.

## Evidence

- Session `20261006T201637Z-aph44u` starts with `can you retrieve our last session?`; the agent searches repository files and asks three clarification questions instead of locating its own Session.
- Each recorded question has four choices. Inputs `5`, `10`, and `5` are returned literally as free text. Replaying the first question through `terminal/repl.py:_make_question()` reproduces this behavior.
- `call_log.py` currently uses one shared configured base path, defaults to `~/.personal_agent/logs/pa_log.jsonl`, derives both log filenames from it, and selects Resume `last` by greatest Session Id.
- `main()` resolves Workspace Root from `PA_WORKSPACE` or the launch directory before Resume. Session start records currently omit project identity.

## Settled decisions

The user accepted all four first-round recommendations, then replaced the configurable workspace/log-path decisions with fixed defaults.

- Workspace Root and project identity are always the resolved absolute process working directory at startup. Remove `PA_WORKSPACE`; project instructions and workspace Tools use that same root. Capture this root for the Run rather than allowing later directory changes to redirect its logs.
- Logs always live under the user's `~/.personal_agent/logs` directory, partitioned by project. Remove `PA_LOG_PATH`; no alternate log destination is part of this feature.
- Project folders use a readable flattened absolute path plus a stable short hash, distinguishing paths that flatten to the same readable name. Record the original absolute Workspace Root in Session metadata.
- Append a local Other choice after the model-supplied choices. Selecting Other opens a custom-text prompt. Reject invalid option numbers and reprompt; ordinary direct text remains accepted. Numeric text in the custom prompt is literal. Questions without choices remain free-text prompts.
- Log discovery defaults to the current project, with explicit cross-project search available. Cross-project results identify the original project directory.
- For the Tool, last/previous means the Session whose latest Run was most recently started or resumed, excluding the current Session. Interrupted and incomplete Sessions remain discoverable.
- Search ordinary Call Logs by default. Detailed Audit Payload companions are available only when explicitly requested and recorded; their absence is reported rather than invented.
- Search uses case-insensitive literal text matching. Semantic search, embeddings, additional model calls and indexing databases are out of scope.
- Session reads default to a readable chronological recorded timeline of user requests, assistant responses, Tool results and errors, with timestamps and source references. Avoid duplicate Conversation snapshots. Include evidence from interrupted turns rather than restricting output to completed Conversation turns.
- `--resume last` follows current-project scope and latest-Run start/resume ordering. At startup there is no current Session to exclude. Resume continues the original Session and companion files.

## Intended implementation constraints

- One read-only model-facing Tool with list, read and search operations. Keep result provenance (project, Session Id and record position), bounded output and continuation pagination; reuse existing Tool Output Cap rather than introducing another configurable cap. Exact schema and default page sizes belong in the spec.
- Keep existing question/choice/answer bounds. Other is appended by the local interface, not included in model-supplied choice limits. Preserve the explicit `text: ` escape and treat custom-prompt text literally, including text resembling an option number.
- Search/read show incomplete or malformed evidence visibly, and never claim it is a complete successful Session. Resume retains its strict validation.
- Reading historical logs does not execute recorded Tools, restore Conversation or activate logged instructions. Historical content stays untrusted data; apply existing known-secret redaction and filesystem boundary protections.
- Tests must isolate their user-home log storage without restoring either removed production environment override.

## Execution state

Discovery complete: the user accepted the final timeline and Resume recommendations. No open product questions remain; the planner owns exact schema, bounds, hash encoding and ticket slicing.

The user authorized local commits and continuing SDD on 2026-10-06. Prior spinner and patch-description corrections were committed separately as `bd2cc2e` on `feature/0050-project-session-discovery`; the prior targeted validation passed 509 tests. Commit the finalized discovery artifacts before the planner handoff. No push is authorized.

Follow-up (user decision 2026-10-07): after ticket 03 is approved, run a separate maintainability cleanup of `session_logs.py` with no behavior change: top-level `COMPRESS_TASK` import without a cycle, public names instead of private cross-module ones (`_SESSION_ID_PATTERN`, `_current_session_id`, `_configured_workspace`), a shorter `execute()` with descriptive cursor keys, and the current-Session in-progress check also matching the current project_id.
