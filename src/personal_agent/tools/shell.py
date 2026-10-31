import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass

from personal_agent.tools import workspace
from personal_agent.tools.builtins import ToolExecutionError
from personal_agent.tools.dangerous_command import matched_rules
from personal_agent.tools.workspace import TRUNCATION_MARKER, parse_positive_int

DEFAULT_SHELL_TIMEOUT_SECONDS = 30
# A few seconds, not configurable (spec: Timeout) - long enough for a
# SIGTERM-catching process to clean up, short enough not to stall the REPL.
KILL_GRACE_SECONDS = 2
# Shared deadline for both post-kill drain-thread joins together, not 2s
# each - bounds the wait for a process that escaped the group (e.g. `setsid`)
# and still holds the output pipes open, since there is no sandbox to
# reclaim them.
DRAIN_JOIN_TIMEOUT_SECONDS = 2
_READ_CHUNK_SIZE = 65536


@dataclass(frozen=True)
class PreparedShellCall:
    """Everything shell's apply step needs, computed by prepare without
    running anything: the Tool Confirmation label (the Workspace Root) and
    preview (the exact command), the resolved shell binary, the command
    string itself, and the Dangerous Command rules matched against it (R2;
    empty when none matched)."""

    display_path: str
    preview: str
    shell: str
    command: str
    dangerous_rules: tuple[str, ...]
    background: bool = False


@dataclass(frozen=True)
class ShellConfig:
    timeout_seconds: int
    max_output_bytes: int


_shell_config: ShellConfig | None = None
_process_observer = None


def observe_processes(callback) -> None:
    global _process_observer
    _process_observer = callback


def process_started(process) -> None:
    if _process_observer is not None:
        try:
            _process_observer("started", process.pid)
        except BaseException:
            kill_process_groups([(process, process.pid)])
            raise


def configure_shell(timeout_value, max_output_bytes_value, default_max_output_bytes: int) -> ShellConfig:
    """Startup-only shell configuration (ticket 0018-02), parallel to
    workspace.configure_workspace: validates PA_SHELL_TIMEOUT_SECONDS and
    PA_SHELL_MAX_OUTPUT_BYTES eagerly, so `main` can report a
    Configuration error before the REPL starts. `default_max_output_bytes`
    is the caller's already-resolved effective PA_MAX_READ_BYTES."""
    timeout_seconds = parse_positive_int(
        timeout_value, DEFAULT_SHELL_TIMEOUT_SECONDS, "PA_SHELL_TIMEOUT_SECONDS", unit="whole number of seconds"
    )
    max_output_bytes = parse_positive_int(
        max_output_bytes_value, default_max_output_bytes, "PA_SHELL_MAX_OUTPUT_BYTES"
    )
    global _shell_config
    _shell_config = ShellConfig(timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes)
    return _shell_config


def reset_shell_config() -> None:
    """Test-only: undo configure_shell(), restoring the unconfigured default."""
    global _shell_config
    _shell_config = None


def effective_shell_config() -> ShellConfig:
    """The active ShellConfig: configure_shell()'s value when main called it,
    otherwise the spec defaults computed from the configured workspace (so
    execute_batch works in tests that enable `shell` without configuring it
    separately)."""
    if _shell_config is not None:
        return _shell_config
    return ShellConfig(
        timeout_seconds=DEFAULT_SHELL_TIMEOUT_SECONDS,
        max_output_bytes=workspace.configured_workspace().max_read_bytes,
    )


def _resolve_shell() -> str:
    for name in ("bash", "sh"):
        found = shutil.which(name)
        if found is not None:
            return found
    raise ToolExecutionError("neither bash nor sh is available on PATH")


def prepare_shell(arguments: dict) -> PreparedShellCall:
    """`shell`'s prepare step (two-phase Mutating Tool): resolves the shell
    binary and the Dangerous Command rules (R2) before Tool Confirmation and
    runs nothing."""
    workspace_root = workspace.configured_workspace().root
    shell_path = _resolve_shell()
    command = arguments["command"]
    background = arguments.get("background", False)
    return PreparedShellCall(
        display_path=str(workspace_root),
        preview=f"[background job] {command}" if background else command,
        shell=shell_path,
        command=command,
        dangerous_rules=matched_rules(command, workspace_root),
        background=background,
    )


def _drain_capped(stream, cap: int, sink: dict) -> None:
    """Read `stream` to EOF, keeping only the first `cap` bytes and
    discarding the rest as it arrives (ticket 0018-02 Output cap) so a
    command like `yes` cannot buffer unbounded output in memory."""
    kept = bytearray()
    truncated = False
    while True:
        chunk = stream.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        remaining = cap - len(kept)
        if remaining > 0:
            kept.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
    sink["data"] = bytes(kept)
    sink["truncated"] = truncated


def _decode_capped(sink: dict) -> str:
    text = sink["data"].decode("utf-8", errors="replace")
    return text + TRUNCATION_MARKER if sink["truncated"] else text


def _kill_process_group(process: subprocess.Popen, pgid: int) -> None:
    kill_process_groups([(process, pgid)])


def kill_process_groups(groups: list[tuple[subprocess.Popen | None, int]]) -> None:
    """SIGTERM every process group first, then poll the groups themselves
    (not just the leaders) for one shared KILL_GRACE_SECONDS before
    SIGKILLing whatever remains. Polling the group - rather than gating
    escalation on the leader's exit - kills a TERM-immune group member (e.g.
    `trap '' TERM`) even after the leader is long gone. Each `pgid` is the
    leader's own pid, captured right after start (start_new_session=True
    makes the leader its own process group), since the leader may already be
    reaped by the time this runs. An already-empty group must not raise and
    must not wait out the grace period."""
    live = []
    for process, pgid in groups:
        try:
            os.killpg(pgid, signal.SIGTERM)
            live.append((process, pgid))
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + KILL_GRACE_SECONDS
    while live and time.monotonic() < deadline:
        remaining = []
        for process, pgid in live:
            # Reap the leader as soon as it exits: otherwise its own unreaped
            # zombie keeps killpg(pgid, 0) reporting the group as alive.
            if process is not None:
                process.poll()
            try:
                os.killpg(pgid, 0)
                remaining.append((process, pgid))
            except ProcessLookupError:
                pass
        live = remaining
        if live:
            time.sleep(0.05)
    for _process, pgid in live:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    for process, _pgid in groups:
        if process is not None:
            process.wait()
        if _process_observer is not None:
            _process_observer("finished", _pgid)


def shell_environment() -> dict:
    return {key: value for key, value in os.environ.items() if key != "TAVILY_API_KEY"}


def apply_shell(prepared: PreparedShellCall) -> dict:
    """`shell`'s apply step: run the command via `[<shell>, "-c", command]`,
    cwd the Workspace Root, no stdin, environment inherited except the Tavily key, in
    its own process group/session, stdout/stderr drained concurrently and
    capped. Any exit code is a normal result; a failure to start the
    process or a timeout is a Tool error. The process group is always
    killed before returning, on every path, so a backgrounded child never
    survives the call; a process that escaped the group and still holds a
    pipe open cannot be signalled, so that case is instead a bounded Tool
    error after `DRAIN_JOIN_TIMEOUT_SECONDS`."""
    workspace_root = workspace.configured_workspace().root
    config = effective_shell_config()
    try:
        process = subprocess.Popen(
            [prepared.shell, "-c", prepared.command],
            cwd=workspace_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=shell_environment(),
        )
    except OSError as exc:
        raise ToolExecutionError(f"failed to start command: {exc}") from exc
    pgid = process.pid
    process_started(process)

    stdout_sink: dict = {}
    stderr_sink: dict = {}
    stdout_thread = threading.Thread(
        target=_drain_capped, args=(process.stdout, config.max_output_bytes, stdout_sink), daemon=True
    )
    stderr_thread = threading.Thread(
        target=_drain_capped, args=(process.stderr, config.max_output_bytes, stderr_sink), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()

    deadline = time.monotonic() + config.timeout_seconds
    try:
        try:
            process.wait(timeout=config.timeout_seconds)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True

        if not timed_out:
            # The leader exiting is not enough: a backgrounded child that
            # inherits stdout/stderr (e.g. `server &`) keeps the pipes open
            # after bash returns, so bound the drains by the same deadline
            # rather than joining them unconditionally.
            stdout_thread.join(timeout=max(deadline - time.monotonic(), 0))
            stderr_thread.join(timeout=max(deadline - time.monotonic(), 0))
            if stdout_thread.is_alive() or stderr_thread.is_alive():
                timed_out = True

    except BaseException:
        _kill_process_group(process, pgid)
        drain_deadline = time.monotonic() + DRAIN_JOIN_TIMEOUT_SECONDS
        stdout_thread.join(timeout=max(drain_deadline - time.monotonic(), 0))
        stderr_thread.join(timeout=max(drain_deadline - time.monotonic(), 0))
        if not stdout_thread.is_alive():
            process.stdout.close()
        if not stderr_thread.is_alive():
            process.stderr.close()
        raise

    # Kill the group on every path, not only on timeout, so a backgrounded
    # child never survives the call. Tolerates an already-empty group (the
    # common case) with no added latency.
    _kill_process_group(process, pgid)

    # A process that escaped the group (e.g. `setsid`) and still holds a
    # pipe open cannot be signalled (no sandbox), so bound the wait instead
    # of joining unconditionally. The threads are daemon threads and their
    # pipes are left open below so an abandoned drain neither blocks process
    # exit nor blocks this call on a close().
    drain_deadline = time.monotonic() + DRAIN_JOIN_TIMEOUT_SECONDS
    stdout_thread.join(timeout=max(drain_deadline - time.monotonic(), 0))
    stderr_thread.join(timeout=max(drain_deadline - time.monotonic(), 0))
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        raise ToolExecutionError(
            f"command timed out after {config.timeout_seconds} seconds; "
            "a process that left the process group may still be running"
        )

    process.stdout.close()
    process.stderr.close()

    if timed_out:
        raise ToolExecutionError(f"command timed out after {config.timeout_seconds} seconds; "
                                 "an inner timeout cannot extend this tool limit. For long commands, "
                                 "use shell with background: true, then job_status to collect the result")

    return {
        "stdout": _decode_capped(stdout_sink),
        "stderr": _decode_capped(stderr_sink),
        "exit_code": process.returncode,
    }
