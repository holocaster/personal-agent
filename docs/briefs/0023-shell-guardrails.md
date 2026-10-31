# 0023 — shell guardrails

## Goal

Make the one gate in front of `shell`, `write`, and `edit` (Tool Confirmation) harder to wave through at the moments it matters most: when the command is obviously destructive, and when web content may have steered the model. Follow-up requested by the user during feature 0022, after `webfetch` brought third-party content into the Conversation.

## Scope

### Dangerous Command and Strong Confirmation (`shell` only)

- A fixed rule set in code flags a command string as a Dangerous Command:
  - recursive `rm` targeting `/`, `~`, `$HOME`, a bare `*`, `..`, or an absolute path outside the Workspace Root;
  - `git reset --hard`, `git clean -f…`, `git push --force`/`-f`, `git checkout -- .`;
  - `mkfs`, `dd … of=`, redirection to a block device (`/dev/sd*`, `/dev/nvme*`, …);
  - recursive `chmod`/`chown` on `/` or `~`;
  - the classic fork bomb;
  - `sudo`;
  - piping or evaluating data into a shell or interpreter: `| sh`, `| bash`, `| zsh`, `| python`/`python3`, `| perl`, `| node`, `eval`, `bash -c "$(…)"`/`sh -c "$(…)"`, `source <(…)`/`. <(…)`.
- A Dangerous Command gets Strong Confirmation: the matched rules are shown (red when colored) and only the exact word `yes` (trimmed, case-insensitive) approves; `y` and anything else reject. Piped input follows the same rule; EOF rejects.
- Nothing is blocked outright: the user can always approve by typing `yes`.
- The Call Log's Tool execution entry for a flagged command records which rules matched.
- Rules are not configurable (no env var).

### Fetched-Content Warning (`shell`, `write`, `edit`)

- Once a `webfetch` succeeds in a turn, every later Tool Confirmation for `shell`, `write`, or `edit` in that same turn shows a warning line naming the fetched URL(s) and asking for careful review. Approval rules do not change (a normal command still takes `y`).
- Scope is the turn: a new user task, or a Continuation Turn, starts without the warning.

### Hidden HTML (`webfetch`)

- HTML conversion drops the content of elements carrying the `hidden` attribute, `aria-hidden="true"`, or an inline `style` containing `display:none` or `visibility:hidden` (whitespace-insensitive), the same way `script`/`style` content is dropped.

### Docs

- `README.md` covers Dangerous Command rules, Strong Confirmation, the Fetched-Content Warning, and hidden-element dropping.

## Out of scope

- Any sandbox (`bwrap` was considered and deferred by the user).
- Blocking commands outright, or an allowlist / auto-approval of safe commands.
- Configurable rules.
- Parsing shell syntax fully; the rules are pattern matches on the command string, and obfuscation beyond the listed interpreter-pipe forms is not detected.
- Treating files read via `read_file` as external content for the warning.
- Hidden elements styled through CSS classes or external stylesheets.

## Settled decisions

1. **Threat model is both accident and manipulation**, but without a sandbox only accident gets real coverage; manipulation relies on the user reading the confirmation, which the Fetched-Content Warning and the interpreter-pipe rule support.
2. **No sandbox for now** (user decision), even though `bwrap` works unprivileged on the user's machine.
3. **Escalate, never block**: a hard block creates false positives with no real gain, since any denylist is trivially bypassed; typing `yes` costs little and breaks the reflexive `y`.
4. **Destructive Git is in the list** because, without a sandbox, Git is the undo mechanism; losing it is the worst accident here.
5. **Interpreter pipes are in the list**: they are the common obfuscation shape (`curl … | sh`, `base64 -d | sh`); a false positive only costs typing `yes`.
6. **Fixed rules, no configuration**: configuration mostly serves to switch the protection off.
7. **Matched rules are logged** for audit and to calibrate the list later.
8. **Warning scope is the turn**, since that is where fetched content and the model's next actions meet.
9. **Hidden-element dropping** covers the common injection trick cheaply; class-based hiding needs CSS and is out of scope.

## Open questions

None — confirmed by the user on 2026-09-25.

## Known issues

- Obfuscated commands that match no rule (e.g. `r''m -rf ~`, variables, `find / -delete`) are not flagged; accepted without a sandbox.
