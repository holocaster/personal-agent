import json
import os
from datetime import datetime, timezone

MEMORY_PATH_ENV_VAR = "PA_MEMORY_PATH"
DEFAULT_MEMORY_PATH = "~/.personal_agent/memory.jsonl"
WARNING_THRESHOLD = 2000


def resolve_path() -> str:
    """Resolve the Memory file: PA_MEMORY_PATH names the exact file; unset
    or empty falls back to the fixed default. ~ is expanded either way; the
    path is never resolved against the cwd or the Workspace Root."""
    raw = os.environ.get(MEMORY_PATH_ENV_VAR) or DEFAULT_MEMORY_PATH
    return os.path.expanduser(raw)


def load(path: str | None = None) -> list[dict]:
    """Load every Memory Note in stored order. A missing file is empty
    Memory; blank lines are ignored. Raises ValueError naming the file when a
    line is not a JSON object with string text and string added."""
    path = path if path is not None else resolve_path()
    if not os.path.isfile(path):
        return []
    notes = []
    try:
        with open(path, encoding="utf-8") as memory_file:
            for line in memory_file:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"memory file {path} is malformed") from exc
                if (
                    not isinstance(parsed, dict)
                    or not isinstance(parsed.get("text"), str)
                    or not isinstance(parsed.get("added"), str)
                ):
                    raise ValueError(f"memory file {path} is malformed")
                notes.append({"text": parsed["text"], "added": parsed["added"]})
    except UnicodeDecodeError as exc:
        raise ValueError(f"memory file {path} is malformed") from exc
    return notes


def remember(text: str, path: str | None = None) -> dict:
    """Append one Memory Note, creating the parent directory when needed."""
    path = path if path is not None else resolve_path()
    note = {"text": text, "added": _now_iso()}
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as memory_file:
        memory_file.write(json.dumps(note) + "\n")
    return note


def forget(index: int, notes: list[dict], path: str | None = None) -> dict:
    """Remove the Memory Note at 1-based `index` from `notes` - the caller's
    current view of Memory, e.g. what `/memory` would show - and rewrite the
    file from the remaining notes through a temporary file beside it that
    replaces the original. The file is never re-read: `notes` is
    authoritative, so the caller's view and the file agree even if the file
    changed since it was loaded. Returns the removed note. Raises IndexError
    when index is out of range for `notes`."""
    path = path if path is not None else resolve_path()
    if not 1 <= index <= len(notes):
        raise IndexError(f"index {index} out of range for {len(notes)} notes")
    removed = notes[index - 1]
    remaining = notes[: index - 1] + notes[index:]
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as memory_file:
        for note in remaining:
            memory_file.write(json.dumps(note) + "\n")
    os.replace(tmp_path, path)
    return removed


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
