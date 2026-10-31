import json
import os

from personal_agent.providers import http
from personal_agent.providers.contract import AssistantMessage, ToolCall, ToolDef, validate_output_allowance

API_URL = "https://api.anthropic.com/v1/messages"
COST_ESTIMATED = True
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504, 529}
PROVIDER_LABEL = "anthropic"


def is_retryable(exc: BaseException) -> bool:
    return http.is_retryable(exc, RETRYABLE_HTTP_CODES)


def _to_wire_messages(messages: list[dict]) -> list[dict]:
    wire: list[dict] = []
    pending_results: list[dict] = []

    def flush() -> None:
        if pending_results:
            wire.append({"role": "user", "content": pending_results.copy()})
            pending_results.clear()

    for message in messages:
        role = message["role"]
        if role == "tool_result":
            content = message["content"]
            block = {
                "type": "tool_result",
                "tool_use_id": message["id"],
                "content": content if isinstance(content, str) else json.dumps(content),
            }
            if message.get("is_error"):
                block["is_error"] = True
            pending_results.append(block)
            continue

        flush()
        if role == "user":
            wire.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                blocks = []
                if message.get("content"):
                    blocks.append({"type": "text", "text": message["content"]})
                for call in tool_calls:
                    blocks.append(
                        {"type": "tool_use", "id": call["id"], "name": call["name"], "input": call.get("arguments") or {}}
                    )
                wire.append({"role": "assistant", "content": blocks})
            else:
                wire.append({"role": "assistant", "content": message["content"]})
        else:
            raise ValueError(f"unsupported normalized message role: {role!r}")
    flush()
    return wire


def _parse_response(data: dict) -> AssistantMessage:
    blocks = data["content"]
    texts = [block["text"] for block in blocks if block["type"] == "text"]
    text = "\n".join(texts) if texts else None
    tool_calls = tuple(
        ToolCall(id=block["id"], name=block["name"], arguments=block["input"], arguments_raw=block.get("arguments_raw"))
        for block in blocks
        if block["type"] == "tool_use"
    )
    return AssistantMessage(text=text, tool_calls=tool_calls, termination=data.get("stop_reason"))


def prepare_input(system: str, messages: list[dict], tools=None, replay=None) -> dict:
    prepared = {"system": system, "messages": _to_wire_messages(messages)}
    if tools:
        prepared["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
    return prepared


def _stream_response(payload, headers, model, tools, on_text):
    usage, raw_usage = {}, {}
    blocks = []
    active, finish = None, None
    started, stopped, ending = False, False, False
    assembled_bytes, tool_count, text_count = 0, 0, 0
    try:
        with http.post_sse(API_URL, {**payload, "stream": True}, headers) as events:
            for event, raw in events:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("Malformed Anthropic stream event")
                if "usage" in data:
                    http.native_stream_usage(data["usage"], raw_usage, usage, PROVIDER_LABEL, model)
                http.raise_for_response_error(data, PROVIDER_LABEL, model, bool(tools), usage)
                if not isinstance(data.get("type"), str):
                    raise ValueError("Malformed Anthropic stream event")
                kind = data["type"]
                if event and event != kind:
                    raise ValueError("Contradictory Anthropic stream event")
                if stopped:
                    raise ValueError("Unexpected data after message_stop")
                if kind == "error":
                    raise ValueError("Anthropic stream error")
                if kind == "ping":
                    continue
                if kind == "message_start":
                    message = data.get("message")
                    if (started or not isinstance(message, dict) or message.get("role") != "assistant"
                            or message.get("content") != [] or message.get("stop_reason") is not None):
                        raise ValueError("Invalid Anthropic message_start")
                    if "usage" in message:
                        http.native_stream_usage(message["usage"], raw_usage, usage, PROVIDER_LABEL, model)
                    started = True
                    continue
                if not started:
                    raise ValueError("Anthropic event before message_start")
                if kind == "message_delta":
                    if active is not None:
                        raise ValueError("Anthropic message_delta before block stop")
                    ending = True
                    delta = data.get("delta")
                    if not isinstance(delta, dict):
                        raise ValueError("Malformed Anthropic message_delta")
                    reason = delta.get("stop_reason")
                    if reason is not None:
                        if reason not in {"end_turn", "stop_sequence", "tool_use", "max_tokens", "pause_turn",
                                          "refusal", "model_context_window_exceeded"} or finish not in {None, reason}:
                            raise ValueError("Invalid Anthropic stop reason")
                        finish = reason
                    continue
                if kind == "message_stop":
                    if active is not None or finish is None:
                        raise ValueError("Incomplete Anthropic message_stop")
                    stopped = True
                    continue
                if kind not in {"content_block_start", "content_block_delta", "content_block_stop"}:
                    continue
                index = data.get("index")
                if type(index) is not int or index < 0 or ending:
                    raise ValueError("Invalid Anthropic block index or order")
                if kind == "content_block_start":
                    block = data.get("content_block")
                    if active is not None or index != len(blocks) or not isinstance(block, dict):
                        raise ValueError("Invalid Anthropic block start")
                    block = dict(block)
                    assembled_bytes += len(json.dumps(block, ensure_ascii=False).encode("utf-8"))
                    if assembled_bytes > http.MAX_RESPONSE_BYTES:
                        raise ValueError("Stream response exceeds 8 MiB limit")
                    block_type = block.get("type")
                    if block_type == "text":
                        if not isinstance(block.get("text"), str):
                            raise ValueError("Malformed Anthropic text block")
                        if text_count:
                            on_text("\n")
                        text_count += 1
                        if block["text"]:
                            on_text(block["text"])
                    elif block_type == "tool_use":
                        tool_count += 1
                        if (tool_count > 16 or not isinstance(block.get("id"), str) or not block["id"]
                                or not isinstance(block.get("name"), str) or not block["name"]
                                or not isinstance(block.get("input"), dict)):
                            raise ValueError("Malformed Anthropic Tool block")
                    elif block_type == "thinking":
                        if not isinstance(block.get("thinking"), str) or not isinstance(block.get("signature"), str):
                            raise ValueError("Malformed Anthropic thinking block")
                    elif block_type == "redacted_thinking":
                        if not isinstance(block.get("data"), str):
                            raise ValueError("Malformed Anthropic redacted thinking block")
                    else:
                        raise ValueError("Unsupported Anthropic content block")
                    blocks.append(block)
                    active = index
                else:
                    if active != index:
                        raise ValueError("Invalid Anthropic block delta or stop")
                    block = blocks[index]
                    if kind == "content_block_stop":
                        if "arguments_raw" in block:
                            try:
                                arguments = json.loads(block["arguments_raw"])
                            except ValueError:
                                arguments = None
                            block["input"] = arguments if isinstance(arguments, dict) else None
                        active = None
                        continue
                    delta = data.get("delta")
                    if not isinstance(delta, dict):
                        raise ValueError("Malformed Anthropic block delta")
                    fields = {"text_delta": ("text", "text", "text"),
                              "input_json_delta": ("tool_use", "partial_json", "arguments_raw"),
                              "thinking_delta": ("thinking", "thinking", "thinking"),
                              "signature_delta": ("thinking", "signature", "signature")}
                    field = fields.get(delta.get("type"))
                    if field is None or block["type"] != field[0] or not isinstance(delta.get(field[1]), str):
                        raise ValueError("Invalid Anthropic block delta type")
                    assembled_bytes += len(delta[field[1]].encode("utf-8"))
                    if assembled_bytes > http.MAX_RESPONSE_BYTES:
                        raise ValueError("Stream response exceeds 8 MiB limit")
                    block[field[2]] = block.get(field[2], "") + delta[field[1]]
                    if field[0] == "text" and delta[field[1]]:
                        on_text(delta[field[1]])
        if not stopped:
            raise ValueError("Incomplete response: Anthropic stream ended before message_stop")
        if finish == "tool_use" and not tool_count or tool_count and finish not in {"tool_use", "max_tokens", "model_context_window_exceeded"}:
            raise ValueError("Contradictory Anthropic Tool termination")
        return _parse_response({"content": blocks, "stop_reason": finish}), usage
    except BaseException as exc:
        http.raise_for_provider_error(exc, PROVIDER_LABEL, model, bool(tools), usage or None)
        raise


def call(
    model: str,
    system: str,
    messages: list[dict],
    tools: tuple[ToolDef, ...] | None = None,
    replay: object = None,
    api_key: str | None = None,
    max_output_tokens: int = 16000,
    prepared_input: dict | None = None,
    on_text=None,
    session_id: str | None = None,
) -> tuple[AssistantMessage, dict]:
    validate_output_allowance(max_output_tokens)
    prepared = prepared_input if prepared_input is not None else prepare_input(system, messages, tools, replay)
    payload = {"model": model, **prepared, "max_tokens": max_output_tokens, "cache_control": {"type": "ephemeral"}}
    headers = {"x-api-key": os.environ.get("ANTHROPIC_API_KEY", "") if api_key is None else api_key,
               "anthropic-version": "2023-06-01"}
    if on_text is not None:
        return _stream_response(payload, headers, model, tools, on_text)

    usage = None
    try:
        data = http.post_json(
            API_URL,
            payload,
            headers,
        )
        usage = http.response_usage(data, PROVIDER_LABEL, model)
        http.raise_for_response_error(data, PROVIDER_LABEL, model, bool(tools), usage)
        assistant = _parse_response(data)
    except Exception as exc:
        http.raise_for_provider_error(exc, PROVIDER_LABEL, model, bool(tools), usage)
        raise

    return assistant, usage
