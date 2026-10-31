import hashlib
import os
import re
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

import yaml

from personal_agent.tools.builtins import ToolExecutionError
from personal_agent.tools.workspace import configured_workspace

MAX_BYTES = 32 * 1024
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
ALIASES = {
    "Read": {"read_file"}, "Grep": {"search_text"}, "Glob": {"list_files"},
    "Write": {"write"}, "Edit": {"edit"}, "Bash": {"shell", "job_status", "job_stop"},
    "Skill": {"skill"}, "TodoWrite": {"todo"}, "WebFetch": {"webfetch"}, "WebSearch": {"websearch"},
}
NATIVE_NAMES = frozenset({"calculator", "current_time", "read_file", "search_text", "list_files", "write", "edit",
                          "apply_patch", "shell", "job_status", "job_stop", "skill", "todo", "webfetch", "websearch",
                          "session_logs", "mcp_list_resources", "mcp_list_resource_templates", "mcp_read_resource",
                          "agent", "question"})


@dataclass(frozen=True)
class Definition:
    name: str
    description: str
    instructions: str
    tools: frozenset[str] | None
    origin: str
    source: str
    canonical: str
    fingerprint: str
    identity: tuple[int, int]
    diagnostics: tuple[str, ...] = ()


def _load(path: Path, scope: Path, origin: str) -> Definition:
    name = path.stem
    if len(name) > 64 or not NAME.fullmatch(name):
        raise ValueError("invalid agent name")
    directory = path.parent.resolve(strict=True)
    canonical = path.resolve(strict=True)
    if not directory.is_relative_to(scope) or not canonical.is_relative_to(scope):
        raise ValueError("definition escapes its scope")
    fd = os.open(canonical, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise ValueError("definition must be a regular file")
    with os.fdopen(fd, "rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or b"\x00" in data:
        raise ValueError("definition must be bounded UTF-8 text (32 KiB maximum)")
    text = data.decode("utf-8")
    if path.suffix == ".md":
        lines = text.splitlines()
        if not lines or lines[0] != "---":
            raise ValueError("Markdown requires YAML frontmatter")
        try:
            end = lines.index("---", 1)
        except ValueError:
            raise ValueError("unterminated YAML frontmatter") from None
        metadata = yaml.safe_load("\n".join(lines[1:end]))
        instructions = "\n".join(lines[end + 1:]).strip()
        if not isinstance(metadata, dict) or metadata.get("name") != name:
            raise ValueError("Markdown name must match filename")
        description = metadata.get("description")
    else:
        metadata = tomllib.loads(text)
        if metadata.get("name", name) != name:
            raise ValueError("TOML name must match filename")
        instructions = metadata.get("developer_instructions")
        description = metadata.get("description", name)
    if not isinstance(description, str) or not description.strip():
        raise ValueError("nonempty description required")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError("nonempty instructions required")
    allowed = None
    diagnostics = []
    if "tools" in metadata:
        tokens = metadata["tools"]
        if isinstance(tokens, str):
            tokens = [token.strip() for token in tokens.split(",") if token.strip()]
        if not isinstance(tokens, list) or any(not isinstance(token, str) for token in tokens):
            raise ValueError("tools must be a string or string array")
        allowed = set()
        for token in tokens:
            token = token.strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
                raise ValueError("unsupported parameterized or pattern Tool permission")
            if token in ALIASES:
                allowed.update(ALIASES[token])
            elif token in NATIVE_NAMES:
                allowed.add(token)
            else:
                diagnostics.append(f"unknown Tool token {token!r} grants nothing")
        allowed = frozenset(allowed)
    return Definition(name, description.strip(), instructions.strip(), allowed, origin, str(path),
                      str(canonical), hashlib.sha256(data).hexdigest(), (info.st_dev, info.st_ino), tuple(diagnostics))


def discover() -> tuple[dict[str, Definition], list[str]]:
    selected = {}
    diagnostics = []
    for origin, scope in (("workspace", configured_workspace().root), ("global", Path.home().resolve())):
        for location in (".agents/agents", ".claude/agents", ".codex/agents"):
            directory = scope / location
            try:
                if not directory.exists():
                    continue
                if not directory.resolve(strict=True).is_relative_to(scope):
                    raise ValueError("agent directory escapes its scope")
                paths = sorted((path for path in directory.iterdir() if path.suffix in {".md", ".toml"}),
                               key=lambda path: path.name)
            except (OSError, ValueError, RuntimeError) as exc:
                diagnostics.append(f"{origin}/{location}: {exc}")
                continue
            counts = {}
            for path in paths:
                counts[path.stem] = counts.get(path.stem, 0) + 1
            for path in paths:
                try:
                    if counts[path.stem] > 1:
                        raise ValueError("ambiguous same-name definitions in one location")
                    definition = _load(path, scope, origin)
                    selected.setdefault(definition.name, definition)
                    diagnostics.extend(f"{origin}/{location}/{path.name}: {item}" for item in definition.diagnostics)
                except yaml.YAMLError as exc:
                    mark = getattr(exc, "problem_mark", None)
                    where = f" at line {mark.line + 1}" if mark is not None else ""
                    diagnostics.append(f"{origin}/{location}/{path.name}: invalid YAML ({type(exc).__name__}{where})")
                except (OSError, ValueError, RuntimeError) as exc:
                    diagnostics.append(f"{origin}/{location}/{path.name}: {exc}")
    return dict(sorted(selected.items())), diagnostics


def revalidate(expected: Definition) -> None:
    selected, _ = discover()
    if selected.get(expected.name) != expected:
        raise ToolExecutionError("agent definition changed since it was advertised; start a new task")


def tool_definition(roles, diagnostics):
    from personal_agent.providers.contract import ToolDef
    description = ("Delegate one bounded task to a named role in a fresh native Session. Children share the workspace "
                   "and current execution policies; product questions return in the handoff. Available agents:\n")
    description += "\n".join(f"{role.name}: {role.description} ({role.origin}, {role.source})" for role in roles.values())
    if diagnostics:
        description += "\nDiscovery diagnostics:\n" + "\n".join(diagnostics)
    return ToolDef("agent", description, PARAMETERS)


PARAMETERS = {
    "type": "object", "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 64},
        "task": {"type": "string", "minLength": 1, "maxLength": MAX_BYTES, "pattern": r"\S"},
        "references": {"type": "array", "maxItems": 16, "items": {
            "type": "string", "minLength": 1, "maxLength": 512, "pattern": r"\S"}},
    }, "required": ["name", "task"], "additionalProperties": False,
}
