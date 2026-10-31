import dataclasses
import json
import os

from personal_agent.providers import http
from personal_agent.providers.contract import AssistantMessage, ToolCall, ToolDef, validate_output_allowance

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
COST_ESTIMATED = True
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
PROVIDER_LABEL = "gemini"


def is_retryable(exc: BaseException) -> bool:
    return http.is_retryable(exc, RETRYABLE_HTTP_CODES)


def _to_wire_contents(messages: list[dict]) -> list[dict]:
    """Translate normalized messages into Gemini `contents`. Used whole for a
    fresh loop/cross-Provider history, or for just the tail not yet covered by
    an active loop's `replay` (see call())."""
    contents: list[dict] = []
    pending_responses: list[dict] = []

    def flush() -> None:
        if pending_responses:
            contents.append({"role": "user", "parts": pending_responses.copy()})
            pending_responses.clear()

    for message in messages:
        role = message["role"]
        if role == "tool_result":
            response = message["content"] if isinstance(message["content"], dict) else {"result": message["content"]}
            function_response = {"name": message["name"], "response": response}
            # Only echo an id back when it came from the vendor (R08); an id we
            # generated locally for correlation is never invented onto the wire.
            if message.get("id") and not message.get("id_is_generated"):
                function_response["id"] = message["id"]
            pending_responses.append({"functionResponse": function_response})
            continue

        flush()
        if role == "user":
            contents.append({"role": "user", "parts": [{"text": message["content"]}]})
        elif role == "assistant":
            tool_calls = message.get("tool_calls") or []
            parts = []
            if message.get("content"):
                parts.append({"text": message["content"]})
            for call in tool_calls:
                function_call = {"name": call["name"], "args": call.get("arguments") or {}}
                if call.get("id") and not call.get("id_is_generated"):
                    function_call["id"] = call["id"]
                parts.append({"functionCall": function_call})
            contents.append({"role": "model", "parts": parts})
        else:
            raise ValueError(f"unsupported normalized message role: {role!r}")
    flush()
    return contents


def _parse_assistant(parts: list[dict], separator="\n") -> AssistantMessage:
    texts = [part["text"] for part in parts if "text" in part and not part.get("thought")]
    text = separator.join(texts) if texts else None
    tool_calls = []
    for index, part in enumerate(parts):
        if "functionCall" not in part:
            continue
        function_call = part["functionCall"]
        # Older Gemini responses omit an id; generate a stable internal one for
        # our own correlation without touching the original replay payload (R08).
        vendor_id = function_call.get("id")
        call_id = vendor_id or f"gemini-call-{index}"
        tool_calls.append(
            ToolCall(
                id=call_id,
                name=function_call["name"],
                arguments=function_call.get("args") or {},
                id_is_generated=vendor_id is None,
            )
        )
    return AssistantMessage(text=text, tool_calls=tuple(tool_calls))


def prepare_input(system: str, messages: list[dict], tools=None, replay=None) -> dict:
    if replay is not None:
        contents = replay["contents"] + _to_wire_contents(messages[replay["consumed"] :])
    else:
        contents = _to_wire_contents(messages)

    payload = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents}
    if tools:
        payload["tools"] = [
            {"functionDeclarations": [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools]}
        ]
    return payload


def begin_replay(history: list[dict]) -> dict:
    contents = _to_wire_contents(history)
    return {"contents": contents, "consumed": len(history),
            "active_start": len(history), "active_contents_start": len(contents)}


def rebase_replay(replay: dict, history: list[dict]) -> dict:
    contents = _to_wire_contents(history)
    return {**replay, "contents": contents + replay["contents"][replay["active_contents_start"]:],
            "consumed": len(history) + replay["consumed"] - replay["active_start"],
            "active_start": len(history), "active_contents_start": len(contents)}


def _stream_response(url, payload, headers, model, tools, on_text):
    usage, raw_usage = {}, {}
    parts = []
    finish = None
    assembled_bytes, tool_count = 0, 0
    try:
        with http.post_sse(url, payload, headers) as events:
            for event, raw in events:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("Malformed Gemini stream frame")
                if "usageMetadata" in data:
                    http.native_stream_usage(data["usageMetadata"], raw_usage, usage, PROVIDER_LABEL, model)
                http.raise_for_response_error(data, PROVIDER_LABEL, model, bool(tools), usage)
                feedback = data.get("promptFeedback")
                if event == "error" or feedback is not None and (
                        not isinstance(feedback, dict) or feedback.get("blockReason")):
                    raise ValueError("Gemini stream error or blocked prompt")
                candidates = data.get("candidates", [])
                if not isinstance(candidates, list):
                    raise ValueError("Malformed Gemini stream candidates")
                selected = []
                for item in candidates:
                    if (not isinstance(item, dict) or type(item.get("index", 0)) is not int
                            or item.get("index", 0) < 0):
                        raise ValueError("Invalid Gemini candidate index")
                    if item.get("index", 0) == 0:
                        selected.append(item)
                if len(selected) > 1:
                    raise ValueError("Duplicate Gemini stream candidate")
                if not selected:
                    continue
                item = selected[0]
                finished = finish is not None
                reason = item.get("finishReason")
                if reason is not None:
                    if reason not in {"STOP", "MAX_TOKENS"} or finish not in {None, reason}:
                        raise ValueError("Invalid Gemini finish reason")
                    finish = reason
                content = item.get("content")
                if content is None:
                    continue
                if not isinstance(content, dict) or content.get("role", "model") != "model":
                    raise ValueError("Malformed Gemini stream content")
                new_parts = content.get("parts", [])
                if not isinstance(new_parts, list):
                    raise ValueError("Malformed Gemini stream parts")
                for part in new_parts:
                    assembled_bytes += len(json.dumps(part, ensure_ascii=False).encode("utf-8"))
                    if assembled_bytes > http.MAX_RESPONSE_BYTES:
                        raise ValueError("Stream response exceeds 8 MiB limit")
                    if (not isinstance(part, dict) or not part
                            or part.keys() - {"text", "functionCall", "thought", "thoughtSignature"}
                            or "thought" in part and type(part["thought"]) is not bool
                            or "thoughtSignature" in part and not isinstance(part["thoughtSignature"], str)
                            or "text" in part and not isinstance(part["text"], str)
                            or "text" in part and "functionCall" in part
                            or not (part.keys() & {"text", "functionCall", "thoughtSignature"})):
                        raise ValueError("Malformed Gemini stream part")
                    if finished and ("functionCall" in part or part.get("text") and not part.get("thought")):
                        raise ValueError("Gemini content after finish reason")
                    if "functionCall" in part:
                        call = part["functionCall"]
                        tool_count += 1
                        if (tool_count > 16 or not isinstance(call, dict)
                                or not isinstance(call.get("name"), str) or not call["name"]
                                or "args" in call and call["args"] is not None and not isinstance(call["args"], dict)
                                or "id" in call and call["id"] is not None and (
                                    not isinstance(call["id"], str) or not call["id"])):
                            raise ValueError("Malformed Gemini function call")
                    parts.append(part)
                    if part.get("text") and not part.get("thought"):
                        on_text(part["text"])
        if finish is None or not (tool_count or any(part.get("text") and not part.get("thought") for part in parts)):
            raise ValueError("Incomplete response: Gemini stream lacks usable completed candidate")
        return parts, finish, usage
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
    payload = {**prepared, "generationConfig": {"maxOutputTokens": max_output_tokens}}
    contents = prepared["contents"]
    headers = {"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "") if api_key is None else api_key}

    usage = None
    try:
        if on_text is not None:
            url = API_URL.format(model=model).replace(":generateContent", ":streamGenerateContent?alt=sse")
            raw_parts, finish, usage = _stream_response(url, payload, headers, model, tools, on_text)
        else:
            data = http.post_json(API_URL.format(model=model), payload, headers)
            usage = http.response_usage(data, PROVIDER_LABEL, model)
            http.raise_for_response_error(data, PROVIDER_LABEL, model, bool(tools), usage)
            raw_parts = (data["candidates"][0].get("content") or {}).get("parts") or []
            finish = data["candidates"][0].get("finishReason")

        # Preserve the exact original parts (including any thoughtSignature) for
        # same-model replay across Tool rounds within one active loop (R08).
        assistant = _parse_assistant(raw_parts, separator="" if on_text is not None else "\n")
        new_replay = {"contents": [*contents, {"role": "model", "parts": raw_parts}], "consumed": len(messages) + 1}
        new_replay.update(active_start=replay.get("active_start", 0) if replay else 0,
                          active_contents_start=replay.get("active_contents_start", 0) if replay else 0)
        assistant = dataclasses.replace(assistant, replay=new_replay, termination=finish)
    except Exception as exc:
        http.raise_for_provider_error(exc, PROVIDER_LABEL, model, bool(tools), usage)
        raise

    return assistant, usage
