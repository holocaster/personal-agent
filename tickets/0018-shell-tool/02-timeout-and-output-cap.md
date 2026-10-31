# 02: `shell` timeout and bounded output cap

**What to build:** A `shell` command can no longer hang a turn or flood the
Conversation. A command running past `ROUTER_SHELL_TIMEOUT_SECONDS` (default
30) has its whole process group sent SIGTERM, then SIGKILL if still alive
after a short fixed grace period, and the call becomes a Tool error. stdout
and stderr are each capped at `ROUTER_SHELL_MAX_OUTPUT_BYTES` (default: the
effective `ROUTER_MAX_READ_BYTES`), with output past the cap discarded as it
arrives and `[...truncated]` appended to a capped stream.

**Blocked by:** 01 (Opt-in `shell` Mutating Tool behind command Tool
Confirmation) - extends its execution step and configuration.

**Spec:** `docs/specs/0018-shell-tool.md` (Implementation Decisions: Timeout,
Output cap, Configuration errors, README; Testing Decisions; Further Notes on
the `[...truncated]` marker and the effective read-limit default).
**ADRs:** none.

- [x] `ROUTER_SHELL_TIMEOUT_SECONDS`: unset or empty means 30, otherwise a
  positive whole number of seconds. `ROUTER_SHELL_MAX_OUTPUT_BYTES`: unset or
  empty means the effective `ROUTER_MAX_READ_BYTES`, otherwise a positive
  whole-byte count parsed like the existing byte limits. Invalid values make
  `main` print `Configuration error: ...` and exit 1 only when shell is
  enabled; when disabled both are ignored.
- [x] On timeout the process group gets SIGTERM, then SIGKILL after a fixed
  grace period of a few seconds if still alive; a background child started
  by the command does not survive. The result is a Tool error
  `command timed out after N seconds`; no partial output is returned.
- [x] stdout and stderr are drained concurrently and capped independently:
  the first cap bytes are kept, the rest is read and discarded (never
  buffered whole), so a command like `yes` cannot exhaust memory before the
  timeout. A capped stream ends with the literal `[...truncated]` after
  UTF-8 decoding; an uncapped one has no marker. `read_file` is unchanged.
- [x] Timed-out calls produce the existing Tool execution Call Log entry and
  `tool>` line.
- [x] README `shell` subsection documents both settings, SIGTERM-then-SIGKILL,
  and the truncation marker.
- [x] Tests at the `execute_batch` and `main` seams (short timeouts, one or
  two seconds) cover the above. Full offline suite passes.
