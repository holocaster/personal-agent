import re
import stat
from dataclasses import dataclass
from pathlib import Path

from personal_agent.tools.workspace import _is_excluded


@dataclass(frozen=True)
class ProjectInstructions:
    text: str
    sources: tuple[str, ...]


class LoadError(ValueError):
    def __init__(self, source: str, reference: str | None, reason: str):
        self.source = source
        self.reference = reference
        self.reason = reason
        super().__init__(f"{source}" + (f" -> {reference}" if reference is not None else "") + f": {reason}")


def load(workspace_root: str | Path) -> ProjectInstructions:
    root = Path(workspace_root).resolve()
    selected = None
    for name in ("AGENTS.md", "CLAUDE.md"):
        try:
            (root / name).lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise LoadError(name, None, str(exc)) from exc
        selected = root / name
        break
    if selected is None:
        return ProjectInstructions("", ())
    active: list[Path] = []
    completed: set[Path] = set()
    sources: list[str] = []
    output: list[str] = []
    source_bytes = 0
    expanded_bytes = 0

    def append(text: str, source: str) -> None:
        nonlocal expanded_bytes
        expanded_bytes += len(text.encode("utf-8"))
        if expanded_bytes > 512 * 1024:
            raise LoadError(source, None, "expanded text exceeds 512 KiB")
        output.append(text)

    def include(named: Path, containing: str, reference: str | None) -> None:
        nonlocal source_bytes
        try:
            path = named.resolve(strict=True)
            if not path.is_relative_to(root):
                raise ValueError("path is outside Workspace Root")
            if any(_is_excluded(item) for item in (named, path)):
                raise ValueError("excluded instruction file")
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("instruction source must be a regular file")
            source = path.relative_to(root).as_posix()
            if path in active:
                chain = " -> ".join(item.relative_to(root).as_posix() for item in (*active, path))
                raise ValueError(f"reference cycle: {chain}")
            if path in completed:
                return
            if len(active) >= 16:
                raise ValueError("active instruction chain exceeds 16 files")
            if len(sources) >= 64:
                raise ValueError("instruction graph exceeds 64 distinct sources")
            with path.open("rb") as stream:
                data = stream.read(64 * 1024 + 1)
            if len(data) > 64 * 1024:
                raise ValueError("source exceeds 64 KiB")
            source_bytes += len(data)
            if source_bytes > 256 * 1024:
                raise ValueError("distinct source bytes exceed 256 KiB")
            text = data.decode("utf-8", errors="strict")
            if "\0" in text:
                raise ValueError("NUL is not allowed in instruction text")
        except (OSError, ValueError, RuntimeError) as exc:
            raise LoadError(containing, reference, str(exc)) from exc
        sources.append(source)
        active.append(path)
        append(f"[Project source: {source}]\n", source)
        for start, end, target in _references(text, source):
            append(text[start:end], source)
            if target is not None:
                if Path(target).is_absolute() or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                    raise LoadError(source, target, "absolute and URI references are not allowed")
                include(path.parent / target, source, target)
        append(f"\n[End project source: {source}]\n", source)
        active.pop()
        completed.add(path)

    include(selected, selected.name, None)
    return ProjectInstructions("".join(output), tuple(sources))


def _references(text: str, source: str):
    index = 0
    literal_start = 0
    fence = None
    while index < len(text):
        if index == 0 or text[index - 1] == "\n":
            line_end = text.find("\n", index)
            line_end = len(text) if line_end < 0 else line_end + 1
            line = text[index:line_end]
            marker = re.match(r" {0,3}(`{3,}|~{3,})(.*?)(?:\n)?$", line)
            if fence is not None:
                if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                    fence = None
                index = line_end
                continue
            if marker:
                fence = (marker[1][0], len(marker[1]))
                index = line_end
                continue
        if text[index] == "`":
            run = re.match(r"`+", text[index:])[0]
            remaining = text[index + len(run):]
            next_fence = re.search(r"(?m)^ {0,3}(?:`{3,}|~{3,})", remaining)
            closing = re.search(r"(?<!`)" + re.escape(run) + r"(?!`)",
                                remaining[:next_fence.start()] if next_fence else remaining)
            index += len(run) + (closing.end() if closing else 0)
            continue
        boundary = index == 0 or text[index - 1].isspace() or text[index - 1] == "("
        bracketed = text.startswith("[@", index)
        if not boundary or not (bracketed or text[index] == "@"):
            index += 1
            continue
        token_start = index
        index += 2 if bracketed else 1
        path_start = index
        target = ""
        quoted = index < len(text) and text[index] in "\"'"
        if quoted:
            quote = text[index]
            index += 1
            while index < len(text) and text[index] != quote:
                if text[index] == "\\" and index + 1 < len(text) and text[index + 1] in (quote, "\\"):
                    index += 1
                target += text[index]
                index += 1
            if index == len(text):
                raise LoadError(source, text[token_start:index], "missing closing quote")
            index += 1
        else:
            while index < len(text) and not text[index].isspace() and text[index] not in "()[]\"'`":
                index += 1
            target = text[path_start:index]
        if not target:
            if quoted or bracketed:
                raise LoadError(source, text[token_start:index], "empty reference path")
            continue
        if bracketed:
            if index == len(text) or text[index] != "]":
                raise LoadError(source, text[token_start:index], "missing closing bracket")
            index += 1
        yield literal_start, token_start, target
        literal_start = index
    yield literal_start, len(text), None
