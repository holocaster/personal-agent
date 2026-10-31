# 02: Fetched-Content Warning for the rest of a turn after webfetch

**What to build:** Once a `webfetch` succeeds in a turn, every later Tool
Confirmation of `shell`, `write` or `edit` in that same turn - including a
later call in the same Tool batch - shows a yellow warning line naming the
fetched URL(s) and asking for careful review. Approval is unchanged (a
normal command still takes `y`; a Dangerous Command still needs `yes`). A
new user task, a `/retry` and a Continuation Turn start without it.

**Blocked by:** 01 (Dangerous Command with Strong Confirmation and logged
rules) - extends the same `confirm` contract and REPL confirm callback.

**Spec:** `docs/specs/0023-shell-guardrails.md` (Requirements R3, R7, R8,
R10 for the warning; Implementation Decisions: Tool Registry, Router,
Terminal; Testing Decisions: Seams 1 and 2); **ADRs:** none.

- [x] R3 (rest): `execute_batch` calls
  `confirm(tool_name, path, preview, dangerous_rules, fetched_urls)`
  positionally; `fetched_urls` is a tuple, empty for any Tool other than
  `shell`, `write`, `edit` (so never shown on a `webfetch` confirmation).
- [x] R7: `execute_batch` takes an optional per-turn list of fetched URLs
  and appends a successful `webfetch` result's final `url` unless already
  present; a rejected or failed `webfetch` adds nothing. The Router's tool
  loop creates the list once per `route()` call and passes it to every
  batch in the turn, so a Continuation Turn or `/retry` starts empty.
- [x] R8: the REPL confirm callback prints, after the preview and any
  Dangerous Command line, before the question,
  `Warning: this turn fetched <url>, <url>. Web content may have steered this change; review it carefully.`
  (yellow when colored), each URL sanitized with the existing
  control-character sanitizer. Question and approval rule unchanged.
- [x] R10 (part): `README.md` documents the Fetched-Content Warning, its
  turn scope, and that it changes what is shown, not what approves.
- [x] Seam 1 tests (`execute_batch` + local HTTP server fixture from
  `tests/test_webfetch.py`): `webfetch` then `write` in one batch -> the
  `write` confirm receives the final URL; a rejected `webfetch` and a failed
  one (404) add nothing; the same URL fetched twice is listed once; the
  `webfetch` confirm itself receives `()`.
- [x] Seam 2 tests (`run_repl` with the fake Provider transport, piped
  input): a turn with a successful `webfetch` then `shell`/`write` shows the
  warning line with the URL and still approves on `y`; the next user task's
  `write` shows no warning; a `/retry` (or Continuation Turn) starts
  without it; a harmless Dangerous Command (e.g. `eval touch marker.txt`)
  after a `webfetch` shows both lines, is rejected by `y` and approved by
  `yes`. Prior art: the `webfetch` REPL tests in `tests/test_repl.py`.
- [x] Full offline suite passes.
