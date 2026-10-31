import codecs
import difflib
import fnmatch
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from personal_agent.tools.builtins import ToolExecutionError
from personal_agent import call_log, file_recovery

DEFAULT_MAX_READ_BYTES = 32 * 1024
DEFAULT_MAX_WRITE_BYTES = 1024 * 1024
MAX_WORKSPACE_DEPTH = 8
MAX_WORKSPACE_RESULTS = 100
SKIPPED_DIR_NAMES = frozenset({".git", ".venv", "node_modules", "__pycache__"})
DEFAULT_READ_OFFSET = 1
DEFAULT_READ_LIMIT = 500
EXCERPT_MAX_CHARS = 200
# Reused by shell.py for its own output cap (same Tool Output Cap concept);
# defined here, not there, because shell.py already imports workspace and
# the reverse import would cycle.
TRUNCATION_MARKER = "[...truncated]"
_LINE_CHUNK_SIZE = 65536


@dataclass(frozen=True)
class WorkspaceConfig:
    root: Path
    max_read_bytes: int
    max_write_bytes: int


@dataclass(frozen=True)
class PreparedChange:
    """Everything a Mutating Tool's apply step needs, computed by its prepare
    step without touching disk: the preview shown for Tool Confirmation, and
    the write target/bytes/result used only once the change is approved."""

    display_path: str
    preview: str
    candidate: Path
    data: bytes
    result: dict
    effects: tuple[dict, ...]


_workspace: WorkspaceConfig | None = None


def parse_positive_int(value: str | int | None, default: int, env_name: str, unit: str = "whole-byte count") -> int:
    """Shared positive-integer env var parser (R01, ticket 0018-02): also
    used by shell.py for PA_SHELL_TIMEOUT_SECONDS and
    PA_SHELL_MAX_OUTPUT_BYTES, which is why `unit` is overridable."""
    if value is None or value == "":
        return default
    if isinstance(value, int) and not isinstance(value, bool):
        parsed = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        parsed = int(value)
    else:
        raise ValueError(f"{env_name} must be a positive {unit}")
    if parsed <= 0:
        raise ValueError(f"{env_name} must be a positive {unit}")
    return parsed


def configure_workspace(
    root_value: str | Path,
    max_read_bytes_value: str | int | None = None,
    max_write_bytes_value: str | int | None = None,
) -> WorkspaceConfig:
    try:
        root = Path(root_value).resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Workspace Root must name an existing directory: {root_value}") from exc
    if not root.is_dir():
        raise ValueError(f"Workspace Root must name a directory: {root_value}")

    max_read_bytes = parse_positive_int(max_read_bytes_value, DEFAULT_MAX_READ_BYTES, "PA_MAX_READ_BYTES")
    max_write_bytes = parse_positive_int(max_write_bytes_value, DEFAULT_MAX_WRITE_BYTES, "PA_MAX_WRITE_BYTES")

    global _workspace
    _workspace = WorkspaceConfig(root=root, max_read_bytes=max_read_bytes, max_write_bytes=max_write_bytes)
    return _workspace


def configured_workspace() -> WorkspaceConfig:
    if _workspace is None:
        raise ToolExecutionError("workspace is not configured")
    return _workspace


def _is_excluded(path: Path) -> bool:
    if path.name == ".env" or path.name.endswith((".pem", ".key")):
        return True
    if _workspace is None:
        return False
    candidate = path if path.is_absolute() else _workspace.root / path
    storage = Path(call_log.session_log_path()).parent.parent
    try:
        parts = candidate.relative_to(storage).parts
    except ValueError:
        return False
    return len(parts) > 1 and parts[1].startswith("recovery-")


def _validated_relative_path(value: str) -> Path:
    try:
        supplied = Path(value)
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError("path is invalid") from exc
    if supplied.is_absolute():
        raise ToolExecutionError("path must be relative to the workspace")
    if ".." in supplied.parts:
        raise ToolExecutionError("path traversal is not allowed")
    return supplied


def _resolve_workspace_path(value: str) -> tuple[Path, Path]:
    workspace = configured_workspace()
    supplied = _validated_relative_path(value)
    candidate = workspace.root / supplied
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ToolExecutionError(f"path is unavailable: {value}") from exc
    try:
        resolved.relative_to(workspace.root)
    except ValueError as exc:
        raise ToolExecutionError("path resolves outside the workspace") from exc
    return candidate, resolved


def _file_target(value: str) -> tuple[Path, Path]:
    candidate, resolved = _resolve_workspace_path(value)
    if _is_excluded(candidate) or _is_excluded(resolved):
        raise ToolExecutionError("requested file is excluded")
    if candidate.is_dir():
        raise ToolExecutionError("path must name a file")
    if not resolved.is_file():
        raise ToolExecutionError("path must name a regular file")
    return candidate, resolved


def _directory_target(value: str) -> Path:
    candidate, resolved = _resolve_workspace_path(value)
    if _is_excluded(candidate) or _is_excluded(resolved):
        raise ToolExecutionError("requested directory is excluded")
    if candidate.is_symlink():
        raise ToolExecutionError("directory symlinks are not allowed")
    if not resolved.is_dir():
        raise ToolExecutionError("path must name a directory")
    return candidate


def _walk_files(directory: Path) -> Iterator[Path]:
    workspace = configured_workspace()

    def visit(current: Path, depth: int) -> Iterator[Path]:
        try:
            resolved_current = current.resolve(strict=True)
            children = sorted(current.iterdir(), key=lambda child: child.name + ("/" if child.is_dir() else ""))
        except OSError as exc:
            raise ToolExecutionError(f"path is inaccessible: {current.relative_to(workspace.root).as_posix()}") from exc
        for child in children:
            if _is_excluded(child) or _is_excluded(resolved_current / child.name):
                continue
            if child.is_symlink():
                try:
                    resolved = child.resolve(strict=True)
                except OSError:
                    continue
                try:
                    resolved.relative_to(workspace.root)
                except ValueError:
                    continue
                if resolved.is_dir():
                    continue
                if resolved.is_file() and not _is_excluded(child) and not _is_excluded(resolved):
                    yield child
                continue
            if child.is_dir():
                if child.name in SKIPPED_DIR_NAMES:
                    continue
                if depth < MAX_WORKSPACE_DEPTH:
                    yield from visit(child, depth + 1)
            elif child.is_file() and not _is_excluded(child):
                yield child

    yield from visit(directory, 0)


def _matches_glob_segments(path_segments: list[str], pattern_segments: list[str]) -> bool:
    """One shared, case-sensitive glob matcher (R2): recurses segment by
    segment, letting a `**` segment consume zero or more path segments;
    every other segment is matched with fnmatch.fnmatchcase, which never
    crosses a `/` since each segment is single-'/'-free by construction."""
    if not pattern_segments:
        return not path_segments
    head, *rest = pattern_segments
    if head == "**":
        if _matches_glob_segments(path_segments, rest):
            return True
        return bool(path_segments) and _matches_glob_segments(path_segments[1:], pattern_segments)
    if not path_segments:
        return False
    return fnmatch.fnmatchcase(path_segments[0], head) and _matches_glob_segments(path_segments[1:], rest)


def _matches_glob(relative_posix: str, pattern: str) -> bool:
    if "/" not in pattern:
        return fnmatch.fnmatchcase(relative_posix.rsplit("/", 1)[-1], pattern)
    return _matches_glob_segments(relative_posix.split("/"), pattern.split("/"))


def _read_text(path: Path, max_bytes: int | None = None) -> str | None:
    try:
        if max_bytes is None:
            data = path.read_bytes()
        else:
            with path.open("rb") as file:
                data = file.read(max_bytes + 1)
    except OSError as exc:
        raise ToolExecutionError(f"path is inaccessible: {path}") from exc
    if max_bytes is not None and len(data) > max_bytes:
        raise ToolExecutionError(f"file exceeds the {max_bytes}-byte write limit")
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _finish_diff(lines) -> str:
    """Joins unified-diff lines, adding a `\\ No newline at end of file`
    marker after any line that lacks a trailing `\\n` (the source text had no
    final newline), so every emitted line, and every block built from this
    text, ends with a newline of its own."""
    result = []
    for line in lines:
        result.append(line if line.endswith("\n") else f"{line}\n\\ No newline at end of file\n")
    return "".join(result)


def _diff_lines(text: str) -> list[str]:
    """Splits text into diff input lines on `\\n` only, unlike
    str.splitlines(keepends=True), which also breaks on form feed, vertical
    tab, `\\x1c`-`\\x1e`, `\\x85`, U+2028 and U+2029 - none of which should
    end a preview line. A `\\r` right before a `\\n` stays attached to that
    line, so `\\r\\n` remains one line ending."""
    if text == "":
        return []
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1] != "":
        lines.append(parts[-1])
    return lines


def _unified_diff(display_path: str, old_text: str, new_text: str) -> str:
    lines = difflib.unified_diff(
        _diff_lines(old_text),
        _diff_lines(new_text),
        fromfile=display_path,
        tofile=display_path,
    )
    return _finish_diff(lines)


def prepare_write(arguments: dict) -> PreparedChange:
    """`write`'s prepare step (two-phase Mutating Tool): every check that can
    fail (path, parent directory, exclusion, existing-target rules, UTF-8,
    size limit) runs here, before Tool Confirmation, and nothing touches
    disk."""
    value = arguments["path"]
    supplied = _validated_relative_path(value)
    if not supplied.name or supplied.name in (".", ".."):
        raise ToolExecutionError("path must name a file")

    parent_dir = _directory_target(supplied.parent.as_posix())
    candidate = parent_dir / supplied.name
    if _is_excluded(candidate):
        raise ToolExecutionError("requested file is excluded")

    workspace = configured_workspace()
    display_path = candidate.relative_to(workspace.root).as_posix()

    content = arguments["content"]
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ToolExecutionError("content is not valid UTF-8") from exc
    if len(data) > workspace.max_write_bytes:
        raise ToolExecutionError(f"content exceeds the {workspace.max_write_bytes}-byte write limit")

    if candidate.is_symlink() or candidate.exists():
        _, resolved = _file_target(value)
        old_text = _read_text(resolved, workspace.max_write_bytes)
        if old_text is None:
            raise ToolExecutionError("existing file is binary or not valid UTF-8")
        preview = _unified_diff(display_path, old_text, content)
        created = False
    else:
        preview = content
        created = True

    return PreparedChange(
        display_path=display_path,
        preview=preview,
        candidate=candidate,
        data=data,
        result={"path": display_path, "bytes_written": len(data), "created": created},
        effects=(file_recovery.prepare_effect(display_path, data, None if created else old_text.encode("utf-8")),),
    )


def prepare_edit(arguments: dict) -> PreparedChange:
    """`edit`'s prepare step (two-phase Mutating Tool): every check that can
    fail (path, exclusion, UTF-8, match count, size limit) runs here, before
    Tool Confirmation, and nothing touches disk."""
    candidate, resolved = _file_target(arguments["path"])
    workspace = configured_workspace()
    display_path = candidate.relative_to(workspace.root).as_posix()

    old_text = _read_text(resolved, workspace.max_write_bytes)
    if old_text is None:
        raise ToolExecutionError("file is binary or not valid UTF-8")

    old_string = arguments["old_string"]
    new_string = arguments["new_string"]
    if new_string == old_string:
        raise ToolExecutionError("new_string is identical to old_string")

    count = old_text.count(old_string)
    if count == 0:
        raise ToolExecutionError("old_string was not found")
    replace_all = arguments.get("replace_all", False)
    if count > 1 and not replace_all:
        raise ToolExecutionError(f"old_string is not unique: {count} occurrences found")

    replacements = count if replace_all else 1
    new_text = old_text.replace(old_string, new_string, -1 if replace_all else 1)

    try:
        data = new_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ToolExecutionError("content is not valid UTF-8") from exc
    if len(data) > workspace.max_write_bytes:
        raise ToolExecutionError(f"content exceeds the {workspace.max_write_bytes}-byte write limit")

    preview = _unified_diff(display_path, old_text, new_text)

    return PreparedChange(
        display_path=display_path,
        preview=preview,
        candidate=candidate,
        data=data,
        result={"path": display_path, "replacements": replacements},
        effects=(file_recovery.prepare_effect(display_path, data, old_text.encode("utf-8")),),
    )


def apply_change(prepared: PreparedChange) -> dict:
    """A Mutating Tool's apply step: write the prepared bytes directly (no
    temp-file replace, so a symlinked target and its permissions are kept)
    and return the already-computed result."""
    file_recovery.apply_effects(prepared.effects)
    return prepared.result


def list_files(arguments: dict) -> dict:
    directory = _directory_target(arguments.get("path", "."))
    workspace = configured_workspace()
    pattern = arguments.get("pattern")
    files = []
    for path in _walk_files(directory):
        if pattern is not None and not _matches_glob(path.relative_to(directory).as_posix(), pattern):
            continue
        if len(files) >= MAX_WORKSPACE_RESULTS:
            return {"files": files, "truncated": True}
        files.append(path.relative_to(workspace.root).as_posix())
    return {"files": files, "truncated": False}


class _BoundedLineReader:
    def __init__(self, file):
        self._file = file
        self._buf = b""

    def _fill(self) -> bool:
        if self._buf:
            return True
        chunk = self._file.read(_LINE_CHUNK_SIZE)
        if not chunk:
            return False
        self._buf = chunk
        return True

    def has_more(self) -> bool:
        return self._fill()

    def read_line(self, max_keep: int) -> tuple[bytes, bool, bool]:
        """Returns `(kept, truncated, exists)`; bytes past `max_keep` are scanned but discarded."""
        kept = bytearray()
        truncated = False
        exists = False
        while True:
            if not self._fill():
                return bytes(kept), truncated, exists
            exists = True
            newline_index = self._buf.find(b"\n")
            if newline_index == -1:
                line_part, self._buf = self._buf, b""
            else:
                line_part, self._buf = self._buf[: newline_index + 1], self._buf[newline_index + 1 :]
            if not truncated:
                room = max_keep - len(kept)
                if len(line_part) <= room:
                    kept.extend(line_part)
                else:
                    kept.extend(line_part[:room])
                    truncated = True
            if newline_index != -1:
                return bytes(kept), truncated, True


def _decode_strict(data: bytes) -> str:
    if b"\0" in data:
        raise ToolExecutionError("file is binary or not valid UTF-8")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolExecutionError("file is binary or not valid UTF-8") from exc


def _decode_dropping_trailing_partial_char(data: bytes) -> str:
    """`final=False` drops a multibyte character split by the cut instead of raising."""
    if b"\0" in data:
        raise ToolExecutionError("file is binary or not valid UTF-8")
    try:
        return codecs.getincrementaldecoder("utf-8")().decode(data, False)
    except UnicodeDecodeError as exc:
        raise ToolExecutionError("file is binary or not valid UTF-8") from exc


def _offset_past_end_error(offset: int, count: int) -> ToolExecutionError:
    unit = "line" if count == 1 else "lines"
    return ToolExecutionError(f"offset {offset} is past end of file ({count} {unit})")


def read_file(arguments: dict) -> dict:
    candidate, _ = _file_target(arguments["path"])
    offset = arguments.get("offset", DEFAULT_READ_OFFSET)
    limit = arguments.get("limit", DEFAULT_READ_LIMIT)
    cap = configured_workspace().max_read_bytes
    marker = TRUNCATION_MARKER.encode()

    try:
        with candidate.open("rb") as file:
            reader = _BoundedLineReader(file)

            line_number = 1
            while line_number < offset:
                _, _, exists = reader.read_line(0)
                if not exists:
                    raise _offset_past_end_error(offset, line_number - 1)
                line_number += 1

            raw = bytearray()
            while line_number < offset + limit:
                prefix = f"{line_number}\t".encode()
                max_keep = max(cap - len(raw) - len(prefix), 0)
                kept, truncated, exists = reader.read_line(max_keep)

                if not exists:
                    if raw:
                        return {"content": _decode_strict(bytes(raw)), "has_more": False, "next_offset": None}
                    if offset == 1:
                        return {"content": "", "has_more": False, "next_offset": None}
                    raise _offset_past_end_error(offset, offset - 1)

                if not truncated:
                    raw.extend(prefix)
                    raw.extend(kept)
                    line_number += 1
                    continue

                if raw:
                    return {"content": _decode_strict(bytes(raw)), "has_more": True, "next_offset": line_number}

                keep_len = max(max_keep - len(marker), 0)
                text = _decode_dropping_trailing_partial_char(bytes(kept[:keep_len]))
                content = prefix.decode() + text + TRUNCATION_MARKER
                has_more = reader.has_more()
                return {
                    "content": content,
                    "has_more": has_more,
                    "next_offset": line_number + 1 if has_more else None,
                }

            has_more = reader.has_more()
            return {
                "content": _decode_strict(bytes(raw)),
                "has_more": has_more,
                "next_offset": line_number if has_more else None,
            }
    except OSError as exc:
        raise ToolExecutionError(f"path is inaccessible: {candidate}") from exc


def _r2_lines(text: str) -> list[str]:
    if text == "":
        return []
    parts = text.split("\n")
    if text.endswith("\n"):
        parts.pop()
    return parts


def _excerpt(line: str, match_start: int, match_length: int) -> str:
    """Shared by literal and regex search_text hits (R5): centred on the
    match's start/length rather than re-finding a casefolded needle, so both
    modes share one implementation."""
    if len(line) <= EXCERPT_MAX_CHARS:
        return line
    center = match_start + match_length // 2
    start = max(0, min(center - EXCERPT_MAX_CHARS // 2, len(line) - EXCERPT_MAX_CHARS))
    end = start + EXCERPT_MAX_CHARS
    excerpt = line[start:end]
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(line):
        excerpt += "…"
    return excerpt


def search_text(arguments: dict) -> dict:
    value = arguments["path"] if "path" in arguments else "."
    candidate, resolved = _resolve_workspace_path(value)
    if _is_excluded(candidate) or _is_excluded(resolved):
        raise ToolExecutionError("requested file is excluded")
    if candidate.is_symlink() and resolved.is_dir():
        raise ToolExecutionError("directory symlinks are not allowed")
    if resolved.is_dir():
        files = _walk_files(candidate)
        glob_pattern = arguments.get("glob")
        if glob_pattern is not None:
            files = (path for path in files if _matches_glob(path.relative_to(candidate).as_posix(), glob_pattern))
    elif resolved.is_file():
        files = [candidate]
    else:
        raise ToolExecutionError("path must name a file or directory")

    workspace = configured_workspace()
    use_regex = arguments.get("regex", False)
    if use_regex:
        try:
            pattern = re.compile(arguments["text"], re.IGNORECASE)
        except re.error as exc:
            raise ToolExecutionError(f"invalid regex: {exc}") from exc
    else:
        needle = arguments["text"].casefold()

    matches = []
    running_bytes = 0
    for path in files:
        content = _read_text(path)
        if content is None:
            if resolved.is_file():
                raise ToolExecutionError("file is binary or not valid UTF-8")
            continue
        display_path = path.relative_to(workspace.root).as_posix()
        for line_number, line in enumerate(_r2_lines(content), start=1):
            excerpt_source = line[:-1] if line.endswith("\r") else line
            if use_regex:
                found = pattern.search(excerpt_source)
                if found is None:
                    continue
                match_start, match_length = found.start(), found.end() - found.start()
            else:
                if needle not in line.casefold():
                    continue
                match_start = excerpt_source.casefold().find(needle)
                if match_start == -1:
                    match_start = 0
                match_length = len(needle)
            match = {
                "path": display_path,
                "line": line_number,
                "excerpt": _excerpt(excerpt_source, match_start, match_length),
            }
            encoded_length = len(json.dumps(match, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if len(matches) >= MAX_WORKSPACE_RESULTS or running_bytes + encoded_length > workspace.max_read_bytes:
                return {"matches": matches, "truncated": True}
            matches.append(match)
            running_bytes += encoded_length
    return {"matches": matches, "truncated": False}
