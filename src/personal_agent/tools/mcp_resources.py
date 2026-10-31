import asyncio
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import anyio
from mcp import Client, InputRequiredRoundsExceededError, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import BlobResourceContents, InputRequiredResult, TextResourceContents

from personal_agent.tools.builtins import ToolExecutionError

OUTPUT_BYTES = 32 * 1024
TIMEOUT_SECONDS = 30
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


@dataclass(frozen=True)
class ServerConfig:
    name: str
    command: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class PreparedOperation:
    config: ServerConfig
    workspace_root: Path
    operation: str
    uri: str | None
    display_path: str
    preview: str


def parse_config(value: str | None) -> ServerConfig | None:
    if value is None or not value.strip():
        return None
    try:
        data = json.loads(value)
        if not isinstance(data, dict) or not {"name", "command"} <= data.keys() or data.keys() - {"name", "command", "args"}:
            raise ValueError
        name, command, args = data["name"], data["command"], data.get("args", [])
        if (not isinstance(name, str) or not 1 <= len(name) <= 80 or not name.strip()
                or not isinstance(command, str) or not command.strip()
                or not isinstance(args, list) or not all(isinstance(arg, str) for arg in args)
                or any("\x00" in item for item in [name, command, *args])):
            raise ValueError
        return ServerConfig(name, command, tuple(args))
    except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
        raise ValueError("PA_MCP_SERVER must be one valid server object with name, command and string args") from exc


def _size(content: dict) -> int:
    return len(json.dumps(content, ensure_ascii=False).encode("utf-8"))


def _error(server: str, operation: str, reason: str) -> ToolExecutionError:
    return ToolExecutionError(f"MCP server {server!r} {operation}: {reason}")


def prepare_operation(config: ServerConfig, workspace_root: Path, operation: str, arguments: dict) -> PreparedOperation:
    uri = arguments.get("uri") if operation == "read resource" else None
    if uri is not None and (not uri.strip() or not _SCHEME.match(uri)
                            or any(unicodedata.category(char) == "Cc" for char in uri)
                            or "{" in uri or "}" in uri):
        raise _error(config.name, operation, "invalid resource URI")
    identity = f"{config.name} — {operation}"
    if uri is not None:
        identity += f" — {uri}"
    return PreparedOperation(config, workspace_root, operation, uri, identity, identity)


def _fit_item(result: dict, key: str, item: dict, text_key: str | None = None) -> bool:
    result[key].append(item)
    if _size(result) <= OUTPUT_BYTES:
        return True
    result["truncated"] = True
    if text_key is not None:
        original = item[text_key]
        lo, hi = 0, len(original)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            item[text_key] = original[:mid]
            if _size(result) <= OUTPUT_BYTES:
                lo = mid
            else:
                hi = mid - 1
        item[text_key] = original[:lo]
        if _size(result) <= OUTPUT_BYTES:
            return False
    result[key].pop()
    return False


async def _list(client: Client, prepared: PreparedOperation, templates: bool, partial: list) -> dict:
    key = "resource_templates" if templates else "resources"
    result = {"server": prepared.config.name, key: [], "truncated": False}
    cursor = None
    seen = set()
    for page in range(10):
        response = (await client.list_resource_templates(cursor=cursor, cache_mode="bypass") if templates
                    else await client.list_resources(cursor=cursor, cache_mode="bypass"))
        if isinstance(response, InputRequiredResult):
            raise _error(prepared.config.name, prepared.operation, "unsupported interaction")
        partial[:] = [result]
        entries = getattr(response, key)
        for entry in entries:
            if len(result[key]) == 100:
                result["truncated"] = True
                return result
            item = {"uriTemplate" if templates else "uri": entry.uri_template if templates else entry.uri,
                    "name": entry.name}
            if entry.description is not None:
                item["description"] = entry.description
            if entry.mime_type is not None:
                item["mimeType"] = entry.mime_type
            if not _fit_item(result, key, item, "description" if "description" in item else None):
                if result[key] and result[key][-1] is item:
                    return result
                for optional in ("description", "mimeType"):
                    item.pop(optional, None)
                    if _fit_item(result, key, item):
                        result["truncated"] = True
                        return result
                if not result[key]:
                    raise _error(prepared.config.name, prepared.operation, "required provenance exceeds output limit")
                return result
        next_cursor = response.next_cursor
        if next_cursor is None:
            return result
        if next_cursor in seen or page == 9:
            result["truncated"] = True
            return result
        seen.add(next_cursor)
        cursor = next_cursor
    return result


async def _read(client: Client, prepared: PreparedOperation) -> dict:
    response = await client.read_resource(prepared.uri, cache_mode="bypass")
    if isinstance(response, InputRequiredResult):
        raise _error(prepared.config.name, prepared.operation, "unsupported interaction")
    if any(isinstance(item, BlobResourceContents) for item in response.contents):
        raise _error(prepared.config.name, prepared.operation, "unsupported binary content")
    result = {"server": prepared.config.name, "uri": prepared.uri, "contents": [], "truncated": False}
    if _size(result) > OUTPUT_BYTES:
        raise _error(prepared.config.name, prepared.operation, "required provenance exceeds output limit")
    for item in response.contents:
        if not isinstance(item, TextResourceContents):
            raise _error(prepared.config.name, prepared.operation, "unsupported content")
        content = {"uri": item.uri, "text": item.text}
        if item.mime_type is not None:
            content["mimeType"] = item.mime_type
        if not _fit_item(result, "contents", content, "text"):
            if not result["contents"]:
                raise _error(prepared.config.name, prepared.operation, "required provenance exceeds output limit")
            break
    return result


async def _execute(prepared: PreparedOperation) -> dict:
    params = StdioServerParameters(command=prepared.config.command, args=list(prepared.config.args),
                                   cwd=prepared.workspace_root)
    partial = []
    with open(os.devnull, "w") as sink:
        with anyio.move_on_after(TIMEOUT_SECONDS):
            async with Client(stdio_client(params, errlog=sink), input_required_max_rounds=0) as client:
                if client.server_capabilities.resources is None:
                    raise _error(prepared.config.name, prepared.operation, "Resources capability unavailable")
                if prepared.operation == "read resource":
                    return await _read(client, prepared)
                return await _list(client, prepared, prepared.operation == "list resource templates", partial)
    if not partial:
        raise TimeoutError
    partial[0]["truncated"] = True
    return partial[0]


def _find(error: BaseException, kind: type[BaseException]) -> BaseException | None:
    if isinstance(error, kind):
        return error
    if isinstance(error, BaseExceptionGroup):
        return next((found for child in error.exceptions if (found := _find(child, kind))), None)
    return None


def apply_operation(prepared: PreparedOperation) -> dict:
    suffix = f" [{prepared.uri}]" if prepared.uri is not None else ""
    try:
        return asyncio.run(_execute(prepared))
    except Exception as exc:
        specific = _find(exc, ToolExecutionError)
        if specific is not None:
            raise ToolExecutionError(f"{specific}{suffix}") from exc
        if isinstance(exc, TimeoutError):
            reason = "timed out"
        elif _find(exc, InputRequiredRoundsExceededError) is not None:
            reason = "unsupported interaction"
        else:
            reason = "server request failed"
        raise _error(prepared.config.name, prepared.operation, reason + suffix) from exc
