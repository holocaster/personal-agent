import difflib
from dataclasses import dataclass
from pathlib import Path

from personal_agent.tools import workspace
from personal_agent import file_recovery
from personal_agent.tools.builtins import ToolExecutionError

_SECTION_PREFIXES = ("*** Add File:", "*** Delete File:", "*** Update File:", "*** Move to:")


@dataclass(frozen=True)
class _Hunk:
    anchor: str | None
    old_lines: tuple[str, ...]
    new_lines: tuple[str, ...]
    end_of_file: bool
    number: int


@dataclass(frozen=True)
class _AddSection:
    path: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class _DeleteSection:
    path: str


@dataclass(frozen=True)
class _UpdateSection:
    path: str
    hunks: tuple[_Hunk, ...]


@dataclass(frozen=True)
class PatchFileOp:
    """One file's effect of an approved Patch, computed by prepare without
    touching disk: `target` is the write/unlink target (the candidate path,
    not its resolved real path, so an in-root symlink is kept as `edit`
    keeps it); `original` is the bytes to restore on a mid-apply failure
    (None for `add`, which restores by removing the file instead); `data` is
    the bytes to write (None for `delete`). `resolved` is a resolved
    identity used only to detect two paths that alias the same file (R4):
    for Update/Delete the resolved real path of the existing target; for Add
    the resolved real parent directory joined with the file's own name
    (the target itself does not exist yet), which still catches two Adds
    that reach the same file through a directory symlink."""

    action: str
    display_path: str
    target: Path
    original: bytes | None
    data: bytes | None
    resolved: Path


@dataclass(frozen=True)
class PreparedPatch:
    """Everything apply_patch's apply step needs, computed by prepare
    without touching disk: the Tool Confirmation label (every path,
    comma-joined in Patch order) and preview (the combined per-file diffs,
    in Patch order), plus the per-file operations to run once approved."""

    display_path: str
    preview: str
    operations: tuple[PatchFileOp, ...]
    effects: tuple[dict, ...]


def _split_lines(patch: str) -> list[str]:
    return [line[:-1] if line.endswith("\r") else line for line in patch.split("\n")]


def _parse_add_body(body: list[str], pos: int, line_number) -> tuple[list[str], int]:
    lines: list[str] = []
    while pos < len(body):
        line = body[pos]
        if line.strip().startswith(_SECTION_PREFIXES):
            break
        if not line.startswith("+"):
            raise ToolExecutionError(f"line {line_number(pos)}: Add File body line must start with '+'")
        lines.append(line[1:])
        pos += 1
    return lines, pos


def _parse_hunks(body: list[str], pos: int, line_number) -> tuple[list[_Hunk], int]:
    hunks: list[_Hunk] = []
    current: dict | None = None

    def finalize() -> None:
        if not current["old"] and not current["new"]:
            raise ToolExecutionError(f"hunk {len(hunks) + 1} is empty (line {current['line']})")
        hunks.append(
            _Hunk(
                anchor=current["anchor"],
                old_lines=tuple(current["old"]),
                new_lines=tuple(current["new"]),
                end_of_file=current["end_of_file"],
                number=len(hunks) + 1,
            )
        )

    while pos < len(body):
        line = body[pos]
        if line == "" or line[0] in (" ", "-", "+"):
            if current is None:
                current = {"anchor": None, "old": [], "new": [], "end_of_file": False, "line": line_number(pos)}
            kind = " " if line == "" else line[0]
            content = "" if line == "" else line[1:]
            if kind == " ":
                current["old"].append(content)
                current["new"].append(content)
            elif kind == "-":
                current["old"].append(content)
            else:
                current["new"].append(content)
            pos += 1
            continue
        trimmed = line.strip()
        if trimmed.startswith(_SECTION_PREFIXES):
            break
        if trimmed == "*** End of File":
            if current is None:
                current = {"anchor": None, "old": [], "new": [], "end_of_file": False, "line": line_number(pos)}
            current["end_of_file"] = True
            finalize()
            current = None
            pos += 1
            continue
        if line.startswith("@@") and line[2:].strip() == "":
            if current is not None:
                finalize()
            current = {"anchor": None, "old": [], "new": [], "end_of_file": False, "line": line_number(pos)}
            pos += 1
            continue
        if line.startswith("@@ "):
            if current is not None:
                finalize()
            current = {"anchor": line[3:], "old": [], "new": [], "end_of_file": False, "line": line_number(pos)}
            pos += 1
            continue
        raise ToolExecutionError(f"unrecognized line {line_number(pos)}: {line!r}")

    if current is not None:
        finalize()
    return hunks, pos


def _parse_sections(patch: str) -> list:
    """R2: the envelope grammar. Splits on Begin/End markers (blank lines
    before Begin and after End ignored, one trailing \\r stripped per line,
    marker lines trimmed) and dispatches the body between them into Add,
    Delete and Update File sections."""
    lines = _split_lines(patch)
    non_blank = [index for index, line in enumerate(lines) if line.strip() != ""]
    if not non_blank:
        raise ToolExecutionError("missing *** Begin Patch marker")
    first_idx, last_idx = non_blank[0], non_blank[-1]
    if lines[first_idx].strip() != "*** Begin Patch":
        raise ToolExecutionError(f"missing *** Begin Patch marker (line {first_idx + 1})")
    if lines[last_idx].strip() != "*** End Patch":
        raise ToolExecutionError(f"missing *** End Patch marker (line {last_idx + 1})")

    body = lines[first_idx + 1 : last_idx]
    body_offset = first_idx + 1

    def line_number(pos: int) -> int:
        return body_offset + pos + 1

    sections: list = []
    pos = 0
    while pos < len(body):
        line = body[pos]
        trimmed = line.strip()
        if trimmed.startswith("*** Add File:"):
            path = trimmed[len("*** Add File:") :].strip()
            pos += 1
            add_lines, pos = _parse_add_body(body, pos, line_number)
            sections.append(_AddSection(path=path, lines=tuple(add_lines)))
        elif trimmed.startswith("*** Delete File:"):
            path = trimmed[len("*** Delete File:") :].strip()
            pos += 1
            sections.append(_DeleteSection(path=path))
        elif trimmed.startswith("*** Update File:"):
            path = trimmed[len("*** Update File:") :].strip()
            pos += 1
            hunks, pos = _parse_hunks(body, pos, line_number)
            if not hunks:
                raise ToolExecutionError(f"{path}: Update File has no hunks")
            sections.append(_UpdateSection(path=path, hunks=tuple(hunks)))
        elif trimmed.startswith("*** Move to:"):
            raise ToolExecutionError(f"Move to is not supported (line {line_number(pos)})")
        else:
            raise ToolExecutionError(f"unrecognized line {line_number(pos)}: {line!r}")
    if not sections:
        raise ToolExecutionError("Patch has no file sections")
    return sections


def _match_hunk(display_path: str, lines: list[str], cursor: int, hunk: _Hunk) -> int:
    """R3: locates one hunk's old-lines run in `lines` at or after `cursor`,
    returning the 0-based match start. An anchor is a deliberate navigation
    (first occurrence at or after the cursor, then the first old-lines match
    after it); without one, the old-lines run must be unique in the region
    from the cursor onward. `*** End of File` restricts either search to a
    run ending at the file's last line."""
    if hunk.anchor is not None:
        anchor_pos = next((i for i in range(cursor, len(lines)) if lines[i] == hunk.anchor), None)
        if anchor_pos is None:
            raise ToolExecutionError(f"{display_path}: hunk {hunk.number}: anchor not found: {hunk.anchor!r}")
        search_start = anchor_pos + 1
    else:
        search_start = cursor

    if not hunk.old_lines:
        return len(lines)

    old = list(hunk.old_lines)
    occurrences = []
    for i in range(search_start, len(lines) - len(old) + 1):
        if lines[i : i + len(old)] == old and (not hunk.end_of_file or i + len(old) == len(lines)):
            occurrences.append(i)

    if hunk.anchor is not None:
        if not occurrences:
            raise ToolExecutionError(f"{display_path}: hunk {hunk.number}: context not found after anchor")
        return occurrences[0]

    if not occurrences:
        raise ToolExecutionError(f"{display_path}: hunk {hunk.number}: context not found")
    if len(occurrences) > 1:
        raise ToolExecutionError(
            f"{display_path}: hunk {hunk.number}: context is ambiguous, add an @@ anchor or more context"
        )
    return occurrences[0]


def _apply_hunks(display_path: str, old_text: str, hunks: tuple[_Hunk, ...]) -> str:
    """R3: applies every hunk of one Update File section top to bottom with
    a moving cursor, over lines split on the file's own line ending
    (`\\r\\n` when present, else `\\n`); untouched lines keep their bytes. A
    `+`-only hunk appends at the end of the file. The result always ends
    with a line ending."""
    line_ending = "\r\n" if "\r\n" in old_text else "\n"
    if old_text == "":
        lines: list[str] = []
    else:
        lines = old_text.split(line_ending)
        if old_text.endswith(line_ending):
            lines.pop()

    cursor = 0
    result: list[str] = []
    for hunk in hunks:
        match_start = _match_hunk(display_path, lines, cursor, hunk)
        result.extend(lines[cursor:match_start])
        result.extend(hunk.new_lines)
        cursor = match_start + len(hunk.old_lines) if hunk.old_lines else len(lines)
    result.extend(lines[cursor:])

    if not result:
        return ""
    return line_ending.join(result) + line_ending


def _diff_block(old_text: str, new_text: str, from_label: str, to_label: str) -> str:
    """A unified diff with explicit from/to headers (R6): Add uses
    `/dev/null` -> path, Delete path -> `/dev/null`, Update path -> path
    (via workspace._unified_diff). Always shows the headers, even when both
    sides are empty and difflib would otherwise emit nothing."""
    diff_lines = difflib.unified_diff(
        workspace._diff_lines(old_text), workspace._diff_lines(new_text), fromfile=from_label, tofile=to_label
    )
    text = workspace._finish_diff(diff_lines)
    return text if text else f"--- {from_label}\n+++ {to_label}\n"


def _with_section_path(section_path: str, func, *args):
    """Calls one of workspace's shared bounds helpers and, on failure,
    prefixes its generic error with this section's Patch path, so a
    multi-file Patch names which file the error came from."""
    try:
        return func(*args)
    except ToolExecutionError as exc:
        raise ToolExecutionError(f"{section_path}: {exc}") from exc


def _prepare_update(section: _UpdateSection, config: workspace.WorkspaceConfig) -> tuple[PatchFileOp, str]:
    candidate, resolved = _with_section_path(section.path, workspace._file_target, section.path)
    display_path = candidate.relative_to(config.root).as_posix()
    old_text = _with_section_path(section.path, workspace._read_text, resolved, config.max_write_bytes)
    if old_text is None:
        raise ToolExecutionError(f"{display_path}: file is binary or not valid UTF-8")
    new_text = _apply_hunks(display_path, old_text, section.hunks)
    if new_text == old_text:
        raise ToolExecutionError(f"{display_path}: update produces no changes")
    try:
        original_bytes = old_text.encode("utf-8")
        new_bytes = new_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ToolExecutionError(f"{display_path}: content is not valid UTF-8") from exc
    if len(new_bytes) > config.max_write_bytes:
        raise ToolExecutionError(f"{display_path}: content exceeds the {config.max_write_bytes}-byte write limit")
    diff_block = workspace._unified_diff(display_path, old_text, new_text)
    op = PatchFileOp(
        action="update", display_path=display_path, target=candidate, original=original_bytes, data=new_bytes,
        resolved=resolved,
    )
    return op, diff_block


def _prepare_add(section: _AddSection, config: workspace.WorkspaceConfig) -> tuple[PatchFileOp, str]:
    supplied = _with_section_path(section.path, workspace._validated_relative_path, section.path)
    if not supplied.name or supplied.name in (".", ".."):
        raise ToolExecutionError(f"{section.path}: path must name a file")
    parent_dir = _with_section_path(section.path, workspace._directory_target, supplied.parent.as_posix())
    candidate = parent_dir / supplied.name
    if workspace._is_excluded(candidate):
        raise ToolExecutionError(f"{section.path}: requested file is excluded")
    display_path = candidate.relative_to(config.root).as_posix()
    if candidate.is_symlink() or candidate.exists():
        raise ToolExecutionError(f"{display_path}: file exists; use Update File")
    content = "".join(line + "\n" for line in section.lines)
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ToolExecutionError(f"{display_path}: content is not valid UTF-8") from exc
    if len(data) > config.max_write_bytes:
        raise ToolExecutionError(f"{display_path}: content exceeds the {config.max_write_bytes}-byte write limit")
    diff_block = _diff_block("", content, "/dev/null", display_path)
    resolved = parent_dir.resolve(strict=True) / supplied.name
    op = PatchFileOp(
        action="add", display_path=display_path, target=candidate, original=None, data=data, resolved=resolved
    )
    return op, diff_block


def _prepare_delete(section: _DeleteSection, config: workspace.WorkspaceConfig) -> tuple[PatchFileOp, str]:
    candidate, resolved = _with_section_path(section.path, workspace._file_target, section.path)
    display_path = candidate.relative_to(config.root).as_posix()
    if candidate.is_symlink():
        raise ToolExecutionError(f"{display_path}: cannot delete a symlink")
    old_text = _with_section_path(section.path, workspace._read_text, resolved, config.max_write_bytes)
    if old_text is None:
        raise ToolExecutionError(f"{display_path}: file is binary or not valid UTF-8")
    original_bytes = old_text.encode("utf-8")
    diff_block = _diff_block(old_text, "", display_path, "/dev/null")
    op = PatchFileOp(
        action="delete", display_path=display_path, target=candidate, original=original_bytes, data=None,
        resolved=resolved,
    )
    return op, diff_block


def prepare_patch(arguments: dict) -> PreparedPatch:
    """apply_patch's prepare step (two-phase Mutating Tool, R5): parses the
    whole Patch, then validates and prepares every file operation - path
    bounds, hunk matching, size limits, duplicate paths - before Tool
    Confirmation, without touching disk."""
    sections = _parse_sections(arguments["patch"])

    # R4's "same path twice" check runs on the literal path first, before any
    # per-section validation, so e.g. an Add and a Delete of the same path
    # never falls through to Add's own "file exists" error instead.
    seen_literal_paths: set[str] = set()
    for section in sections:
        literal_path = _with_section_path(section.path, workspace._validated_relative_path, section.path).as_posix()
        if literal_path in seen_literal_paths:
            raise ToolExecutionError(f"duplicate path in Patch: {literal_path}")
        seen_literal_paths.add(literal_path)

    config = workspace.configured_workspace()
    operations: list[PatchFileOp] = []
    diff_blocks: list[str] = []
    display_paths: list[str] = []
    seen_resolved: set[Path] = set()

    for section in sections:
        if isinstance(section, _UpdateSection):
            op, diff_block = _prepare_update(section, config)
        elif isinstance(section, _AddSection):
            op, diff_block = _prepare_add(section, config)
        else:
            op, diff_block = _prepare_delete(section, config)

        # A resolved-target alias (two different paths reaching the same
        # real file, or the same real parent directory for two Adds) can
        # only be found once the target is resolved, so this second check
        # stays per-section.
        if op.resolved in seen_resolved:
            raise ToolExecutionError(f"duplicate path in Patch: {op.display_path}")
        seen_resolved.add(op.resolved)

        operations.append(op)
        diff_blocks.append(diff_block)
        display_paths.append(op.display_path)

    return PreparedPatch(
        display_path=", ".join(display_paths), preview="".join(diff_blocks), operations=tuple(operations),
        effects=tuple(file_recovery.prepare_effect(op.display_path, op.data, op.original) for op in operations),
    )


def apply_patch_change(prepared: PreparedPatch) -> dict:
    """apply_patch's apply step (R7): writes/unlinks every operation in
    Patch order. On an OS error, every file touched so far, including the
    failing one, is restored from its in-memory original - an `add` by
    removing it, an `update`/`delete` by rewriting its original bytes - and
    any path that also fails to restore is named in the Tool error."""
    file_recovery.apply_effects(prepared.effects)
    return {"files": [{"path": op.display_path, "action": op.action} for op in prepared.operations]}
