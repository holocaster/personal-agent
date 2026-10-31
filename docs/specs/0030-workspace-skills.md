# 0030 — Workspace Skills

Brief: `docs/briefs/0030-workspace-skills.md`. Vocabulary and existing boundaries:
`docs/CONTEXT.md`; ADR-0004 (Input Box), ADR-0005 (Resume and Call Log).

## Problem Statement

A user cannot explicitly load reusable workspace instructions for routed tasks.
Copying instructions into each task is repetitive; adding a Tool or making the
instructions global would change a different boundary and lifetime.

## Solution

Discover valid `SKILL.md` files in the Workspace Root's
`.agents/skills/<name>/` directories. `/skills` lists their names and
descriptions and marks the one active in this Run. `/skill <name>` loads its
instructions for subsequent routed turns, replacing any prior active skill;
`/skill off` disables it. New Runs, including Resume, start with none active.
Loading a skill never grants Tool access or changes Agent Mode.

## User Stories

1. As a user, I want `/skills` to list workspace skill names and descriptions,
   so that I can choose explicitly.
2. As a user, I want `/skills` to show which skill is active or that none is,
   so that I can check my current Run's instructions.
3. As a user, I want `/skill <name>` to load one workspace skill, so that my
   later routed requests get its instructions without copying them.
4. As a user, I want activating another skill to replace the previous one,
   so that only my latest choice applies.
5. As a user, I want `/skill off` to remove the active skill, so that later
   requests no longer carry its instructions.
6. As a user, I want the active skill to survive `/clear`, `/undo`, `/retry`,
   `/compress`, and a change of Agent Mode within the Run, so that only a
   replacement, `/skill off`, or the end of the Run changes my choice.
7. As a user resuming a Session, I want no skill active by default, so that
   earlier instructions are not silently reactivated.
8. As a user, I want malformed, missing, oversized, or inaccessible skill
   files reported without changing the active skill, so that mistakes are safe.
9. As a user, I want links out of the Workspace Root rejected, so that a skill
   cannot read outside my workspace.
10. As a user in `plan`, I want skill instructions to leave the Tool boundary
    intact, so that a skill cannot enable Mutating Tools.
11. As a user in `build`, I want the existing Tool Confirmation behavior, so
    that a skill does not pre-approve a Tool or relax confirmation.
12. As a piped-input user, I want the same local commands and readable errors,
    so that no interactive terminal is required to use skills.

## Requirements

- **R1 — Discovery and listing.** `/skills` is a local REPL Command: no Provider
  Attempt. Inspect only direct child directories of
  `<Workspace Root>/.agents/skills/` for `SKILL.md`; do not search other roots,
  recurse, or load auxiliary files. List valid skill names and descriptions in
  deterministic name order and mark the active one (or say none). If the skill
  directory is absent, list none without error. Malformed/inaccessible entries
  are not offered; visibly report that they were skipped without reading their
  instructions into the model. Document `/skills` in `/help` and interactive
  command completion. `off` is reserved for deactivation, so a directory named
  `off` is skipped with a visible diagnostic rather than listed as activatable.
- **R2 — Format and validation.** Each accepted file is UTF-8 Markdown with
  YAML frontmatter delimited by `---` and a non-empty Markdown instruction
  body. Require string `name` and non-empty string `description`; validate
  `name` against the Agent Skills naming rule (1–64 ASCII lowercase letters,
  digits and single internal hyphens, not starting/ending in a hyphen), equal
  to its parent directory, and `description` length 1–1024 characters. Accept
  ordinary YAML scalar descriptions (including quoted or folded values).
  Ignore other metadata fields, including `allowed-tools` and
  `compatibility`: they confer no permission. A file that cannot be decoded or
  parsed/validated is invalid. See https://agentskills.io/specification for
  the standard fields; this feature does not load referenced resources.
- **R3 — Bounded, confined reads.** Limit each `SKILL.md` read to **16 KiB of
  UTF-8 bytes total**, including frontmatter. Reject oversized files rather
  than silently truncating instructions. Use the Run's configured Workspace
  Root, not the process cwd; reject the skills base directory, a skill
  directory, or a file whose resolved path leaves the Workspace Root,
  including symlink escapes. Do not enumerate an escaped base directory or
  read a file outside that boundary even during `/skills`; unreadable,
  missing, and unsafe paths yield visible errors on activation.
- **R4 — Activation and errors.** `/skill <name>` validates and snapshots one
  skill's instructions for subsequent routed turns; a successful activation
  replaces the old skill. `/skill off` disables it; turning it off when none is
  active is harmless. Missing name, extra arguments, invalid name, missing or
  invalid file, or unsafe path produces a visible local error and preserves
  the previous active skill. `/skill` and `/skills` never call a Provider.
  Support these commands in interactive and piped REPL modes and `/help` /
  interactive completion.
- **R5 — Run lifetime.** Start with no active skill on every Run, including a
  Resume. Do not persist activation in the Call Log or replay it as Session
  state; preserve the existing Conversation replay. `/clear`, `/undo`, `/retry`,
  `/compress`, and `/mode` do not deactivate it. Activation is a snapshot: disk
  edits after activation take effect only on the next successful
  `/skill <name>`; a failed reload leaves the prior snapshot active.
- **R6 — Routed prompt.** Include the current active skill's name and bounded
  Markdown instructions in the System Prompt for every exchange of each
  subsequent routed turn, including Tool follow-ups, local retries, Escalation,
  `/retry` and a Continuation Turn. Freeze the skill for the whole routed turn.
  Once disabled, later turns omit it. Skill text is lower-priority workspace
  content: state in the System Prompt that it cannot override the Agent Mode,
  Tool Registry, Tool Confirmation, or Workspace Root boundaries. Do not add
  skills to Compression's separate Tool-free summary request, or alter the
  Conversation/Call Log format to carry skill state.
- **R7 — No expanded capabilities.** Listing/activation do not register,
  advertise, or execute any Tool; skill metadata or Markdown is not a source
  of Tool permissions, confirmation decisions, mode switches, or paths for
  unrestricted reading. All existing execution-time Tool Registry gates and
  confirmation paths remain authoritative in both `plan` and `build`.

## Implementation Decisions

- Keep command state in the Terminal beside the Run-local Agent Mode. Pass the
  immutable active skill snapshot to the Router when routing a turn, rather
  than putting it in the Conversation or changing the Provider Contract.
- Add a small workspace-skill reader for discovery, validation, and bounded
  reads. Use the configured Workspace Root and its containment checks rather
  than inventing a second root. Validate the path before opening and reject
  unsafe symlinks; no recursive directory walker or support for references,
  scripts, assets, or installed global skills.
- Declare a YAML parser dependency for standard frontmatter (safe loading
  only); avoid a home-grown YAML subset that would reject valid folded
  descriptions. Read at most 16 KiB plus one byte per file before parsing.
- Append skill content as a separate labeled block in the existing System
  Prompt for routed exchanges, below existing app-owned mode and Tool
  instructions. Keep existing Memory, Conversation Summary, date, and Todo
  List behavior. Do not treat Markdown commands or frontmatter keys as app
  configuration. No new Tool Registry entries or persistence schema.
- Existing ADR-0004's Input Box and ADR-0005's Resume replay stand unchanged;
  no new ADR is warranted for the settled single-skill Run scope.

## Testing Decisions

- Test observable command replies and Provider requests, not private parser
  state or whether a model obeys hostile skill text. Highest seam: scripted
  `run_repl` with fake Provider transport and a temporary configured Workspace
  Root. Prior art: `tests/test_agent_mode.py`, `tests/test_repl.py`,
  `tests/test_workspace_tools.py`, and `tests/fakes.py`.
- Verify `/skills` discovery/active marker, local command Attempt count,
  activation/replacement/off, prompt content on initial and Tool-follow-up
  exchanges, a switch followed by `/retry`, and no active skill on Resume
  despite the Conversation being restored. Include piped input and `/help` /
  interactive command completion.
- At the same seam, exercise missing root, invalid YAML/metadata/name/body,
  inaccessible and oversized files, and directory/file symlinks escaping the
  Workspace Root. Failed activation preserves an existing active skill and
  never sends escaped/invalid instructions to a Provider.
- Use a skill that asks for forbidden Tools or confirmation bypass to show
  `plan` still refuses Mutating Tools before confirmation and `build` still
  confirms them. Check that skill contents remain bounded across retries,
  Escalation, `/compress`, and a Continuation Turn. Run the offline suite.

## Out of Scope

Automatic skill selection, global skills, multiple simultaneous active
skills, installing/downloading skills, executing scripts, following resource
references automatically, new Tools/MCP/plugins, persistence across Runs, and
changes to Agent Mode or Tool Confirmation. Future multi-skill, automatic
selection, and global user skills belong in separate backlog features.

## Further Notes

- The brief's explicit single-skill Run scope is authoritative. The Skill
  format reference clarifies frontmatter only; optional capability metadata
  is not an authorization surface in Personal Agent.
