# 01: Compact Tool Confirmation previews with full inspection

**What to build:** Keep interactive Tool Confirmation readable for large file content, diffs and shell commands, with a full scrollable view before explicit approval.

**Blocked by:** None.

**Spec:** none (fast path)

## Acceptance criteria

- [x] The shared interactive confirmation renderer shows small previews fully and bounds large previews to roughly half the terminal height, accounting for wrapping, terminal width, tabs and wide characters. A single huge line cannot flood the display. Show the path, preview line/byte counts, hidden-content notice and diff additions/deletions/hunks where applicable; derive these locally from the actual preview.
- [x] Large interactive previews offer `v` to inspect the entire sanitized original command/content/diff in a read-only scrollable viewer using the installed terminal library. Arrows and Page Up/Down navigate; `q` or Escape closes it and returns to the same approval prompt. Viewing/closing never approves or executes the action; repeated viewing is supported.
- [x] Approval stays explicit: ordinary `y`/`yes` approves, blank/`n`/EOF rejects, dangerous commands still require exact `yes`. Ctrl-C interrupts the turn, including inside the viewer. Danger and fetched-content warnings remain visible next to approval; sanitize both compact and full views through existing control-character protection.
- [x] `write`, `edit`, `apply_patch` and `shell` use the shared rendering path. Preserve existing network/MCP confirmation behavior, mode policies, audit logging and actual operation payloads. Noninteractive/piped confirmations retain full previews and existing prompts; compact interactive behavior must work with `NO_COLOR` too.
- [x] Deterministic checks first reproduce the unbounded interactive preview, then verify bounded multiline/huge-line rendering, full-view content fidelity, navigation/return-to-approval, cancellation and rejection without execution, short-preview compatibility and full piped previews. Relevant terminal/confirmation checks and required existing regressions pass.
- [x] README describes the compact preview, `v` inspection, viewer navigation and unchanged approval requirement concisely. No dependency, model call, AI-generated summary, persistent setting or code comment is added.

## Evidence and execution

`_make_confirm` currently writes the entire sanitized preview before asking approval. Existing InputBox wraps prompt_toolkit 3.0.53. A read-only full-screen viewer can use its existing input/output and the library's Application, Layout and TextArea facilities, keeping full inspection out of scrollback.

Use existing terminal modules and test seams; preserve operation content independently from display truncation. Do not auto-approve after inspection or pipe untrusted preview text into a shell pager. The user authorized implementation; no commits or pushes for this feature are authorized.
