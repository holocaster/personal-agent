import json
import os
import random
import re
import stat
import string
import sys
from hashlib import sha256
from threading import Lock
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
from contextlib import contextmanager

from personal_agent.chatgpt_auth import valid_reference
from personal_agent.providers.registry import PROVIDERS
from personal_agent.routing.runtime_config import RuntimeConfig
from personal_agent.routing.continuation import build as build_continuation, validate as validate_continuation
from personal_agent.tools import todo as todo_module

_workspace_root: str | None = None
_log_home: Path | None = None
_project_id: str | None = None

_SESSION_SUFFIX_ALPHABET = string.ascii_lowercase + string.digits
_SESSION_SUFFIX_LENGTH = 6
SESSION_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z-[a-z0-9]{6}$")
COMPRESS_TASK = "/compress"
LOG_VERSION = 3

_current_session_id: str | None = None
_current_run_id: str | None = None
_total_cost: float = 0.0
_write_lock = Lock()
_detail_file = None
_attempt_observer = None
_delegated_attempts: set[tuple[str, str]] = set()
PLAN_FIELDS = ("prompt_tokens", "completion_tokens", "cached_tokens", "reasoning_tokens")


def _empty_plan_usage() -> dict:
    return {"attempts": 0, **{name: {"total": 0, "known": 0, "missing": 0, "invalid": 0} for name in PLAN_FIELDS}}


def _empty_api_usage() -> dict:
    return dict.fromkeys(("attempts", "reported", "estimated", "unknown"), 0)


_plan_usage = _empty_plan_usage()
_api_usage = _empty_api_usage()

SESSION_END_ERROR = "error"
SESSION_END_EOF = "eof"
SESSION_END_INTERRUPT = "interrupt"
SESSION_END_EXIT_COMMAND = "exit_command"
SESSION_END_FORK = "fork"


class ResumeError(Exception):
    """Raised when a Resume cannot proceed. Its message is what the user sees."""


class AuditError(Exception):
    """An enabled detailed audit could not be completed; stop this Run."""


class PersistenceError(Exception):
    pass


class Turn(tuple):
    replay = None

    def __new__(cls, messages, replay=None):
        turn = super().__new__(cls, messages)
        turn.replay = replay
        return turn


def _access(config: RuntimeConfig) -> dict:
    if config.readiness_error or not config.provider:
        return {}
    if config.provider != "chatgpt":
        return {"access_method": "api_key"}
    binding = config.chatgpt_binding
    return {"access_method": "chatgpt_plan", **({"registration_ref": binding.registration} if binding else {})}


def _valid_access(entry: dict, required: bool) -> bool:
    if entry.get("provider") != "chatgpt":
        return entry.get("access_method", "api_key") == "api_key" and "registration_ref" not in entry
    reference = entry.get("registration_ref")
    return entry.get("access_method") == "chatgpt_plan" and (reference is None and not required or valid_reference(reference))


def project_id(workspace_root: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9._-]+", "_", workspace_root).strip("_")[:96].strip("_") or "root"
    return f"{readable}--{sha256(workspace_root.encode('utf-8')).hexdigest()[:12]}"


def initialize_storage(workspace_root: str | os.PathLike | None = None) -> str:
    global _workspace_root, _log_home, _project_id
    root = str(Path.cwd().resolve() if workspace_root is None else Path(workspace_root).resolve())
    if _workspace_root != root or _log_home is None:
        _workspace_root = root
        _project_id = project_id(root)
        _log_home = Path.home().resolve()
    return root


def storage_identity() -> dict:
    if _workspace_root is None:
        initialize_storage()
    return {"workspace_root": _workspace_root, "project_id": _project_id}


@contextmanager
def storage_directory(project: str | None = None, *, create: bool = False, private: bool = False):
    storage_identity()
    if project is not None and not re.fullmatch(r"[A-Za-z0-9._-]+--[0-9a-f]{12}", project):
        raise OSError("invalid project folder")
    fd = os.open(_log_home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in (".personal_agent", "logs", *((project,) if project is not None else ())):
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            if create:
                info = os.fstat(fd)
                if stat.S_IMODE(info.st_mode) != 0o700:
                    if info.st_uid != os.getuid():
                        raise OSError("unsafe storage directory permissions or owner")
                    os.fchmod(fd, 0o700)
            if private:
                info = os.fstat(fd)
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise OSError("unsafe storage directory permissions or owner")
        yield fd
    finally:
        os.close(fd)


def open_session_file(session_id: str, mode: str = "rb", *, project: str | None = None, audit: bool = False):
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise OSError(f"invalid Session Id: {session_id}")
    identity = storage_identity()
    project = project or identity["project_id"]
    suffix = ".audit.jsonl" if audit else ".jsonl"
    writing = mode in ("a", "a+", "r+b")
    flags = (os.O_RDWR if writing else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK
    if mode.startswith("a"):
        flags |= os.O_APPEND | os.O_CREAT
    with storage_directory(project, create=writing) as directory:
        filename = f"pa_log-{session_id}{suffix}"
        try:
            info = os.stat(filename, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            if not mode.startswith("a"):
                raise
        else:
            if not stat.S_ISREG(info.st_mode):
                raise OSError("Session file must be a regular file")
        fd = os.open(filename, flags, 0o600, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("Session file must be a regular file")
        if audit and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise OSError("unsafe detailed audit file; use an owner-only regular file")
        return open(fd, mode, **({"encoding": "utf-8"} if "b" not in mode else {}))
    except BaseException:
        os.close(fd)
        raise


def validate_identity(entry: dict, session_id: str, project: str | None = None) -> None:
    identity = storage_identity()
    root = entry.get("workspace_root")
    expected_project = project or identity["project_id"]
    if (entry.get("session_id") != session_id or not isinstance(root, str)
            or not root.startswith("/") or root.startswith("//") or str(Path(root)) != root
            or ".." in Path(root).parts or project_id(root) != expected_project
            or entry.get("project_id") != expected_project
            or (project is None and root != identity["workspace_root"])
            or not isinstance(entry.get("run_id"), str) or not re.fullmatch(r"[0-9a-f]{32}", entry["run_id"])):
        raise ResumeError(f"session {session_id} has invalid project or Run identity")
    if "session_kind" in entry:
        _validate_session_origin([entry], session_id)


def _mint_session_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "".join(random.choices(_SESSION_SUFFIX_ALPHABET, k=_SESSION_SUFFIX_LENGTH))
    return f"{timestamp}-{suffix}"


def mint_session_id() -> str:
    return _mint_session_id()


def _validate_project_storage() -> None:
    from personal_agent import session_logs
    try:
        project = storage_identity()["project_id"]
        budget = {"bytes": 0, "records": 0}
        for candidate in session_logs.candidates(project):
            if candidate["warning"]:
                raise OSError(candidate["warning"])
            stream = session_logs.records(project, candidate["session_id"], budget)
            try:
                row = next(stream, None)
                if row and row["entry"] and row["entry"].get("type") == "session_start":
                    validate_identity(row["entry"], candidate["session_id"])
            finally:
                stream.close()
    except ValueError as exc:
        raise PersistenceError(f"cannot validate project storage: {exc}") from exc


def _session_start_entry(session_id: str, run_id: str, config: RuntimeConfig) -> dict:
    return {
        "timestamp": _now_iso(),
        "session_id": session_id,
        "type": "session_start",
        "log_version": LOG_VERSION,
        **storage_identity(),
        "run_id": run_id,
        "provider": config.provider if not config.readiness_error else None,
        "model": config.model if not config.readiness_error else None,
        **({"route_error": config.readiness_error} if config.readiness_error else {}),
        **_access(config),
    }


def start_session(config: RuntimeConfig, *, subagent: dict | None = None, session_id: str | None = None) -> str:
    """Mint a fresh Session Id, reset spend tracking, and write session_start."""
    global _current_session_id, _current_run_id, _total_cost, _plan_usage, _api_usage
    _validate_project_storage()
    _current_session_id = session_id or _mint_session_id()
    _current_run_id = uuid4().hex
    _total_cost = 0.0
    _delegated_attempts.clear()
    _plan_usage = _empty_plan_usage()
    _api_usage = _empty_api_usage()
    entry = _session_start_entry(_current_session_id, _current_run_id, config)
    if subagent is not None:
        entry.update(session_kind="subagent", **subagent)
    _write_line(entry, restore_on_failure=True)
    return _current_session_id


def fork_session(config: RuntimeConfig, turns, summary: str | None, todo_baseline: list[dict],
                 destination: str | None = None) -> str:
    """End the current Session's Run with reason fork and continue in a new
    self-contained child Session whose Call Log copies the Conversation
    (ADR-0013). Any failure is a PersistenceError naming the parent."""
    global _current_session_id, _current_run_id, _total_cost, _plan_usage, _api_usage
    parent = current_session_id()
    child = _mint_session_id()
    run_id = uuid4().hex
    try:
        _write_line({"timestamp": _now_iso(), "session_id": parent, "type": "session_end",
                     "reason": SESSION_END_FORK, "total_cost": _total_cost, "child_session_id": child})
        _validate_project_storage()
        _write_line({**_session_start_entry(child, run_id, config), "parent_session_id": parent},
                    restore_on_failure=True, durable=True)
        _write_line({"timestamp": _now_iso(), "session_id": child, "type": "conversation_forked",
                     "parent_session_id": parent, "turns": [list(turn) for turn in turns], "summary": summary,
                     "todo_baseline": list(todo_baseline), "replays": [getattr(turn, "replay", None) for turn in turns],
                     "destination": destination}, restore_on_failure=True, durable=True)
    except (OSError, ValueError, PersistenceError) as exc:
        detail = str(exc)
        try:
            with storage_directory(storage_identity()["project_id"]) as directory:
                os.unlink(f"pa_log-{child}.jsonl", dir_fd=directory)
        except FileNotFoundError:
            pass
        except OSError as cleanup:
            detail += f"; could not remove child Session {child}: {cleanup}"
        raise PersistenceError(f"cannot create the forked Session from parent Session {parent}: {detail}; "
                               f"resume the parent with --resume {parent}") from exc
    _current_session_id = child
    _current_run_id = run_id
    _total_cost = 0.0
    _plan_usage = _empty_plan_usage()
    _api_usage = _empty_api_usage()
    return child


def resume_session(session_id: str, config: RuntimeConfig) -> None:
    """Continue an existing Session for a new Run: keep its Session Id, reset
    per-Run spend to zero, and write session_resumed with the current route."""
    global _current_session_id, _current_run_id, _total_cost, _plan_usage, _api_usage
    _read_entries(session_id)
    _current_session_id = session_id
    _current_run_id = uuid4().hex
    _total_cost = 0.0
    _delegated_attempts.clear()
    _plan_usage = _empty_plan_usage()
    _api_usage = _empty_api_usage()
    _write_line(
        {
            "timestamp": _now_iso(),
            "session_id": _current_session_id,
            "type": "session_resumed",
            "log_version": LOG_VERSION,
            **storage_identity(),
            "run_id": _current_run_id,
            "provider": config.provider if not config.readiness_error else None,
            "model": config.model if not config.readiness_error else None,
            **({"route_error": config.readiness_error} if config.readiness_error else {}),
            **_access(config),
        }
    )


def current_session_id() -> str:
    """Return the current Session Id, lazily minting one if no Session was started."""
    global _current_session_id
    if _current_session_id is None:
        _current_session_id = _mint_session_id()
    return _current_session_id


def active_session_id() -> str | None:
    return _current_session_id


def active_run_id() -> str | None:
    return _current_run_id


def session_log_path(session_id: str | None = None) -> str:
    """Resolve the Call Log file path for the current or a given Session Id."""
    sid = session_id if session_id is not None else current_session_id()
    if not SESSION_ID_PATTERN.fullmatch(sid):
        raise ResumeError(f"unknown session: {sid}")
    identity = storage_identity()
    return str(_log_home / ".personal_agent" / "logs" / identity["project_id"] / f"pa_log-{sid}.jsonl")


def total_cost() -> float:
    """Return this Session's running total of Attempt costs (R12) - the same
    number end_session writes as total_cost."""
    return _total_cost


def plan_usage() -> dict:
    return {key: dict(value) if isinstance(value, dict) else value for key, value in _plan_usage.items()}


def api_usage() -> dict:
    return dict(_api_usage)


def _observe_api(cost, estimated) -> None:
    _api_usage["attempts"] += 1
    _api_usage["unknown" if not _valid_cost(cost) else "estimated" if estimated is True else "reported"] += 1


def _observe_plan(entry: dict) -> None:
    invalid = entry.get("invalid_usage") if isinstance(entry.get("invalid_usage"), list) else []
    _plan_usage["attempts"] += 1
    for name in PLAN_FIELDS:
        value, metric = entry.get(name), _plan_usage[name]
        if name in invalid or value is None and "usage" in invalid or value is not None and not (type(value) is int and value >= 0):
            metric["invalid"] += 1
        elif value is None:
            metric["missing"] += 1
        else:
            metric["known"] += 1
            metric["total"] += value


def _valid_cost(value) -> bool:
    return type(value) in (int, float) and 0 <= value <= sys.float_info.max


def end_session(reason: str) -> None:
    """Write session_end for the current Session. Leaves the Session Id readable."""
    _write_line(
        {
            "timestamp": _now_iso(),
            "session_id": current_session_id(),
            "type": "session_end",
            "reason": reason,
            "total_cost": _total_cost,
        }
    )


def reset_session() -> None:
    """Clear the in-process Session state, so the next call mints a fresh Session Id."""
    global _current_session_id, _current_run_id, _total_cost, _workspace_root, _log_home, _project_id, _plan_usage, _api_usage
    _workspace_root = _log_home = _project_id = None
    _current_session_id = None
    _current_run_id = None
    _total_cost = 0.0
    _delegated_attempts.clear()
    _plan_usage = _empty_plan_usage()
    _api_usage = _empty_api_usage()
    close_detail()


def resolve_resume_session(session: str) -> str:
    """Resolve a --resume value to a Session Id: "last" picks the most recent
    Session's Call Log; anything else must have the Session Id shape, so an
    arbitrary value is never used to build a path. Raises ResumeError."""
    if session == "last":
        return _find_last_session_id()
    if not SESSION_ID_PATTERN.fullmatch(session):
        raise ResumeError(f"unknown session: {session}")
    return session


def _find_last_session_id() -> str:
    from personal_agent import session_logs
    try:
        return session_logs.last_session(storage_identity()["project_id"])
    except (OSError, ValueError) as exc:
        raise ResumeError(f"cannot select last Session: {exc}") from exc


def load_conversation(session_id: str) -> tuple[tuple[tuple[dict, ...], ...], str | None, list[dict], int]:
    """Rebuild (turns, summary, todo_baseline, submissions) for a Resume by
    replaying the Call Log in order: conversation_cleared empties the
    Conversation, an 'ok' Turn End appends its turn, turn_undone removes the
    last remaining turn, and conversation_compressed sets the summary, derives
    the Todo baseline from the dropped turns and keeps the two most recent.
    Raises ResumeError for an unreadable, malformed or non-current Call Log."""
    turns: list[tuple[dict, ...]] = []
    summary: str | None = None
    todo_baseline: list[dict] = []
    submissions = 0
    for entry in _read_entries(session_id):
        entry_type = entry.get("type")
        if entry_type == "conversation_forked":
            turns = [_turn(session_id, turn, replay)
                     for turn, replay in zip(entry["turns"], entry.get("replays") or [None] * len(entry["turns"]))]
            summary = entry["summary"]
            todo_baseline = list(entry["todo_baseline"])
        elif entry_type == "routed_task_submitted":
            submissions = entry["ordinal"]
        elif entry_type == "conversation_cleared":
            turns = []
            summary = None
            todo_baseline = []
        elif entry_type == "turn_end" and entry.get("status") == "ok":
            messages = entry.get("messages")
            if not isinstance(messages, list):
                raise ResumeError(f"session {session_id} has an invalid Call Log line")
            turns.append(_turn(session_id, messages, entry.get("replay")))
        elif entry_type == "turn_undone":
            if turns:
                turns.pop()
        elif entry_type == "conversation_compressed":
            summary = entry.get("summary")
            if not isinstance(summary, str):
                raise ResumeError(f"session {session_id} has an invalid Call Log line")
            todo_baseline = todo_module.current_list(turns[:-2], todo_baseline)
            turns = turns[-2:]
    return tuple(turns), summary, todo_baseline, submissions


def _turn(session_id: str, messages: list, replay) -> Turn:
    if replay is not None:
        from personal_agent.providers import chatgpt
        try:
            chatgpt.validate_turn_replay(replay, messages)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ResumeError(f"session {session_id} has an invalid Responses replay") from exc
    return Turn(messages, replay)


def last_destination(session_id: str | None = None) -> str | None:
    destination = None
    for entry in _read_entries(session_id or current_session_id()):
        if entry.get("type") == "conversation_forked":
            destination = entry.get("destination")
        elif entry.get("type") == "attempt" and entry.get("access_method") == "chatgpt_plan":
            destination = entry["registration_ref"]
    return destination


def _valid_route(entry: dict) -> bool:
    return (isinstance(entry.get("provider"), str) and entry["provider"] in PROVIDERS
            and isinstance(entry.get("model"), str) and bool(entry["model"].strip()))


def _read_entries(session_id: str) -> list[dict]:
    try:
        with open_session_file(session_id) as log_file:
            data = log_file.read().decode("utf-8")
            if data and not data.endswith("\n"):
                raise ResumeError(f"session {session_id} has an invalid Call Log line: incomplete tail")
            raw_lines = [line for line in data.splitlines() if line]
    except (OSError, UnicodeError) as exc:
        raise ResumeError(f"cannot read session {session_id}: {exc}") from exc
    entries = []
    for line in raw_lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ResumeError(f"session {session_id} has an invalid Call Log line") from exc
        if not isinstance(parsed, dict):
            raise ResumeError(f"session {session_id} has an invalid Call Log line")
        entries.append(parsed)
    if not entries or entries[0].get("type") != "session_start" or entries[0].get("log_version") != LOG_VERSION:
        raise ResumeError(f"session {session_id} was not recorded with log_version {LOG_VERSION} and cannot be "
                          "resumed; its files were left unchanged")
    for entry in entries:
        if entry.get("session_id") != session_id:
            raise ResumeError(f"session {session_id} has invalid Session identity")
        if entry.get("type") in ("session_start", "session_resumed"):
            validate_identity(entry, session_id)
    _validate_session_origin(entries, session_id)
    executions = set()
    recovering = set()
    run_id = None
    submissions = 0
    for position, entry in enumerate(entries, 1):
        kind = entry.get("type")
        if kind in {"session_start", "session_resumed"}:
            if (entry.get("log_version") != LOG_VERSION or not (_valid_route(entry) and _valid_access(entry, False)
                        or entry.get("provider") is None and entry.get("model") is None
                        and isinstance(entry.get("route_error"), str) and bool(entry["route_error"])
                        and not entry.keys() & {"access_method", "registration_ref"})
                    or kind == "session_start" and position != 1):
                raise ResumeError(f"session {session_id} has invalid Run metadata")
            run_id = entry.get("run_id")
        elif kind in {"routed_task_submitted", "routed_task_retried"}:
            ordinal = entry.get("ordinal")
            submitted = kind == "routed_task_submitted"
            if (type(ordinal) is not int or not _valid_route(entry) or not _valid_access(entry, True)
                    or (ordinal != submissions + 1 if submitted else not 0 < ordinal <= submissions)
                    or submitted and (not isinstance(entry.get("task"), str) or not entry["task"].strip())):
                raise ResumeError(f"session {session_id} has an invalid task opening")
            submissions = max(submissions, ordinal)
            executions.add((run_id, position, ordinal))
        elif kind == "attempt" and "access_method" in entry and not _valid_access(entry, True):
            raise ResumeError(f"session {session_id} has an invalid Attempt access method")
        elif kind in {"file_recovery_started", "file_recovery_finished"}:
            reference = entry.get("execution")
            keys = {"timestamp", "session_id", "type", "execution", "ordinal"}
            if kind == "file_recovery_finished":
                keys.add("outcome")
            if (set(entry) != keys or not isinstance(reference, dict)
                    or set(reference) != {"run_id", "opening", "ordinal"}
                    or not isinstance(reference["run_id"], str)
                    or any(type(reference[key]) is not int or reference[key] <= 0 for key in ("opening", "ordinal"))
                    or reference["ordinal"] != entry["ordinal"]):
                raise ResumeError("invalid file recovery record")
            target = reference["run_id"], reference["opening"], reference["ordinal"]
            if target not in executions:
                raise ResumeError("file recovery references an unknown execution")
            if kind == "file_recovery_started":
                recovering.add(target)
            elif (target not in recovering or not isinstance(entry["outcome"], str)
                    or entry["outcome"] not in {"ok", "error"}):
                raise ResumeError("invalid file recovery completion")
            else:
                recovering.discard(target)
    return entries


_FORK_SEED_KEYS = {"timestamp", "session_id", "type", "parent_session_id", "turns", "summary", "todo_baseline"}


def _validate_session_origin(entries: list[dict], session_id: str) -> None:
    error = ResumeError(f"session {session_id} has an invalid fork record")
    start = entries[0]
    forked = [position for position, entry in enumerate(entries) if entry.get("type") == "conversation_forked"]
    if "session_kind" in start:
        execution = start.get("parent_execution")
        parent = start.get("parent_session_id")
        if (start["session_kind"] != "subagent" or forked
                or not isinstance(parent, str) or not SESSION_ID_PATTERN.fullmatch(parent) or parent == session_id
                or not isinstance(execution, dict) or set(execution) != {"run_id", "opening", "ordinal"}
                or not isinstance(execution["run_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", execution["run_id"])
                or any(type(execution[key]) is not int or execution[key] <= 0 for key in ("opening", "ordinal"))
                or not isinstance(start.get("parent_tool_call_id"), str) or not start["parent_tool_call_id"]
                or not isinstance(start.get("agent_name"), str)
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", start["agent_name"])
                or len(start["agent_name"]) > 64):
            raise ResumeError(f"session {session_id} has invalid Subagent metadata")
        return
    if "parent_session_id" not in start:
        if forked:
            raise error
        return
    parent = start["parent_session_id"]
    if (not isinstance(parent, str) or not SESSION_ID_PATTERN.fullmatch(parent) or parent == session_id
            or forked != [1]):
        raise error
    seed = entries[1]
    turns = seed.get("turns")
    baseline = seed.get("todo_baseline")
    replays = seed.get("replays", [None] * len(turns) if isinstance(turns, list) else None)
    destination = seed.get("destination")
    if (set(seed) - {"replays", "destination"} != _FORK_SEED_KEYS or seed["parent_session_id"] != parent
            or not isinstance(turns, list)
            or any(not isinstance(turn, list) or not turn or any(not isinstance(message, dict) for message in turn)
                   for turn in turns)
            or not (seed["summary"] is None or isinstance(seed["summary"], str))
            or not isinstance(baseline, list) or any(not isinstance(item, dict) for item in baseline)
            or not isinstance(replays, list) or len(replays) != len(turns)
            or destination is not None and not valid_reference(destination)):
        raise error


def submission_digest(task: str) -> str:
    return sha256(task.encode("utf-8")).hexdigest()


def load_pending_turn(session_id: str) -> tuple[int, dict, str] | None:
    pending = None
    pending_sources = set()
    submitted = None
    execution = None
    execution_key = None
    run_id = None
    ended = False
    route = None
    for position, entry in enumerate(_read_entries(session_id), 1):
        kind = entry.get("type")
        if kind in {"session_start", "session_resumed"}:
            run_id = entry.get("run_id")
        elif kind in {"routed_task_submitted", "routed_task_retried"}:
            execution = {"run_id": run_id, "opening": position, "ordinal": entry.get("ordinal")}
            execution_key = run_id, position, entry.get("ordinal")
            route = {"provider": entry["provider"], "model": entry["model"], "registration": entry.get("registration_ref")}
            if kind == "routed_task_retried" and pending is None:
                pending_sources.clear()
            ended = False
        if kind == "routed_task_submitted":
            submitted = entry
            pending = None
            pending_sources.clear()
        elif kind == "conversation_cleared":
            pending = None
            pending_sources.clear()
            ended = True
        elif kind == "turn_end":
            ended = True
            pending = None
            if "continuation" in entry:
                try:
                    state = validate_continuation(entry["continuation"])
                    ordinal = entry.get("ordinal")
                    digest = entry.get("task_digest")
                    if (entry.get("status") not in {"error", "interrupted"} or type(ordinal) is not int or ordinal <= 0
                            or submitted is None or ordinal != submitted.get("ordinal")
                            or not isinstance(submitted.get("task"), str)
                            or not isinstance(digest, str) or digest != submission_digest(submitted["task"])):
                        raise ValueError("invalid pending turn attribution")
                except ValueError as exc:
                    raise ResumeError(f"session {session_id} has {exc}") from exc
                pending = ordinal, state, digest
                pending_sources.add(execution_key)
            else:
                pending_sources.clear()
        elif kind == "file_recovery_started":
            target = entry["execution"]
            target_key = target["run_id"], target["opening"], target["ordinal"]
            if target == execution or target_key in pending_sources:
                if pending is not None:
                    ordinal, state, digest = pending
                    state = dict(state, messages=[{"role": "user", "content": state["task"]}],
                                 fetched_urls=[], replay=None)
                    pending = ordinal, state, digest
                    pending_sources = {execution_key}
                elif not ended and submitted is not None and route is not None:
                    task = submitted["task"]
                    state = build_continuation(task, route["provider"], route["model"], route["registration"])
                    pending = execution["ordinal"], validate_continuation(state), submission_digest(task)
                    pending_sources = {execution_key}
    return pending


def latest_execution(session_id: str | None = None) -> dict | None:
    run_id = None
    result = None
    for position, entry in enumerate(_read_entries(session_id or current_session_id()), 1):
        if entry.get("type") in {"session_start", "session_resumed"}:
            run_id = entry.get("run_id")
        elif entry.get("type") in {"routed_task_submitted", "routed_task_retried"}:
            result = {"run_id": run_id, "opening": position, "ordinal": entry["ordinal"]}
    return result


def execution_outcome(reference: dict, session_id: str | None = None) -> str:
    execution = None
    run_id = None
    outcome = "unknown"
    found = False
    for position, entry in enumerate(_read_entries(session_id or current_session_id()), 1):
        if entry.get("type") in {"session_start", "session_resumed"}:
            execution = None
            run_id = entry.get("run_id")
        elif entry.get("type") in {"routed_task_submitted", "routed_task_retried"}:
            execution = {"run_id": run_id, "opening": position, "ordinal": entry["ordinal"]}
            found = found or execution == reference
        elif entry.get("type") == "turn_end" and execution == reference:
            outcome = entry["status"]
    if not found:
        raise ResumeError("file recovery references an unknown execution")
    return outcome


def write_file_recovery(phase: str, execution: dict, outcome: str | None = None) -> None:
    entry = {"timestamp": _now_iso(), "session_id": current_session_id(),
             "type": f"file_recovery_{phase}", "execution": execution, "ordinal": execution["ordinal"]}
    if outcome is not None:
        entry["outcome"] = outcome
    try:
        _write_line(entry, restore_on_failure=True, durable=True)
    except (OSError, ValueError) as exc:
        raise PersistenceError(f"cannot persist file recovery {phase}: {exc}") from exc


def file_recovery_outcome(reference: dict, session_id: str | None = None) -> str | None:
    result = None
    for entry in _read_entries(session_id or current_session_id()):
        if entry.get("execution") == reference:
            if entry.get("type") == "file_recovery_started":
                result = None
            elif entry.get("type") == "file_recovery_finished":
                result = entry.get("outcome")
    return result


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _write_line(entry: dict, *, restore_on_failure: bool = False, durable: bool = False) -> None:
    with _write_lock:
        line = json.dumps(redact_data(entry, ())) + "\n"
        with open_session_file(entry["session_id"], "a") as log_file:
            offset = os.fstat(log_file.fileno()).st_size
            try:
                if log_file.write(line) != len(line):
                    raise OSError("short Call Log write")
                log_file.flush()
                if durable:
                    os.fsync(log_file.fileno())
            except BaseException:
                if restore_on_failure:
                    try:
                        log_file.seek(offset)
                        log_file.truncate(offset)
                        log_file.flush()
                        if durable:
                            os.fsync(log_file.fileno())
                    except BaseException as exc:
                        raise PersistenceError(f"could not restore Call Log after failed append: {exc}") from exc
                raise


def redact_value(value, secrets: tuple[str, ...]):
    from personal_agent.chatgpt_auth import KNOWN_SECRETS
    secrets = (*secrets, *KNOWN_SECRETS)
    if isinstance(value, str):
        for secret in sorted({key for key in secrets if key}, key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {key: redact_value(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item, secrets) for item in value)
    return value


def redact_data(value, secrets: tuple[str, ...]):
    if isinstance(value, dict):
        return {redact_value(key, secrets): redact_data(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_data(item, secrets) for item in value]
    return redact_value(value, secrets)


def detail_enabled() -> bool:
    return _detail_file is not None


def start_coverage(enabled: bool) -> None:
    _write_line({"timestamp": _now_iso(), "session_id": current_session_id(), "run_id": _current_run_id,
                 "type": "audit_coverage_start", "enabled": enabled})
    if enabled:
        open_detail()
        write_detail("run_start")


def end_coverage(enabled: bool) -> None:
    if enabled:
        write_detail("run_end")
        close_detail()
    _write_line({"timestamp": _now_iso(), "session_id": current_session_id(), "run_id": _current_run_id,
                 "type": "audit_coverage_end", "enabled": enabled})


def detail_path(session_id: str | None = None) -> str:
    path = session_log_path(session_id)
    root, ext = os.path.splitext(path)
    return (root if ext else path) + ".audit.jsonl"


def open_detail() -> None:
    global _detail_file
    path = detail_path()
    try:
        file = open_session_file(current_session_id(), "a+", audit=True)
        try:
            if os.fstat(file.fileno()).st_size:
                with os.fdopen(os.dup(file.fileno()), "rb") as existing:
                    existing.seek(-1, os.SEEK_END)
                    if existing.read(1) != b"\n":
                        raise AuditError(f"invalid detailed audit tail: {path}; repair it before enabling audit")
                    existing.seek(0)
                    for line in existing:
                        if not isinstance(json.loads(line), dict):
                            raise AuditError(f"invalid detailed audit tail: {path}; repair it before enabling audit")
            _detail_file = file
        except BaseException:
            file.close()
            raise
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"could not open detailed audit file {path}: {exc}") from exc


def close_detail() -> None:
    global _detail_file
    file = _detail_file
    _detail_file = None
    if file is not None:
        try:
            file.close()
        except OSError as exc:
            raise AuditError(f"could not close detailed audit: {exc}") from exc


def write_detail(kind: str, **fields) -> None:
    if _detail_file is None:
        return
    entry = {"timestamp": _now_iso(), "session_id": current_session_id(), "run_id": _current_run_id,
             "type": kind, **fields}
    try:
        line = json.dumps(redact_data(entry, ())) + "\n"
        if _detail_file.write(line) != len(line):
            raise AuditError(f"could not write detailed audit {kind}: short write")
        _detail_file.flush()
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise AuditError(f"could not write detailed audit {kind}: {exc}") from exc


def action_start(kind: str, name: str, identifier: str | None = None) -> str | None:
    if not detail_enabled():
        return None
    action_id = uuid4().hex
    write_detail("action_start", action_id=action_id, action=kind, name=name, identifier=identifier)
    return action_id


def action_end(action_id: str | None) -> None:
    if action_id is not None:
        write_detail("action_end", action_id=action_id)


def write_audit_event(*, secrets: tuple[str, ...] = (), action_id: str | None = None, **fields) -> None:
    controlled = {"action", "outcome", "decision", "setting", "provider", "dangerous_rules"}
    if fields.get("action") == "mode_toggle" or (fields.get("action") == "command" and fields.get("name") == "/mode"):
        controlled.update({"old", "new"})
    entry = {
        "timestamp": _now_iso(), "session_id": current_session_id(), "run_id": _current_run_id,
        "type": "audit_event",
        **({"action_id": action_id} if action_id else {}),
        **{key: value if key in controlled else redact_value(value, secrets) for key, value in fields.items()},
    }
    _write_line(entry)
    if detail_enabled():
        write_detail("local_outcome", event=entry)


def append_entry(
    *,
    task: str,
    provider: str,
    model: str,
    latency_ms: int,
    cost: float | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cached_tokens: int | None,
    cache_write_tokens: int | None,
    ok: bool,
    error: str | None,
    attempt: int,
    cost_estimated: bool,
    upstream_provider: str | None,
    answer: str | None,
    tool_calls: list[dict] | None,
    attempt_id: str | None = None,
    purpose: str | None = None,
    outcome: str | None = None,
    retry_kind: str | None = None,
    streamed: bool | None = None,
    first_text_latency_ms: int | None = None,
    access_method: str | None = None,
    registration_ref: str | None = None,
    reasoning_tokens: int | None = None,
    invalid_usage: list[str] | None = None,
    error_code: str | None = None,
    error_param: str | None = None,
    http_status: int | None = None,
    request_id: str | None = None,
) -> str:
    global _total_cost
    session_id = current_session_id()
    entry = {
        "timestamp": _now_iso(),
        "session_id": session_id,
        "type": "attempt",
        "task": task,
        "provider": provider,
        "model": model,
        "latency_ms": latency_ms,
        "cost": cost,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_tokens": cached_tokens,
        "cache_write_tokens": cache_write_tokens,
        "ok": ok,
        "error": error,
        "attempt": attempt,
        "cost_estimated": cost_estimated,
        "upstream_provider": upstream_provider,
        "answer": answer,
        "tool_calls": tool_calls,
    }
    if access_method == "api_key":
        entry["access_method"] = access_method
    elif access_method is not None:
        entry.update(access_method=access_method, registration_ref=registration_ref, reasoning_tokens=reasoning_tokens,
                     invalid_usage=invalid_usage, error_code=error_code, error_param=error_param,
                     http_status=http_status, request_id=request_id)
    if attempt_id is None and _attempt_observer is not None:
        attempt_id = uuid4().hex
    if attempt_id is not None:
        entry["attempt_id"] = attempt_id
    if purpose is not None:
        entry["purpose"] = purpose
    if outcome is not None:
        entry["outcome"] = outcome
    if retry_kind is not None:
        entry["retry_kind"] = retry_kind
    if streamed is not None:
        entry["streamed"] = streamed
        entry["first_text_latency_ms"] = first_text_latency_ms
    if _valid_cost(cost):
        _total_cost += cost
    _write_line(entry)
    if access_method == "chatgpt_plan" or provider == "chatgpt":
        _observe_plan(entry)
    else:
        _observe_api(cost, cost_estimated)
    if _attempt_observer is not None:
        _attempt_observer(entry)
    return entry["timestamp"]


def observe_attempts(callback) -> None:
    global _attempt_observer
    _attempt_observer = callback


def write_delegation(phase: str, **fields) -> None:
    try:
        _write_line({"timestamp": _now_iso(), "session_id": current_session_id(),
                     "type": f"delegation_{phase}", "run_id": active_run_id(), **fields},
                    durable=True, restore_on_failure=True)
    except (OSError, ValueError) as exc:
        raise PersistenceError(f"cannot persist delegated evidence: {exc}") from exc
    if detail_enabled():
        write_detail(f"delegation_{phase}", **fields)


def credit_delegated_attempt(child: str, receipt: dict, **attribution) -> bool:
    global _total_cost
    identifier = receipt.get("attempt_id")
    if (not isinstance(child, str) or not SESSION_ID_PATTERN.fullmatch(child)
            or not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier)):
        raise ValueError("invalid delegated Attempt identity")
    identity = child, identifier
    if identity in _delegated_attempts:
        return False
    plan = receipt.get("access_method") == "chatgpt_plan"
    if not plan and receipt.get("access_method", "api_key") != "api_key" or plan and not valid_reference(receipt.get("registration_ref")):
        raise ValueError("invalid delegated Attempt access")
    cost = receipt.get("cost")
    known = _valid_cost(cost) and not plan
    compact = {"attempt_id": identifier, "cost": cost if known else None,
               "cost_status": "known" if known else "missing" if cost is None else "invalid",
               "cost_estimated": receipt.get("cost_estimated") is True and not plan,
               "access_method": "chatgpt_plan" if plan else "api_key"}
    if plan:
        invalid = receipt.get("invalid_usage") if isinstance(receipt.get("invalid_usage"), list) else []
        invalid = [name for name in (*PLAN_FIELDS, "usage") if name in invalid
                   or name in PLAN_FIELDS and receipt.get(name) is not None
                   and not (type(receipt[name]) is int and receipt[name] >= 0)]
        compact.update(registration_ref=receipt["registration_ref"], invalid_usage=invalid or None,
                       **{name: None if name in invalid else receipt.get(name) for name in PLAN_FIELDS})
    write_delegation("receipt", child_session_id=child, **compact, **attribution)
    _delegated_attempts.add(identity)
    if known:
        _total_cost += cost
    if plan:
        _observe_plan(compact)
    else:
        _observe_api(compact["cost"], compact["cost_estimated"])
    return True


def log_upstream_provider(session_id: str, attempt_timestamp: str, upstream_provider: str | None,
                          error: str | None = None) -> None:
    _write_line({
        "timestamp": _now_iso(),
        "session_id": session_id,
        "type": "upstream_provider",
        "attempt_timestamp": attempt_timestamp,
        "upstream_provider": upstream_provider,
        "error": error,
    })


def write_turn_end(status: str, *, messages: tuple[dict, ...] | None = None, error: str | None = None,
                   continuation: dict | None = None, ordinal: int | None = None, task_digest: str | None = None,
                   replay: dict | None = None) -> None:
    """Write the Turn End entry for one routed turn (R20-R23): its outcome,
    and for an 'ok' turn, exactly the messages that entered the Conversation."""
    entry = {
        "timestamp": _now_iso(),
        "session_id": current_session_id(),
        "type": "turn_end",
        "status": status,
    }
    if status == "ok":
        entry["messages"] = list(messages)
        if replay is not None:
            from personal_agent.providers import chatgpt
            chatgpt.validate_turn_replay(replay, messages)
            entry["replay"] = replay
    elif status == "error":
        entry["error"] = error
    if continuation is not None:
        if status not in {"error", "interrupted"} or type(ordinal) is not int or ordinal <= 0:
            raise ValueError("invalid pending turn attribution")
        if not isinstance(task_digest, str) or re.fullmatch(r"[0-9a-f]{64}", task_digest) is None:
            raise ValueError("invalid pending turn task digest")
        entry.update(continuation=validate_continuation(continuation), ordinal=ordinal, task_digest=task_digest)
    _write_line(entry, restore_on_failure=continuation is not None)


def write_routed_task(ordinal: int, task: str, config: RuntimeConfig) -> None:
    _write_line({"timestamp": _now_iso(), "session_id": current_session_id(), "type": "routed_task_submitted",
                 "ordinal": ordinal, "task": task, "provider": config.provider, "model": config.model,
                 **_access(config)}, restore_on_failure=True)


def write_routed_task_retried(ordinal: int, config: RuntimeConfig) -> None:
    _write_line({"timestamp": _now_iso(), "session_id": current_session_id(), "type": "routed_task_retried",
                 "ordinal": ordinal, "provider": config.provider, "model": config.model,
                 **_access(config)}, restore_on_failure=True)


def write_turn_undone() -> None:
    """Write the entry marking one Undo: the /undo command, or the internal
    Undo /retry performs on a still-last successful turn."""
    _write_line(
        {
            "timestamp": _now_iso(),
            "session_id": current_session_id(),
            "type": "turn_undone",
        }
    )


def write_conversation_compressed(summary: str) -> None:
    """Write the entry marking one successful /compress, carrying the new
    Conversation Summary."""
    _write_line(
        {
            "timestamp": _now_iso(),
            "session_id": current_session_id(),
            "type": "conversation_compressed",
            "summary": summary,
        }, restore_on_failure=True,
    )


def write_conversation_cleared() -> None:
    """Write the entry marking one /clear (R25)."""
    _write_line(
        {
            "timestamp": _now_iso(),
            "session_id": current_session_id(),
            "type": "conversation_cleared",
        }, restore_on_failure=True,
    )


def log_tool_execution(
    *,
    tool_call_id: str,
    name: str,
    arguments: dict | None,
    ok: bool,
    result: object,
    error: str | None,
    dangerous_rules: list[str] | None = None,
    action_id: str | None = None,
) -> None:
    """Log one locally executed Tool call's result (R07). Not a Provider
    Attempt: does not touch total_cost or the Attempt counter. `dangerous_rules`
    (spec 0023 R5) is written only when non-empty, for an approved or
    rejected flagged `shell` call alike."""
    entry = {
        "timestamp": _now_iso(),
        "session_id": current_session_id(),
        "type": "tool_execution",
        "tool_call_id": tool_call_id,
        "name": name,
        "arguments": arguments,
        "ok": ok,
        "result": result,
        "error": error,
    }
    if dangerous_rules:
        entry["dangerous_rules"] = list(dangerous_rules)
    if action_id is not None:
        entry["action_id"] = action_id
    _write_line(entry)
