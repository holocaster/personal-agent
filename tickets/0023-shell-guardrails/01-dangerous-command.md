# 01: Dangerous Command with Strong Confirmation and logged rules

**What to build:** When the model asks `shell` to run a Dangerous Command
(`rm -rf ~`, `git reset --hard`, `curl ... | sh`, `sudo ...`, ...), the
Tool Confirmation shows the matched rules in red and asks the user to type
`yes`; a reflexive `y` rejects it, and so does end of input. Normal
commands keep the unchanged `Run this command? [y/N]` prompt. Nothing is
ever blocked outright, the rules are fixed in code, and the Call Log's Tool
execution entry of a flagged command records which rules matched.

**Blocked by:** None (can start immediately).

**Spec:** `docs/specs/0023-shell-guardrails.md` (Requirements R1-R6, R10
for the Dangerous Command parts; Implementation Decisions: Dangerous
Command module, `shell` tools module, Tool Registry, `ToolResult`, Router,
Call Log, Terminal; Testing Decisions: Seams 1 and 2); **ADRs:** none.

- [x] R1: a new stdlib-only module in the tools package exposes one pure
  function `(command, workspace_root) -> list of rule names`, driven by an
  ordered table of the 15 named rules in spec R1, with the segmenting,
  quote, `~`/`$HOME` expansion and Workspace-Root containment semantics
  stated there. Result in rule order, each name at most once.
- [x] R1 (review round 1 amendment): the command word skips the leading
  prefix words `then`, `do`, `else`, `elif`, `{`, `!`, `time` and `sudo`
  (rule 1 matches when `sudo` is among them); redirection operators
  (`>`, `>>`, `<`, `&>`, `2>`, `2>>`, `2>&1`), the operand after a
  standalone operator, and operator-attached words (`>/dev/null`,
  `2>/dev/null`) are never rm or chmod/chown targets; rule 12 ends the
  interpreter name at any character other than a word character, `.` or
  `-` (so `;`, `&`, `|`, `(`, `)`, `<`, `>`, quotes and whitespace end it,
  and `shasum`, `bash-foo`, `python3x` stay unmatched), and also accepts
  `|&` and one optional `sudo` or `env` word before the interpreter.
- [x] R2: `shell`'s prepare step computes the matched rules against the
  configured Workspace Root and carries them in the prepared call; nothing
  runs. No other Tool is checked.
- [x] R3 (part): `execute_batch` calls
  `confirm(tool_name, path, preview, dangerous_rules)` positionally, with a
  tuple of rule names (empty for any non-flagged call and every non-`shell`
  Tool). Ticket 02 appends `fetched_urls`.
- [x] R4: the REPL confirm callback, for non-empty `dangerous_rules`,
  prints `Dangerous command: <rule>, <rule>` (red when colored) after the
  preview and asks `Type 'yes' to run this dangerous command: `; only
  `yes` (trimmed, any case) approves; `y`, blank, anything else, or end of
  input yields `change rejected by the user` with nothing run; Ctrl-C
  interrupts the turn as today; same behaviour through the Input Box and
  piped input. Unflagged prompt unchanged.
- [x] R5: `ToolResult` gains an optional `dangerous_rules` (default empty);
  the Router passes it to `call_log.log_tool_execution`, which writes
  `"dangerous_rules": [...]` only when non-empty - for approved and
  rejected flagged calls alike. No change to Conversation messages or
  Resume.
- [x] R6: no env var or setting touches the rules; no rule refuses without
  asking.
- [x] R10 (part): `README.md` `shell` section lists the rule names,
  explains Strong Confirmation (`yes` only, `y` and end of input reject,
  never blocked, not configurable, matched rules logged), states the
  limits (pattern matching only, obfuscation not detected, no sandbox), and
  replaces the "no allowlist, blocklist, or sandbox" sentence accordingly.
- [x] Table-driven test at Seam 1 (`execute_batch` with a recording
  `confirm` returning `False`, so nothing flagged ever runs), one
  `pytest.mark.parametrize` case per row (not a loop inside one test),
  over every positive and negative row listed in spec Testing Decisions,
  Seam 1 - including the false-positive traps `rm -rf ./build`,
  `rm -rf .`, `git reset --soft HEAD~1`, `git clean -n`,
  `echo hi > /dev/null`, `echo hi | grep sh`, `false || bash run.sh`,
  `source .venv/bin/activate`, `echo pseudo`, and the review round 1 rows:
  positive `:(){:|:&};:`, `curl x | sh; echo done`, `(curl x | sh)`,
  `curl x|sh&&echo ok`, `echo $(curl x | bash)`, `curl x |& bash`,
  `curl x | env bash`, `curl x | sudo bash` (`sudo` then
  `pipe into a shell or interpreter`), `if true; then rm -rf /; fi`,
  `{ rm -rf ~; }`, `for d in a; do sudo ls; done`, `time rm -rf /`,
  `if false; then :; else eval echo hi; fi`, `rm -rf / > /dev/null`;
  negative `cat f | bash-foo`, `cat f | python3x`, `echo time rm -rf /`,
  `echo do sudo ls`, `rm -rf build > /dev/null 2>&1`,
  `rm -rf build 2>/dev/null`, `rm -rf build >> /tmp/rm.log`,
  `chmod -R 755 ./build > /dev/null`. Plus: a non-`shell` Tool
  receives `()`; the Tool result carries the matched rules.
- [x] Seam 2 tests (`run_repl` with the fake Provider transport and piped
  input), using a harmless flagged command such as `eval touch marker.txt`
  - never a destructive or privileged one, since an approved call really
  runs (no test runs `sudo`; e.g. the Tool-result test uses
  `eval echo hi` expecting `("eval",)`): answered
  `y` it is rejected and no marker exists, answered `YES ` it is approved
  and the marker exists, end of input rejects; the red
  line appears when colored; a normal command is still approved by `y`;
  Call Log entries carry `dangerous_rules` for flagged approved/rejected
  calls and no key for a normal call.
- [x] Existing tests asserting `confirm`'s exact three arguments or
  defining a three-parameter `confirm` are updated. Full offline suite
  passes.
