# 0023 - shell guardrails

Brief: `docs/briefs/0023-shell-guardrails.md` (all decisions settled; referenced
below as "brief decision N"). Extends `docs/specs/0018-shell-tool.md`
(`shell`), `docs/specs/0016-write-tools.md` (Tool Confirmation for `write` /
`edit`) and `docs/specs/0022-web-todo-search.md` (`webfetch`, R9-R12).
Vocabulary (Dangerous Command, Strong Confirmation, Fetched-Content Warning,
Tool Confirmation, Mutating Tool, Network Tool, Workspace Root, Call Log,
Continuation Turn, Retry) is in `docs/CONTEXT.md`, including the "shell Tool
scope and opt-out" decision. No ADR applies or is added.

## Problem Statement

Tool Confirmation is the only gate in front of `shell`, `write` and `edit`,
and it is the same `[y/N]` prompt for `ls` as for `rm -rf ~`. A user who has
approved twenty harmless commands types `y` by reflex, so the gate is weakest
exactly when the command is destructive. Since feature 0022, `webfetch` also
brings third-party content into the turn: a page can carry instructions that
steer the model's next `shell` or `write`, and the confirmation gives no hint
that this turn has read anything from the web. The easiest way to hide such
instructions from a human reader of the page - an element marked `hidden`,
`aria-hidden="true"` or styled `display:none` - is kept by the current HTML
conversion and handed to the model as plain text.

## Solution

A fixed set of rules in code flags a `shell` command string as a Dangerous
Command. Its Tool Confirmation becomes Strong Confirmation: the matched rules
are shown (red when colored) and only the exact word `yes` runs it; `y`
rejects. Nothing is ever blocked outright, and the Call Log's Tool execution
entry records which rules matched. Once a `webfetch` succeeds in a turn,
every later Tool Confirmation of `shell`, `write` or `edit` in that turn
carries a Fetched-Content Warning naming the fetched URL(s); approval rules
are unchanged. `webfetch`'s HTML conversion drops elements hidden with the
`hidden` attribute, `aria-hidden="true"`, or an inline `display:none` /
`visibility:hidden` style. `README.md` documents all three.

## User Stories

### Dangerous Command and Strong Confirmation

1. As a user, I want `rm -rf /`, `rm -rf ~`, `rm -rf $HOME`, `rm -rf *` and `rm -rf ..` flagged, so that the commands that wipe my machine or my project cannot pass on a reflexive `y`.
2. As a user, I want a recursive `rm` of an absolute path outside the Workspace Root flagged, so that the model cannot delete things outside the project it was given.
3. As a user, I want `rm -rf ./build`, `rm -r node_modules` and `rm -rf .venv` not flagged, so that normal cleanup inside the workspace keeps its one-letter approval.
4. As a user, I want `rm file.txt` (not recursive) never flagged, so that ordinary deletions are not escalated.
5. As a user, I want `git reset --hard`, `git clean -f` (in any short-flag combination such as `-fd` or `-xdf`), `git push --force` / `-f` and `git checkout -- .` flagged, so that Git - my only undo mechanism without a sandbox - is not destroyed by accident (brief decision 4).
6. As a user, I want `git reset --soft`, `git reset HEAD file`, `git clean -n`, `git push` and `git checkout -- src/file.py` not flagged, so that routine Git use stays cheap.
7. As a user, I want `mkfs`, `mkfs.ext4`, `dd ... of=...` and a redirection into a block device (`> /dev/sda`, `> /dev/nvme0n1`) flagged, so that a disk cannot be overwritten on a reflex.
8. As a user, I want `> /dev/null` and `2>/dev/null` not flagged, so that the most common redirection in shell scripts is not mistaken for a disk write.
9. As a user, I want `chmod -R` / `chown -R` on `/` or `~` flagged, and on `./build` or `.` not flagged, so that only system-wide permission changes are escalated.
10. As a user, I want the classic fork bomb flagged, so that a joke command cannot freeze my machine on a `y`.
11. As a user, I want any `sudo` command flagged, so that a privilege escalation always needs a deliberate `yes`.
12. As a user, I want a pipe into `sh`, `bash`, `zsh`, `python`, `python3`, `perl` or `node` flagged, so that `curl ... | sh` and `base64 -d | sh` - the usual way to hide what really runs - need a deliberate `yes` (brief decision 5).
13. As a user, I want `eval`, `bash -c "$(...)"`, `sh -c "$(...)"`, `source <(...)` and `. <(...)` flagged, so that evaluated data is treated like piped data.
14. As a user, I want `ls | sort`, `echo hi | grep sh`, `false || bash run.sh`, `source .venv/bin/activate` and `bash -c "echo hi"` not flagged, so that pipes and scripts that do not evaluate data stay cheap.
15. As a user, I want a word that merely contains a rule word (`pseudo`, `evaluate`, `shasum`) not flagged, so that the rules match commands, not substrings.
16. As a user, I want a command that matches several rules (`sudo rm -rf /`) to show every matched rule, so that I see the whole risk.
17. As a user, I want the matched rules shown in red above the question, so that I notice the escalation before I answer.
18. As a user, I want only `yes` (trimmed, any case) to approve a Dangerous Command and `y` to reject it, so that the reflexive answer is the safe one (brief decision 3).
19. As a user, I want a rejected Dangerous Command to reach the model as the usual `change rejected by the user` error, so that the model can adapt within the same turn.
20. As a user piping answers into the REPL, I want the same `yes` rule to apply and end of input to reject, so that non-interactive use cannot approve a Dangerous Command by accident.
21. As a user, I want Ctrl-C at Strong Confirmation to interrupt the turn exactly as at a normal confirmation, so that I have one way to stop everything.
22. As a user, I want a Dangerous Command never to be blocked outright, so that I can still run it deliberately by typing `yes` (brief decision 3).
23. As a user, I want a normal (unflagged) `shell` command to keep the unchanged `Run this command? [y/N]` prompt, so that the guardrail costs nothing for everyday commands.
24. As a user auditing a Session, I want the Call Log's Tool execution entry of a flagged command to list the matched rules, whether I approved or rejected it, so that I can review what was escalated and calibrate the rules later (brief decision 7).
25. As a user, I want no environment variable that switches the rules off or changes them, so that the protection cannot be disabled by configuration (brief decision 6).

### Fetched-Content Warning

26. As a user, I want every `shell`, `write` or `edit` confirmation after a successful `webfetch` in the same turn to carry a warning naming the fetched URL(s), so that I read the change knowing web content may have steered it.
27. As a user, I want the warning to name every distinct URL fetched so far in the turn, so that I know which pages were involved.
28. As a user, I want the warning to apply even when the `webfetch` and the `shell` call are in the same Tool batch, so that the order of calls, not the batching, decides.
29. As a user, I want no warning after a `webfetch` that failed or that I rejected, so that the warning only appears when outside content actually entered the turn.
30. As a user, I want the warning not to change what approves (a normal command still takes `y`), so that it informs rather than adds friction.
31. As a user, I want a Dangerous Command after a `webfetch` to show both the matched rules and the warning and still require `yes`, so that both signals are visible together.
32. As a user, I want a new task, a `/retry` and a Continuation Turn to start without the warning, so that it stays tied to the turn where the fetched content and the model's actions meet (brief decision 8).
33. As a user, I want the warning not shown on the `webfetch` confirmation itself, so that it appears only where a permanent side effect is at stake.
34. As a user, I want URLs in the warning sanitized like every other untrusted text, so that a crafted URL cannot inject terminal control sequences.

### Hidden HTML

35. As a user, I want `webfetch` to drop the content of any element with the `hidden` attribute, so that text invisible to a human reader does not reach the model.
36. As a user, I want the same for `aria-hidden="true"` and for an inline `style` containing `display:none` or `visibility:hidden` regardless of whitespace or case, so that the common hiding tricks are covered (brief decision 9).
37. As a user, I want a hidden element's nested children dropped with it, including nested elements of the same tag, so that `<div hidden><div>a</div>b</div>` loses both `a` and `b`.
38. As a user, I want visible content after a hidden element kept, and a hidden void element such as `<input hidden>` to drop nothing else, so that the conversion never loses the rest of the page by mistake.
39. As a user, I want `aria-hidden="false"` and `style="display:block"` elements kept, so that only actually hidden content is dropped.

### Docs

40. As a user, I want `README.md` to list the Dangerous Command rules, explain Strong Confirmation, the Fetched-Content Warning and hidden-element dropping, so that I know what the guardrails do and what they do not do.

## Requirements

### Dangerous Command and Strong Confirmation

- **R1 Rule set.** A fixed, ordered list of named rules in a new tools
  module. Each rule name is a fixed human-readable string shown to the user
  and written to the Call Log. Matching is on the command string, not a full
  shell parse (brief, Out of scope). A command is split into command
  segments at `;`, `&&`, `||`, `|`, `&`, `(`, `)` and newlines, respecting
  quotes where the string can be tokenized (fall back to whitespace
  splitting when quoting is unbalanced). The *leading prefix words* of a
  segment are the run of words at its start that are each one of `then`,
  `do`, `else`, `elif`, `{`, `!`, `time` or `sudo`; the *command word* is
  the first word after that run. So `then rm -rf /`, `{ rm -rf ~`,
  `do sudo ls` and `time rm -rf /` have command words `rm`, `rm`, `ls`
  and `rm`; a prefix word anywhere else (`echo time rm -rf /`) is an
  ordinary argument. *Redirections* in a segment - a word that is a
  redirection operator (`>`, `>>`, `<`, `&>`, or a file-descriptor form
  such as `2>`, `2>>`, `2>&1`), the word right after a standalone operator,
  and a word that starts with an operator with its operand attached
  (`>/dev/null`, `2>/dev/null`) - are never rm or chmod/chown targets
  (rules 2 and 10). Rules, in order:
  1. `sudo` - a segment whose leading prefix words include `sudo`.
  2. `recursive rm on a protected path` - command word `rm` with a
     recursive flag (`--recursive`, or a single-dash flag word containing
     `r` or `R`, anywhere in the segment) and at least one non-flag,
     non-redirection target
     that, with surrounding quotes removed and trailing `/` ignored, either
     is literally `/`, `~`, `$HOME`, `${HOME}`, `*` or `..`, or - after
     expanding a leading `~`, `$HOME` or `${HOME}` to the home directory and
     joining a relative target to the Workspace Root - lexically normalizes
     (no symlink resolution) to a path that is neither the Workspace Root
     nor inside it. So `/tmp/x` (root not under `/tmp`), `/*`, `~/*` and
     `../other` match; `.`, `./build`, `build/*` and an absolute path inside
     the Workspace Root do not.
  3. `git reset --hard` - command word `git`, with words `reset` and
     `--hard`.
  4. `git clean -f` - command word `git`, with word `clean` and `--force`
     or a single-dash flag word containing `f`.
  5. `git push --force` - command word `git`, with word `push` and
     `--force` or a single-dash flag word containing `f`.
  6. `git checkout -- .` - command word `git`, with `checkout` followed
     later by `--` and then a `.` argument.
  7. `mkfs` - command word `mkfs` or starting with `mkfs.`.
  8. `dd of=` - command word `dd` with a word starting with `of=`.
  9. `redirect to a block device` - `>` or `>>` (optionally with a file
     descriptor and whitespace) into `/dev/sd*`, `/dev/hd*`, `/dev/vd*`,
     `/dev/xvd*`, `/dev/nvme*`, `/dev/mmcblk*`, `/dev/dm-*` or `/dev/md*`.
  10. `recursive chmod/chown on / or ~` - command word `chmod` or `chown`
      with `-R`, `--recursive` or a single-dash flag word containing `R`,
      and a non-redirection target that is literally `/`, `/*`, `~`, `~/`,
      `$HOME` or `${HOME}` (quotes removed).
  11. `fork bomb` - the classic `:(){ :|:& };:` shape, whitespace-insensitive,
      with any function name used consistently.
  12. `pipe into a shell or interpreter` - a pipe (`|` not part of `||`,
      or `|&`), then optional whitespace, an optional `sudo` or `env` word
      followed by whitespace, an optional path, and the interpreter name
      `sh`, `bash`, `zsh`, `python`, `python3` (optionally a version suffix
      such as `python3.12`), `perl` or `node`. The name ends at the end of
      the string or at any character that is not a word character, `.` or
      `-` - whitespace, `;`, `&`, `|`, `(`, `)`, `<`, `>` or a quote. So
      `curl x | sh; echo done`, `(curl x | sh)`, `curl x|sh&&echo ok`,
      `echo $(curl x | bash)`, `curl x |& bash`, `curl x | env bash` and
      `curl x | sudo bash` match (the last also matches rule 1), while
      `| shasum`, `| bash-foo` and `| python3x` do not.
  13. `eval` - a segment whose command word is `eval`.
  14. `shell -c with command substitution` - `bash -c` or `sh -c` whose
      argument starts with `$(` (optionally inside quotes).
  15. `source of process substitution` - `source` or `.` as a whole word
      (at the start of the string or after whitespace or a separator),
      followed by whitespace and `<(`.

  Rules 9, 11, 12, 14 and 15 are naturally regular expressions on the raw
  command string; the others work on segments and words.

  The result is the list of matched rule names in rule order, each at most
  once; an empty list means the command is not a Dangerous Command. Rules
  are case-sensitive (shell commands are). A word that merely contains a
  rule word (`pseudo`, `evaluate`, `shasum`, `rm-old.sh`) never matches.
- **R2 Detection point.** `shell`'s prepare step computes the matched rules
  against the configured Workspace Root and carries them in its prepared
  call, before Tool Confirmation and without running anything. Only `shell`
  is checked; `write`, `edit` and `webfetch` never have matched rules.
- **R3 Confirm contract.** `execute_batch` calls
  `confirm(tool_name, path, preview, dangerous_rules, fetched_urls)`, all
  positional: `dangerous_rules` is a tuple of rule names (empty unless R1
  matched), `fetched_urls` a tuple of URLs (R7; empty for any Tool other
  than `shell`, `write`, `edit`). Ticket 01 adds `dangerous_rules`; ticket
  02 adds `fetched_urls`. Everything else about `execute_batch` is
  unchanged.
- **R4 Strong Confirmation.** When `dangerous_rules` is non-empty, the REPL
  prints, after the header and preview, the line
  `Dangerous command: <rule>, <rule>` (red when colored), then asks
  `Type 'yes' to run this dangerous command: ` through the same input path
  as today (Input Box interactively, otherwise the REPL's input source).
  It approves only when the answer, trimmed and lowercased, equals `yes`;
  `y`, a blank line, anything else, or end of input rejects with the
  existing `change rejected by the user` Tool error and nothing runs.
  Ctrl-C interrupts the turn as today. With no matched rules the prompt is
  unchanged (`Run this command? [y/N] `, `y`/`yes` approves).
- **R5 Call Log.** The `tool_execution` entry of a `shell` call with
  matched rules gains `"dangerous_rules": [<rule>, ...]`, whether the call
  was approved (and succeeded or failed) or rejected. Entries of every
  other call are unchanged (no key). The rules travel from the confirmed
  Tool call to the log on the Tool result; they are not part of the
  Conversation messages, so Resume is unaffected.
- **R6 Fixed and non-blocking.** No env var, setting or file changes or
  disables the rules; no rule refuses a command without asking.

### Fetched-Content Warning

- **R7 Turn tracking.** Each routed turn (one `route()` call: a user task,
  a `/retry`, or a Continuation Turn) starts with an empty list of fetched
  URLs, shared across all its Tool rounds. When a `webfetch` call succeeds,
  its result's final `url` is appended unless already present. Rejected or
  failed `webfetch` calls add nothing. Because `execute_batch` runs calls in
  order, a `shell`/`write`/`edit` later in the same batch as a successful
  `webfetch` already sees it.
- **R8 Warning line.** When `fetched_urls` is non-empty for a `shell`,
  `write` or `edit` confirmation, the REPL prints, after the preview (and
  after the Dangerous Command line, if any) and before the question:
  `Warning: this turn fetched <url>, <url>. Web content may have steered this change; review it carefully.`
  (yellow when colored), with each URL passed through the existing
  control-character sanitizer. The question and approval rule are those of
  the call without the warning (R4 or the normal prompt).

### Hidden HTML

- **R9 Hidden elements.** In `webfetch`'s HTML-to-text conversion, a start
  tag carrying any of: a `hidden` attribute (any value, or none);
  `aria-hidden` whose value, trimmed and lowercased, is `true`; or a
  `style` whose value, with all whitespace removed and lowercased, contains
  `display:none` or `visibility:hidden` - has its content dropped the way
  `script`/`style` content is, up to its matching end tag, counting nested
  start/end tags of the same name so a nested same-name element does not
  end the drop early. Exception, for elements whose end tag is optional in
  HTML (`li`, `p`, `dt`, `dd`, `tr`, `td`, `th`, `option`, `optgroup`,
  `rt`, `rp`, `thead`, `tbody`, `tfoot`, `colgroup`, `caption`): while
  dropping such an element, a start tag of the same name ends the drop
  (an implicit close, as a browser does) instead of nesting - unless it
  sits inside another element opened within the dropped element and not
  yet closed by its own end tag, so a nested list inside a hidden `li`
  stays dropped. The start tag that ended the drop is then handled like
  any other (it may itself start a new drop). So
  `<ul><li hidden>x<li>a</ul>` keeps `a`,
  `<p hidden>x<p>y</p><p>after</p>` keeps `y` and `after`, and
  `<ul><li hidden><ul><li>x</li></ul></li><li>b</li></ul>` drops `x` and
  keeps `b`. An unclosed hidden element drops to the end of the
  document. A hidden void element (`area`, `base`, `br`, `col`, `embed`,
  `hr`, `img`, `input`, `link`, `meta`, `source`, `track`, `wbr`) and a
  self-closing tag drop nothing beyond themselves. Everything else about
  the conversion (R11 of spec 0022) is unchanged.

### Docs

- **R10 README.** `README.md` documents: the Dangerous Command rule list
  (by name), Strong Confirmation (`yes` only, `y` rejects, end of input
  rejects, never blocked, not configurable, matched rules in the Call Log),
  the known limits (pattern matching only; obfuscated commands are not
  detected; no sandbox); the Fetched-Content Warning and its turn scope;
  and hidden-element dropping in the Network Tools section. The `shell`
  section's "no allowlist, blocklist, or sandbox" sentence is updated to
  mention the escalation.

## Implementation Decisions

- **New Dangerous Command module in the tools package** holds R1 as one
  pure function taking the command string and the Workspace Root and
  returning the matched rule names. The rules are a module-level ordered
  table of `(name, check)` entries; checks use `shlex` (with
  `punctuation_chars` to split segments) and `re`, stdlib only. No shell is
  invoked, no path touches disk.
- **`shell` tools module**: the prepared shell call gains the matched rules
  (R2), computed in the prepare step from the configured Workspace Root.
- **Tool Registry (`execute_batch`)**: calls `confirm` with the R3
  arguments, taking `dangerous_rules` from the prepared call when present
  (`shell` only) and the fetched URLs from an optional per-turn list
  parameter (only for `shell`, `write`, `edit`); appends a successful
  `webfetch` result's final URL to that list (R7). The Tool result carries
  the matched rules so the Router can log them (R5).
- **Provider contract `ToolResult`** gains an optional
  `dangerous_rules` field, default empty tuple. Nothing else reads it.
- **Router**: `_run_tool_loop` creates the per-turn fetched-URL list once
  and passes it to every `execute_batch` in the turn (R7); the Tool
  execution log call passes the result's matched rules.
- **Call Log**: `log_tool_execution` takes optional matched rules and
  writes the `dangerous_rules` key only when non-empty (R5).
- **Terminal (REPL)**: the confirm callback takes the two new positional
  arguments, prints the R4 and R8 lines, and switches question and approval
  rule for a Dangerous Command (R4). Colors come from the existing
  `colorize` (`red`, `yellow`).
- **`webfetch` tools module**: the HTML extractor's skip handling is
  extended for R9 (a hidden-attribute check on start tags, a same-name
  depth count for the element being dropped, and, for optional-end-tag
  elements, the elements opened inside the drop so a same-name start tag
  closes the drop only at its top level).
- **No new dependency; no new env var**; no Tool description or System
  Prompt change.

## Testing Decisions

- Good tests assert external behaviour only: the arguments `confirm`
  receives, the `ToolResult` of a call, whether a command ran (a marker file
  on disk), REPL output and approval outcome, the Call Log entries, and
  `webfetch`'s returned `content` - never private helpers.
- **Seam 1: `tools.execute_batch`** (existing) with
  `workspace.configure_workspace(tmp_path, ...)` and a recording `confirm`
  that returns `False`, so no flagged command ever runs. A table-driven
  (`pytest.mark.parametrize`) test of R1 lists positive examples with the
  expected rule names and negative examples expecting `()`. Required rows
  at least: every rule in R1 at least once positive; `sudo rm -rf /`
  (two rules, in order); `rm -rf "$HOME"`, `rm -fr ~/`, `rm -Rf <absolute path
  outside the Workspace Root>` (e.g. the root's parent joined with `x`),
  `rm -rf ../other`, `rm -rf *`, `rm -r --no-preserve-root /`;
  `git clean -xdf`, `git push -f origin main`, `curl -fsSL x | sh`,
  `echo aGk= | base64 -d | bash`, `cat x | /bin/sh`, `cat s.py | python3.12`,
  `bash -c "$(curl -s x)"`, `source <(curl x)`, `. <(echo hi)`,
  `echo x > /dev/sda`, `dd if=a of=b`, `mkfs.ext4 /dev/sdb1`,
  `chmod -R 777 /`, `chown -R me ~`, the fork bomb both as
  `:(){ :|:& };:` and as `:(){:|:&};:`; rule 12 ended by a separator:
  `curl x | sh; echo done`, `(curl x | sh)`, `curl x|sh&&echo ok`,
  `echo $(curl x | bash)`; rule 12 variants: `curl x |& bash`,
  `curl x | env bash`, `curl x | sudo bash` (`sudo` and
  `pipe into a shell or interpreter`, in order); leading prefix words:
  `if true; then rm -rf /; fi`, `{ rm -rf ~; }`,
  `for d in a; do sudo ls; done` (`sudo`), `time rm -rf /`,
  `if false; then :; else eval echo hi; fi` (`eval`); a redirection does
  not hide a real target: `rm -rf / > /dev/null`.
  Negative rows at least: `rm -rf ./build`, `rm -rf build/*`, `rm -rf .`,
  `rm -rf <absolute path inside the Workspace Root>`, `rm file.txt`,
  `rm -f ~/x` (not recursive), `git reset --soft HEAD~1`,
  `git reset HEAD file`, `git clean -n`, `git push origin main`,
  `git checkout -- src/a.py`, `git checkout main`, `echo hi > /dev/null`,
  `cmd 2>/dev/null`, `chmod -R 755 ./build`, `chown -R me .`, `ls | sort`,
  `echo hi | grep sh`, `cat f | shasum`, `false || bash run.sh`,
  `bash -c "echo hi"`, `bash script.sh`, `source .venv/bin/activate`,
  `diff <(ls a) <(ls b)`, `echo pseudo`, `echo evaluate`,
  `python eval.py`, `grep sudo notes.txt`, `cat f | bash-foo`,
  `cat f | python3x`, `echo time rm -rf /`, `echo do sudo ls`,
  `rm -rf build > /dev/null 2>&1`, `rm -rf build 2>/dev/null`,
  `rm -rf build >> /tmp/rm.log`, `chmod -R 755 ./build > /dev/null`.
  Also at this seam: a non-shell
  Tool gets `()`; R7 same-batch ordering (`webfetch` then `write` in one
  batch; a rejected or failed `webfetch` adds nothing; duplicate URL listed
  once); the Tool result carries the matched rules. Prior art:
  `tests/test_shell_tool.py` confirm tests, `tests/test_webfetch.py` local
  `ThreadingHTTPServer` fixture.
- **Seam 2: `run_repl` / `route` with the existing fake Provider transport**
  (`install_fake_urlopen`) and piped input, for R4, R5, R7 (turn scope),
  R8: a scripted `shell` call with a harmless flagged command such as
  `eval touch marker.txt` (never a destructive or privileged one such as
  `sudo ...` - an approved call really runs; no test runs `sudo`)
  answered `y` (rejected, no marker, red line shown when colored),
  answered `YES ` (approved, marker created), and at end of input
  (rejected); a normal command still approved by `y`;
  the Call Log `tool_execution` entry has `dangerous_rules` for the flagged
  call (approved and rejected) and no key for a normal call; a turn with a
  successful `webfetch` then `write` shows the warning with the URL, a next
  user task's `write` does not; a Continuation Turn or `/retry` starts
  without it. Prior art: `tests/test_repl.py` confirm and Call Log tests,
  `tests/test_input_box.py` confirmation tests, `tests/test_routing.py`
  confirm forwarding.
- **Seam 3: `webfetch` via `execute_batch` against the local HTTP server**
  (existing) for R9: each hiding form, case/whitespace variants of the
  style, nested same-name elements, a hidden void element followed by
  visible text, `aria-hidden="false"` and `display:block` kept, and the
  three optional-end-tag examples in R9. Prior art:
  `tests/test_webfetch.py` HTML conversion tests.
- Existing tests that assert `confirm`'s exact three arguments or define a
  three-parameter `confirm` are updated to the R3 contract.
- The full offline suite must pass.

## Out of Scope

As the brief: any sandbox (`bwrap` deferred); blocking commands, an
allowlist or auto-approval; configurable rules; full shell parsing and
obfuscation beyond the listed interpreter-pipe forms (`r''m -rf ~`,
variables, `find / -delete`, a command nested in a quoted `bash -c '...'`
string); treating `read_file` content as external for the warning; hidden
elements styled through CSS classes or stylesheets. Also: full HTML
implicit-close rules beyond R9's same-name case (a hidden optional-end-tag
element with no end tag that is ended only by its parent's end tag or by
another tag name, such as `<ul><li>a<li hidden>x</ul>after` or
`<p hidden>x<div>y</div>`, still drops up to its own end tag or the end of
the document); leading shell keywords other than those in R1 (`if`,
`while`, `until`, `case`) and prefix-command options (`sudo -u root`,
`time -p`, `env FOO=1 bash`). Also: logging the
Fetched-Content Warning, showing it on `webfetch` confirmations, and any
change to Tool descriptions or the System Prompt.

## Further Notes

- Decided here as direct readings of the brief:
  - R1 rule 2 always flags the literal `/`, `~`, `$HOME`, `*`, `..` targets
    and additionally any target that normalizes outside the Workspace Root
    (so `../other` counts with `..`, and `rm -rf ~` stays flagged even when
    the Workspace Root is the home directory). `rm -rf .` is not in the
    brief's list and is not flagged.
  - R1 `sudo` is skipped when finding a segment's command word, so
    `sudo rm -rf /` reports both rules.
- Amended after review round 1 of tickets 01-03 (orchestrator decisions):
  R1 leading prefix words (`then`, `do`, `else`, `elif`, `{`, `!`, `time`
  besides `sudo`) and the redirection exclusion for rules 2 and 10; rule 12
  ends the interpreter name at any non-word boundary and accepts `|&` and
  one `sudo`/`env` word; R9 implicit close of optional-end-tag elements on
  a same-name start tag at the top level of the drop (the top-level guard is
  added here so a nested list inside a hidden `li` cannot leak).
  - R7 names the final URL after redirects (the page the content came
    from), matching the `url` field of the `webfetch` result.
  - R9 lowercases the style value (CSS keywords are case-insensitive) in
    addition to the brief's whitespace-insensitivity, and counts nested
    same-name tags so a nested `div` cannot end a hidden `div` early.
- Rule names are stable strings: they are what the Call Log records for
  later calibration (brief decision 7), so renaming one is a visible change.
