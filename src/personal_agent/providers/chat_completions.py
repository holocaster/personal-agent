"""Shared Chat Completions (OpenAI, OpenRouter) request/response translation (R08)."""

import json
import math

from personal_agent.providers import http
from personal_agent.providers.contract import AssistantMessage, ToolCall, ToolDef


def to_wire_tools(tools: tuple[ToolDef, ...] | None) -> list[dict] | None:
    if not tools:
        return None
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
        for t in tools
    ]


def to_wire_messages(system: str, messages: list[dict]) -> list[dict]:
    wire = [{"role": "system", "content": system}]
    for message in messages:
        role = message["role"]
        if role == "user":
            wire.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            entry = {"role": "assistant", "content": message.get("content")}
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments_raw"]
                            if call.get("arguments_raw") is not None
                            else json.dumps(call.get("arguments") or {}),
                        },
                    }
                    for call in tool_calls
                ]
            wire.append(entry)
        elif role == "tool_result":
            content = message["content"]
            wire.append(
                {
                    "role": "tool",
                    "tool_call_id": message["id"],
                    "content": content if isinstance(content, str) else json.dumps(content),
                }
            )
        else:
            raise ValueError(f"unsupported normalized message role: {role!r}")
    return wire


def parse_response(data: dict) -> AssistantMessage:
    message = data["choices"][0]["message"]
    text = message.get("content")
    tool_calls = []
    for raw in message.get("tool_calls") or []:
        raw_arguments = raw["function"]["arguments"]
        try:
            parsed = json.loads(raw_arguments)
            if not isinstance(parsed, dict):
                parsed = None
        except (json.JSONDecodeError, TypeError):
            parsed = None
        tool_calls.append(
            ToolCall(id=raw.get("id") or "", name=raw["function"]["name"], arguments=parsed, arguments_raw=raw_arguments)
        )
    return AssistantMessage(text=text, tool_calls=tuple(tool_calls), termination=data["choices"][0].get("finish_reason"))


def prepare_input(system: str, messages: list[dict], tools=None, replay=None) -> dict:
    prepared = {"messages": to_wire_messages(system, messages)}
    wire_tools = to_wire_tools(tools)
    if wire_tools:
        prepared["tools"] = wire_tools
    return prepared


def _stream_usage(snapshot: object, raw_usage: dict, usage: dict, provider: str, model: str) -> None:
    if snapshot is None:
        return
    if not isinstance(snapshot, dict):
        raise ValueError("Malformed stream usage")
    invalid = []
    fields = {"prompt_tokens", "completion_tokens", "total_tokens", "cost"}
    for field in fields & snapshot.keys():
        value = snapshot[field]
        try:
            valid = (type(value) in {int, float} and math.isfinite(value) and value >= 0
                     if field == "cost" else type(value) is int and value >= 0)
        except OverflowError:
            valid = False
        if valid:
            raw_usage[field] = value
        else:
            if field != "cost":
                raw_usage.setdefault(field, value)
            invalid.append(field)
    if "prompt_tokens_details" in snapshot:
        details = snapshot["prompt_tokens_details"]
        if not isinstance(details, dict):
            raw_usage.setdefault("prompt_tokens_details", details)
            invalid.append("prompt_tokens_details")
        else:
            cache = raw_usage.setdefault("prompt_tokens_details", {})
            for field in {"cached_tokens", "cache_write_tokens"} & details.keys():
                value = details[field]
                if type(value) is int and value >= 0:
                    cache[field] = value
                else:
                    cache.setdefault(field, value)
                    invalid.append(field)
    usage.update(http.response_usage({"usage": raw_usage}, provider, model))
    if invalid:
        if provider != "openrouter":
            usage["cost"] = None
        raise ValueError("Invalid stream usage fields: " + ", ".join(sorted(invalid)))


def stream_response(url: str, payload: dict, headers: dict, provider: str, model: str, tools, on_text):
    usage, raw_usage = {}, {}
    text, calls = [], {}
    finish, done, generation_id = None, False, None
    assembled_bytes = 0

    def fragment(value):
        nonlocal assembled_bytes
        if not isinstance(value, str):
            raise ValueError("Malformed stream text or Tool fragment")
        assembled_bytes += len(value.encode("utf-8"))
        if assembled_bytes > http.MAX_RESPONSE_BYTES:
            raise ValueError("Stream response exceeds 8 MiB limit")
        return value

    try:
        with http.post_sse(url, payload, headers) as events:
            for event, raw in events:
                if done:
                    raise ValueError("Unexpected data after stream termination")
                if raw == "[DONE]":
                    if finish is None:
                        raise ValueError("Stream terminated without a finish reason")
                    done = True
                    continue
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("Malformed stream frame")
                _stream_usage(data.get("usage"), raw_usage, usage, provider, model)
                http.raise_for_response_error(data, provider, model, bool(tools), usage)
                if event == "error":
                    raise ValueError("Provider stream error")
                if "id" in data:
                    if not isinstance(data["id"], str):
                        raise ValueError("Malformed generation id")
                    generation_id = data["id"]
                choices = data.get("choices")
                if not isinstance(choices, list):
                    raise ValueError("Malformed stream choices")
                selected = []
                for item in choices:
                    if not isinstance(item, dict) or type(item.get("index")) is not int or item["index"] < 0:
                        raise ValueError("Malformed stream choice index")
                    if item["index"] == 0:
                        selected.append(item)
                if len(selected) > 1:
                    raise ValueError("Duplicate stream choice")
                if not selected:
                    continue
                item = selected[0]
                delta = item.get("delta")
                if not isinstance(delta, dict):
                    raise ValueError("Malformed stream delta")
                reason = item.get("finish_reason")
                if reason is not None and reason not in {"stop", "length", "tool_calls", "content_filter", "function_call"}:
                    raise ValueError("Invalid stream finish reason")
                if finish is not None:
                    empty = (delta.get("content") in (None, "") and delta.get("tool_calls") in (None, [])
                             and delta.get("role", "assistant") == "assistant"
                             and not (delta.keys() - {"content", "role", "tool_calls"}))
                    if provider != "openrouter" or not empty or reason != finish:
                        raise ValueError("Contradictory stream finish")
                    continue
                if delta.get("role", "assistant") != "assistant":
                    raise ValueError("Invalid stream role")
                content = delta.get("content")
                if content is not None:
                    text.append(fragment(content))
                    if content:
                        on_text(content)
                tool_deltas = delta.get("tool_calls")
                if tool_deltas is not None:
                    if not isinstance(tool_deltas, list) or len(tool_deltas) > 16:
                        raise ValueError("Malformed stream Tool batch")
                    for tool in tool_deltas:
                        if not isinstance(tool, dict) or type(tool.get("index")) is not int or not 0 <= tool["index"] < 16:
                            raise ValueError("Invalid stream Tool index")
                        call = calls.setdefault(tool["index"], {"id": "", "name": "", "arguments": ""})
                        if tool.get("type", "function") != "function":
                            raise ValueError("Invalid stream Tool type")
                        if "id" in tool:
                            call["id"] += fragment(tool["id"])
                        function = tool.get("function", {})
                        if not isinstance(function, dict):
                            raise ValueError("Malformed stream Tool function")
                        for field in {"name", "arguments"} & function.keys():
                            call[field] += fragment(function[field])
                if reason is not None:
                    finish = reason
        if not done or finish is None:
            raise ValueError("Incomplete response: stream ended before termination")
        if calls and (finish not in {"tool_calls", "function_call", "length"} or
                      any(not call["id"] or not call["name"] for call in calls.values())):
            raise ValueError("Incomplete stream Tool calls")
        if finish in {"tool_calls", "function_call"} and not calls:
            raise ValueError("Stream finish has no Tool calls")
        message = {"content": "".join(text) if text else None, "tool_calls": [
            {"id": call["id"], "function": {"name": call["name"], "arguments": call["arguments"]}}
            for _, call in sorted(calls.items())]}
        data = {"id": generation_id, "choices": [{"message": message, "finish_reason": finish}]}
        return parse_response(data), usage, data
    except BaseException as exc:
        http.raise_for_provider_error(exc, provider, model, bool(tools), usage or None)
        raise
