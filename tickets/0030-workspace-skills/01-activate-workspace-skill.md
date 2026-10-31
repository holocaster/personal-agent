# 01: Activate a bounded workspace skill for routed turns

**What to build:** Let a user list workspace-local Agent Skills, activate one
explicitly for later routed turns, replace it or turn it off, without allowing
skill files or instructions to expand workspace access or Tool permissions.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0030-workspace-skills.md` (R1–R7, Testing Decisions);
**ADRs:** ADR-0004 (Input Box), ADR-0005 (Resume/Call Log).

- [x] Add local `/skills`, `/skill <name>` and `/skill off` REPL Commands for
      interactive and piped input; include them in `/help` and interactive
      command completion. List valid direct-child skill names/descriptions in
      sorted order with one active marker or a none marker. Missing skill base
      lists none; skipped invalid entries produce visible diagnostics; reserve
      `off` for deactivation. Commands make no Provider Attempt. (R1, R4)
- [x] Read only `.agents/skills/<name>/SKILL.md` relative to the configured
      Workspace Root. Validate containment of the skills base, child and file
      before enumeration/read, including symlink escapes. Cap each file at
      16 KiB total; reject oversize, unreadable, missing, binary, non-UTF-8,
      invalid YAML or invalid metadata without loading instructions. Parse
      standard YAML frontmatter safely: name matches parent and Agent Skills
      naming rule, description is a non-empty string of at most 1024
      characters, Markdown instruction body is non-empty; accept folded and
      quoted scalar descriptions. Ignore optional capability metadata (e.g.
      `allowed-tools`). Declare the YAML parser dependency. (R2, R3, R7)
- [x] Activate one immutable snapshot only after successful validation;
      replacing and turning off affect later turns only. Failed activation or
      reload, including malformed command arguments, preserves the previous
      skill and reports a visible error. Keep it active through `/clear`,
      `/undo`, `/retry`, `/compress` and `/mode`, but reset to none on every new
      Run including Resume; do not write or replay activation via Call Log or
      change Conversation persistence. (R4, R5)
- [x] Pass the active snapshot from Terminal to Router for the whole routed
      turn. Include its name and bounded instructions in each routed System
      Prompt, including retries, Escalation and Tool follow-ups; current state
      applies to later `/retry` and Continuation Turns. Mark skill text as
      lower-priority workspace content and state it cannot override Agent Mode,
      Tool Registry, Tool Confirmation or Workspace Root. Do not put it in the
      Compression request; do not add or reconfigure Tools. (R6, R7)
- [x] Verify at the `run_repl` + fake Provider seam using temporary workspace
      trees: listing, activation/replacement/off, Attempt counts, prompt
      propagation and removal, snapshot reactivation, `/retry`, Resume,
      `/compress`, retries/Escalation, a Continuation Turn, piped/help/completion;
      invalid/missing/oversize/inaccessible files and escapes at each path
      component preserve an existing skill. Demonstrate a hostile skill cannot
      enable a forbidden Tool in `plan` or skip Tool Confirmation in `build`.
      Keep existing tests passing. (R1–R7)
