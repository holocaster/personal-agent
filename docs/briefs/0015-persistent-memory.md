# 0015 - Persistent Memory

## Goal

Give the user a way to record short facts, preferences, and decisions that
persist across every Session — not just the current one — and have that
content injected into every future Run's System Prompt, without the cost or
risk of LLM-curated memory.

## Background

Loosely (and unverifiably) inspired by the kind of persistent, self-curated
memory a project like `NousResearch/hermes-agent` advertises: agent-curated
memory, autonomous skill creation, skills that self-improve, cross-session
semantic search. None of that is cloned, installed, or trusted as fact — same
posture as the existing hermes-agent relationship decision in
`docs/CONTEXT.md`. This feature is a deliberately small slice of that idea,
scoped down in discovery (see Out of scope).

## Scope

- **Memory Note**: one short fact the user records with `/remember <text>`,
  stored with an ISO timestamp.
- **Memory**: the ordered set of all Memory Notes for this installation.
  Global — one file per user/installation, independent of Session or
  Workspace Root.
- Storage: JSONL file, one `{"text": ..., "added": ...}` object per line, at
  `ROUTER_MEMORY_PATH`, defaulting to a **fixed** path
  (`~/.personal_agent/memory.jsonl`) — not relative to cwd or Workspace Root,
  so it stays the same regardless of which directory the agent runs from.
- `/memory` — REPL Command that lists current Memory Notes with a positional
  index (1, 2, 3...).
- `/forget <index>` — REPL Command that removes the Memory Note at that
  index (as last shown by `/memory`).
- Injection: Memory is added to the System Prompt on every Run, ahead of the
  Conversation Summary, whenever at least one Memory Note exists.
- Growth: unbounded. `/remember` prints a one-time REPL warning (not logged,
  not repeated on later Runs) when total Memory content passes roughly 2000
  characters. Nothing is capped or truncated automatically.
- Memory Notes and their removal are never written to the Call Log — the
  JSONL file is Memory's only record.

## Out of scope

- **LLM-curated memory** — no model call decides what's worth remembering or
  summarizes notes. `/remember` is the only write path, always explicit.
- **A Tool for the model to write Memory** — rejected in discovery
  specifically to avoid ungoverned writes and extra Attempt cost. A future
  feature could revisit this, but only as its own explicit decision.
- **Autonomous skill creation / self-improving skills** — no equivalent of
  Hermes's skill loop. Memory stores facts, not behavior.
- **Per-Workspace-Root memory** — considered and rejected; Memory is global
  by design (it's about the user, not the project).
- **Entry count / size caps, automatic truncation** — deferred; revisit only
  if the 2000-char warning proves insufficient in practice.
- **Any Status Footer or `/history` surfacing of Memory** beyond `/memory`
  itself — not requested, not needed for the goal.

## Settled decisions (from discovery)

1. Global scope, not per-Workspace-Root.
2. Entry mechanism: `/remember` only, no model-driven Tool.
3. Removal: `/forget <index>`, positional index from `/memory` (re-list
   after removing more than one).
4. Storage: JSONL at `ROUTER_MEMORY_PATH`, default
   `~/.personal_agent/memory.jsonl`, matching the Call Log's own JSONL
   convention and `ROUTER_LOG_PATH` naming pattern — but with a **fixed**
   default path (unlike `ROUTER_LOG_PATH`'s cwd-relative default), since a
   cwd-relative default would silently break the "global" requirement.
5. No entry/size cap; single warning on `/remember` past ~2000 chars.
6. Injected into System Prompt ahead of Conversation Summary, on every Run.
7. No Call Log entries for Memory operations.
8. New glossary terms **Memory Note** and **Memory** added to
   `docs/CONTEXT.md`, cross-linked against Conversation Summary and Call Log
   entry to prevent conflation.

## Open questions

None — discovery reached an empty frontier and the user confirmed shared
understanding before this brief was written.
