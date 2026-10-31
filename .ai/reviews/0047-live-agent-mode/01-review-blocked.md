# 0047-01: Ready for review; reviewer startup blocked

**Ticket:** `tickets/0047-live-agent-mode/01-live-mode-switching.md`.

**Status:** Implementation and validation complete. No independent review, approval or security verdict was obtained. Two `sdd-reviewer` startup attempts failed with `agent thread limit reached`. This is an environment capability limit, not an approval rejection or a code finding.

**Exact subject:** feature 0047's implementation commit following `deb9abbac7c13a42c651dfc33ee6c718a81338a9`, the separate feature 0046 commit. This now provides a durable Git range for the deferred review. Original runtime snapshots are `/tmp/pa-0047-baseline-8qcaqkia` and `/tmp/pa-0047-candidate-k6ymxb1d`; they include the previously approved feature 0046 baseline.

**Original runtime review diff:** `/tmp/pa-0047-review.diff`; SHA-256 `ca6527233bf813d360addae5604b02a88533ec89c2c3b931bf35694ab585e071`. Baseline/candidate pointers also exist in `/tmp/pa-0047-baseline-path` and `/tmp/pa-0047-candidate-path`. The user subsequently authorized commit and push; only tracking artifacts changed after validation.

## Validation evidence

- Final full suite outside the restricted sandbox: `.venv/bin/python -m pytest -q --tb=short` — 1990 passed in 112.75s.
- Initial sandbox full run: 1947 passed, nine loopback HTTP failures, 33 HTTP fixture errors caused by socket PermissionError, and one MCP cancellation timeout. The MCP case passed independently outside the sandbox in 1.13s; the final unrestricted full run resolved all failures without production changes.
- Implementer proved missing confirmation shortcut callback and stale same-batch policy with failing regressions before fixing them. Agent-mode module: 26 passed; shell module: 179 passed. Final full suite includes all later input, queued-shortcut and callback-failure changes.
- Root actual PTY check passed switching during blocked work, pending approval draft preservation, question-answer preservation, preview switching/return, main-thread Ctrl-C interruption and reader cleanup.
- Root task-to-work transition first reproduced queued Shift+Tab being delayed; final check passed immediate mode change, ordered draft preservation and reader cleanup.
- Actual shell regression verifies child cleanup, skipped remaining tool batch, continuation preservation and subsequent input consumption.
- `compileall` and `git diff --check` passed during implementation. Final source snapshot equality and diff check are checked before handoff.

## Next action

Investigate the agent-thread limit in the next session as requested by the user, then run a fresh independent `sdd-reviewer` against the recorded Git range, including mandatory BRANCH security review. Keep the ticket ready_for_review until that review approves it. Preserve unrelated dirty edits; do not restore or clean them.
