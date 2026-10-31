# 02: `edit` Mutating Tool behind Tool Confirmation

**What to build:** The model can call `edit(path, old_string, new_string,
replace_all=false)` to change an existing text file in the Workspace Root.
The one exact occurrence of `old_string` is replaced (every occurrence with
`replace_all`); zero matches, or several without `replace_all`, is an error
before the user is asked anything. The change goes through the Tool
Confirmation built in ticket 01, previewed as a unified diff.

**Blocked by:** 01 (`write` Mutating Tool with Tool Confirmation) - reuses its
Mutating Tool marker, `confirm` seam and REPL prompt.

**Spec:** `docs/specs/0016-write-tools.md` (Implementation Decisions: Tools
module, Two-phase Mutating Tool, `edit` rules, Size limit, Tool results, Tool
Registry, Preview; Testing Decisions); **ADRs:** none.

- [x] `edit` targets pass the existing file-target rules (relative, inside
  the Workspace Root, regular file, not `.env`/`*.pem`/`*.key`) through the
  workspace module's existing validation.
- [x] The file is read with the existing bounded reader and
  `ROUTER_MAX_READ_BYTES`; binary, non-UTF-8 or oversized files are Tool
  errors.
- [x] Exact, case-sensitive matching only: zero matches is an error; more
  than one without `replace_all` is an error naming the count; `replace_all`
  replaces every occurrence; `new_string` equal to `old_string` is an error.
- [x] A resulting file larger than `ROUTER_MAX_WRITE_BYTES` in UTF-8 bytes is
  a Tool error; nothing is truncated. The result reports path and number of
  replacements.
- [x] `edit` is registered with its schema (`path` and `old_string`
  `minLength: 1`, `new_string` string, all required; optional boolean
  `replace_all` default false; no extra properties), marked as a Mutating
  Tool, and advertised in `TOOL_DEFS`.
- [x] Every check runs before `confirm`; the preview is a `difflib` unified
  diff labelled with the relative path; approve writes, reject or missing
  callback leaves the file byte-identical and returns the rejection error.
- [x] Applied, rejected and failed `edit` calls produce the existing Tool
  execution Call Log entry and `tool>` line.
- [x] README Mutating Tools section documents `edit` and its exact-match
  rules (no fuzzy matching).
- [x] Tests at the `execute_batch` and `run_repl` seams cover the above. Full
  offline suite passes.
