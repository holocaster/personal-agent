import os
import tempfile
from pathlib import Path

from personal_agent.routing.runtime_config import MANAGED_ENV_VARS


def home_env_path() -> Path:
    return Path.home() / ".personal_agent" / ".env"


def read_env_values(path: Path | None = None) -> dict[str, str]:
    target = path if path is not None else home_env_path()
    try:
        with target.open("r", encoding="utf-8", newline="") as env_file:
            content = env_file.read()
    except FileNotFoundError:
        return {}
    return _parse_env_values(content)


def save_settings(settings: dict[str, str], path: Path | None = None) -> None:
    unsupported = set(settings).difference(MANAGED_ENV_VARS)
    if unsupported:
        raise ValueError(f"unsupported configuration setting: {', '.join(sorted(unsupported))}")
    target = path if path is not None else home_env_path()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with target.open("r", encoding="utf-8", newline="") as env_file:
            original = env_file.read()
    except FileNotFoundError:
        original = ""
    contents = original
    for variable, value in settings.items():
        contents = _replace_setting(contents, variable, _format_env_value(value))
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(contents)
        if os.name == "posix":
            temporary_path.chmod(0o600)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _parse_env_values(content: str) -> dict[str, str]:
    values = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values.setdefault(key, value)
    return values


def _replace_setting(content: str, variable: str, value: str) -> str:
    output = []
    found = False
    for line in content.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        stripped = body.strip()
        key = stripped.partition("=")[0].strip() if stripped and not stripped.startswith("#") else None
        if key == variable:
            output.append(f"{variable}={value}{ending}")
            found = True
        else:
            output.append(line)
    if not found:
        if output and not output[-1].endswith(("\n", "\r")):
            output.append("\n")
        output.append(f"{variable}={value}\n")
    return "".join(output)


def _format_env_value(value: str) -> str:
    if value and value[0] in "\"'" and (len(value) == 1 or value[-1] == value[0]):
        wrapper = "'" if value[0] == '"' else '"'
        return f"{wrapper}{value}{wrapper}"
    return value
