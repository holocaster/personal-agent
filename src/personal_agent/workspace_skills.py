import os
import re
import stat
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

import yaml

from personal_agent.tools.workspace import _is_excluded, configured_workspace

MAX_SKILL_BYTES = 32 * 1024
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    instructions: str
    fingerprint: bytes = field(repr=False)
    origin: str = "workspace"
    identity: tuple = field(default=(), repr=False)


class SkillError(ValueError):
    pass


def _within(path: Path, parent: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(parent)
        return resolved
    except (OSError, ValueError, RuntimeError) as exc:
        raise SkillError("path is unavailable or outside the workspace skills directory") from exc


def _base(origin: str) -> Path:
    root = configured_workspace().root if origin == "workspace" else Path.home().resolve()
    base_path = root / ".agents" / "skills"
    base = _within(base_path, root)
    if origin == "global" and base != base_path:
        raise SkillError("global skills directory escapes its base")
    return base


def _load(name: str, origin: str) -> Skill:
    if name == "off" or len(name) > 64 or not _NAME.fullmatch(name):
        raise SkillError("invalid skill name")
    base = _base(origin)
    if not base.is_dir():
        raise SkillError("skills path is not a directory")
    directory = _within(base / name, Path.home().resolve() if origin == "global" else base)
    if not directory.is_dir():
        raise SkillError("skill path is not a directory")
    file = _within(directory / "SKILL.md", directory)
    if not file.is_file():
        raise SkillError("SKILL.md is not a regular file")
    try:
        with file.open("rb") as handle:
            data = handle.read(MAX_SKILL_BYTES + 1)
    except OSError as exc:
        raise SkillError("SKILL.md is unreadable") from exc
    if len(data) > MAX_SKILL_BYTES:
        raise SkillError("SKILL.md exceeds 32 KiB")
    if b"\0" in data:
        raise SkillError("SKILL.md is binary")
    try:
        text = data.decode("utf-8")
    except UnicodeError as exc:
        raise SkillError("SKILL.md is not UTF-8") from exc
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise SkillError("SKILL.md needs YAML frontmatter")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise SkillError("SKILL.md needs a closing frontmatter delimiter")
    try:
        metadata = yaml.safe_load("".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise SkillError("invalid YAML frontmatter") from exc
    if not isinstance(metadata, dict) or metadata.get("name") != name or not isinstance(metadata.get("name"), str):
        raise SkillError("skill name does not match its directory")
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise SkillError("skill description must be a non-empty string of at most 1024 characters")
    instructions = "".join(lines[end + 1:])
    if not instructions.strip():
        raise SkillError("SKILL.md needs instructions")
    try:
        stat = file.stat()
    except OSError as exc:
        raise SkillError("SKILL.md is unavailable") from exc
    return Skill(name, description, instructions, sha256(data).digest(), origin,
                 (directory, file, stat.st_dev, stat.st_ino))


def load(name: str) -> Skill:
    try:
        return _load(name, "workspace")
    except SkillError as workspace_error:
        try:
            return _load(name, "global")
        except SkillError:
            raise workspace_error from None


def load_resource(skill: Skill, path: str) -> str:
    supplied = Path(path)
    if not path or len(path) > 512 or "\0" in path or supplied.is_absolute() or ".." in supplied.parts:
        raise SkillError("resource path must be relative, without traversal, and at most 512 characters")
    directory = skill.identity[0]
    candidate = directory / supplied
    file = _within(candidate, directory)
    if _is_excluded(candidate) or _is_excluded(file):
        raise SkillError("requested resource is excluded")
    if not file.is_file():
        raise SkillError("resource must be a regular file")
    try:
        parent = os.open(file.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in file.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            fd = os.open(file.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        finally:
            os.close(parent)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise SkillError("resource must be a regular file")
            data = handle.read(MAX_SKILL_BYTES + 1)
    except OSError as exc:
        raise SkillError("resource is unreadable") from exc
    if len(data) > MAX_SKILL_BYTES:
        raise SkillError("resource exceeds 32 KiB")
    if b"\0" in data:
        raise SkillError("resource is binary")
    try:
        return data.decode("utf-8")
    except UnicodeError as exc:
        raise SkillError("resource is not UTF-8") from exc


def discover() -> tuple[list[Skill], list[str]]:
    skills: dict[str, Skill] = {}
    skipped = []
    for origin, root in (("global", Path.home().resolve()), ("workspace", configured_workspace().root)):
        base_path = root / ".agents" / "skills"
        if not base_path.exists() and not base_path.is_symlink() and not base_path.parent.is_symlink():
            continue
        try:
            base = _base(origin)
            if not base.is_dir():
                raise SkillError("skills path is not a directory")
            children = sorted(base_path.iterdir(), key=lambda child: child.name)
        except (SkillError, OSError) as exc:
            skipped.append(f"{origin}/skills: {exc}")
            continue
        for child in children:
            try:
                directory = _within(child, root if origin == "global" else base)
                if not directory.is_dir():
                    raise SkillError("skill path is not a directory")
                skills[child.name] = _load(child.name, origin)
            except (SkillError, OSError) as exc:
                skipped.append(f"{origin}/{child.name}: {exc}")
    return [skills[name] for name in sorted(skills)], skipped
