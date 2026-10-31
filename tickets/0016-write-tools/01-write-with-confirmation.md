# 01: `write` Mutating Tool with Tool Confirmation and ROUTER_MAX_WRITE_BYTES

**What to build:** The model can call `write(path, content)` to create a file,
or overwrite one, inside an existing directory of the Workspace Root. Before
anything touches disk the REPL shows a Tool Confirmation: the full content
for a new file, a unified diff for an overwrite, then `Apply this change?
[y/N] `. Only `y`/`yes` applies it; anything else, or end of piped input,
rejects it and the model receives a "change rejected by the user" error
result. This ticket lands the whole confirmation gate (registry marker,
`execute_batch`/`route()` `confirm` seam, REPL prompt in piped and Input Box
modes) that ticket 02 reuses, plus `ROUTER_MAX_WRITE_BYTES` and the README.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0016-write-tools.md` (Implementation Decisions: Tools
module, Two-phase Mutating Tool, `write` path rules, Size limit, Tool
results, Tool Registry, Confirmation seam, Preview, REPL Tool Confirmation,
Call Log, System Prompt, README; Testing Decisions); **ADRs:** none.

- [x] `ROUTER_MAX_WRITE_BYTES` is parsed and validated in the workspace
  configuration exactly like `ROUTER_MAX_READ_BYTES` (unset/empty = 65536,
  positive whole-byte count, otherwise `main` prints a configuration error
  and exits 1). The test env isolation clears it.
- [x] `write` reuses the workspace module's existing path validation (no
  second resolver): relative path, no `..`, parent directory resolved
  strictly inside the Workspace Root and never created, final name not
  `.env`/`*.pem`/`*.key`; an existing target (symlink included) must pass the
  existing file-target rules; dangling symlinks, directories and directory
  symlinks are rejected.
- [x] `write` content over the limit in UTF-8 bytes, or not encodable as
  UTF-8, is a Tool error; content is written as bytes with no newline
  translation; an OS error on write is a Tool error. The result reports path,
  bytes written, and created vs overwritten.
- [x] `write` is registered in the Tool Registry with its schema (`path`
  `minLength: 1`, `content` string, both required, no extra properties),
  marked as a Mutating Tool, and advertised in `TOOL_DEFS`.
- [x] `execute_batch` and `route()` accept an optional `confirm` callback.
  For a Mutating Tool, every check runs before `confirm` is called (a failing
  call never prompts); `True` applies, `False` or no callback yields the
  rejection error result with nothing written. Non-mutating Tools never call
  `confirm`. A `KeyboardInterrupt` from `confirm` ends the turn as
  `interrupted` with nothing written.
- [x] Preview: full content for a new file, `difflib` unified diff labelled
  with the relative path for an overwrite.
- [x] The REPL builds `confirm` per routed turn: stops the spinner, prints a
  header naming the Tool and path, the preview sanitized for control
  characters (multiline), and `Apply this change? [y/N] `; resumes the
  spinner afterwards. Interactive mode asks through the Input Box's
  prompt_toolkit session as a single-line prompt; piped/plain mode reads the
  next line of the same input source, and EOF rejects.
- [x] Applied, rejected and failed `write` calls each produce the existing
  Tool execution Call Log entry and the live `tool>` line; no new entry type,
  `log_version` unchanged. Workspace Tools and other built-ins still run
  without confirmation.
- [x] README: Workspace Root no longer described as read-only; a Mutating
  Tools section covers `write`, Tool Confirmation (preview, `[y/N]`, piped
  behavior), no parent-directory creation, `ROUTER_MAX_WRITE_BYTES`, full
  content in the Call Log, and Git as the only revert mechanism.
- [x] Tests at the `execute_batch`, `run_repl` (fake Provider via
  `install_fake_urlopen`), `InputBox` (pipe input) and `main` seams cover the
  above. Full offline suite passes.
