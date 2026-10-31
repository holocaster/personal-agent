import json
from urllib.error import HTTPError

from personal_agent import chatgpt_auth
from personal_agent.providers import http
from personal_agent.providers.contract import AssistantMessage, ContextOverflowError, ToolCall, validate_output_allowance

API_URL = "https://api.openai.com/v1/responses"
NAMESPACE = "personal_agent"
COST_ESTIMATED = False
PROVIDER_LABEL = "chatgpt"


class ChatGPTError(RuntimeError):
    def __init__(self, message, *, code=None, param=None, status=None, request_id=None):
        super().__init__(chatgpt_auth.safe(message))
        self.code = chatgpt_auth.safe(code) if isinstance(code, str) else None
        self.param = chatgpt_auth.safe(param) if isinstance(param, str) else None
        self.status = status
        self.request_id = chatgpt_auth.safe(request_id) if isinstance(request_id, str) else None


def is_retryable(exc):
    if isinstance(exc, ChatGPTError):
        if exc.code in {"subscription_sharing_usage_limit_exceeded", "subscription_sharing_user_not_eligible",
                        "subscription_sharing_unsupported_capability", "subscription_sharing_route_not_supported",
                        "subscription_sharing_invalid_user", "permission_denied", "insufficient_permissions",
                        "content_policy_violation", "policy_violation", "model_not_found", "unsupported_parameter",
                        "chatpass_v2_scope_not_authorized",
                        "chatpass_v2_invalid_authorization_context", "context_length_exceeded"}:
            return False
        return (exc.code in {"subscription_sharing_usage_unavailable", "subscription_sharing_user_unavailable",
                            "server_error", "rate_limit_exceeded", "rate_limit_error"}
                or exc.status in {429, 500, 502, 503, 504})
    return isinstance(exc, chatgpt_auth.TemporaryError) or http.is_retryable(exc, {429, 500, 502, 503, 504})


def _failure(data, status=None, request_id=None):
    error = data.get("error", data) if isinstance(data, dict) else {}
    if not isinstance(error, dict):
        error = {"message": error}
    code = error.get("code") if isinstance(error.get("code"), str) else None
    param = error.get("param") if isinstance(error.get("param"), str) else None
    message = error.get("message", data.get("detail", "ChatGPT inference failed"))
    if not isinstance(message, str):
        message = json.dumps(message, ensure_ascii=False)
    if code == "subscription_sharing_usage_limit_exceeded":
        message = "Cota atingida. Manage usage: " + chatgpt_auth.USAGE_URL + ". Wait or select another Provider, then /retry."
    elif status in {401, 403}:
        message += "; check account and plan permission with /connect chatgpt or select another Provider"
    failure = ChatGPTError(message[:1200], code=code, param=param, status=status, request_id=request_id)
    if code == "context_length_exceeded":
        overflow = ContextOverflowError(str(failure))
        overflow.code, overflow.param, overflow.status, overflow.request_id = failure.code, failure.param, failure.status, failure.request_id
        failure = overflow
    return failure


def _json(raw):
    try:
        return chatgpt_auth._json(raw)
    except chatgpt_auth.AuthError:
        raise ValueError("Malformed Responses JSON") from None


def _usage(snapshot, usage):
    if snapshot is None:
        return
    if not isinstance(snapshot, dict):
        invalid = usage.setdefault("invalid_usage", [])
        if "usage" not in invalid:
            invalid.append("usage")
        return
    fields = {"prompt_tokens": snapshot.get("input_tokens"), "completion_tokens": snapshot.get("output_tokens")}
    present = {key for key, source in (("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens"))
               if source in snapshot}
    for source, field in (("input_tokens_details", "cached_tokens"), ("output_tokens_details", "reasoning_tokens")):
        if source in snapshot:
            detail = snapshot[source]
            if isinstance(detail, dict):
                if field in detail:
                    fields[field] = detail[field]
                    present.add(field)
            elif detail is not None:
                fields[field] = None
                present.add(field)
    for field in present:
        value = fields[field]
        if type(value) is int and value >= 0:
            usage[field] = value
        else:
            usage.setdefault("invalid_usage", [])
            if field not in usage["invalid_usage"]:
                usage["invalid_usage"].append(field)
    for field, total in (("cached_tokens", "prompt_tokens"), ("reasoning_tokens", "completion_tokens")):
        if field in usage and total in usage and usage[field] > usage[total]:
            del usage[field]
            usage.setdefault("invalid_usage", []).append(field)


def _normalized(messages):
    items = []
    for message in messages:
        role = message["role"]
        if role in {"user", "assistant"}:
            if message.get("content") is not None:
                items.append({"role": role, "content": message["content"]})
            for call in message.get("tool_calls") or ():
                items.append({"type": "function_call", "call_id": call["id"], "name": call["name"],
                              "namespace": NAMESPACE, "arguments": call["arguments_raw"]
                              if call.get("arguments_raw") is not None else json.dumps(call["arguments"])})
        elif role == "tool_result":
            value = message["content"]
            items.append({"type": "function_call_output", "call_id": message["id"],
                          "output": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)})
        else:
            raise ValueError("Unsupported normalized Responses role")
    return items


def prepare_input(system, messages, tools=None, replay=None):
    items = _normalized(messages) if replay is None else replay["items"] + _normalized(messages[replay["consumed"]:])
    prepared = {"instructions": system, "input": items}
    if tools:
        prepared["tools"] = [{"type": "namespace", "name": NAMESPACE, "description": "Personal Agent local Tools",
                              "tools": [{"type": "function", "name": tool.name, "description": tool.description,
                                         "parameters": tool.parameters, "strict": False} for tool in tools]}]
    return prepared


def rebase_replay(replay, history, prefix=None):
    prefix = _normalized(history) if prefix is None else prefix
    return {"items": prefix + replay["items"][replay["active_items_start"]:],
            "consumed": len(history) + replay["consumed"] - replay["active_start"],
            "active_start": len(history), "active_items_start": len(prefix)}


def bound(replay, model, binding):
    return (binding is not None and isinstance(replay, dict)
            and (replay.get("provider"), replay.get("model"), replay.get("registration"))
            == (PROVIDER_LABEL, model, binding.registration))


def history_items(turns, model, binding):
    items = []
    for turn in turns:
        replay = getattr(turn, "replay", None)
        items += replay["items"] if bound(replay, model, binding) else _normalized(list(turn))
    return items


def turn_replay(model, binding, replay, messages):
    envelope = {"version": 1, "provider": PROVIDER_LABEL, "model": model, "registration": binding.registration,
                "items": replay["items"][replay["active_items_start"]:]}
    try:
        validate_turn_replay(envelope, messages)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return envelope


def validate_turn_replay(replay, messages):
    if (not isinstance(replay, dict) or set(replay) != {"version", "provider", "model", "registration", "items"}
            or replay["version"] != 1 or replay["provider"] != PROVIDER_LABEL
            or not isinstance(replay["model"], str) or not replay["model"].strip()
            or not chatgpt_auth.valid_reference(replay["registration"])):
        raise ValueError("Responses replay binding")
    validate_items(replay["items"], list(messages), True)


def validate_items(items, messages, complete):
    if not isinstance(items, list) or not messages or messages[0].get("role") != "user" or items[:1] != _normalized(messages[:1]):
        raise ValueError("Responses replay task")
    position = 1
    pending = []
    for message in messages[1:]:
        if message.get("role") == "tool_result":
            if (not pending or (message.get("id"), message.get("name")) != pending.pop(0)
                    or items[position:position + 1] != _normalized([message])):
                raise ValueError("Responses replay result correlation")
            position += 1
            continue
        if message.get("role") != "assistant" or pending:
            raise ValueError("Responses replay message graph")
        pending = [(call["id"], call["name"]) for call in message.get("tool_calls") or []]
        normalized = _normalized([message])
        if normalized and items[position:position + len(normalized)] == normalized:
            position += len(normalized)
            continue
        group = []
        while (position < len(items) and isinstance(items[position], dict)
               and items[position].get("type") in {"message", "reasoning", "function_call"} and "id" in items[position]):
            group.append(items[position])
            position += 1
        calls = message.get("tool_calls") or []
        for item in group:
            _validate_item(item, {call["name"] for call in calls})
        text = "".join(part["text"] for item in group if item["type"] == "message"
                       for part in item["content"] if part["type"] == "output_text")
        expected = [(call["id"], call["name"], call["arguments_raw"] if call.get("arguments_raw") is not None
                     else json.dumps(call["arguments"])) for call in calls]
        actual = [(item["call_id"], item["name"], item["arguments"]) for item in group if item["type"] == "function_call"]
        if not group or actual != expected or (text or None) != message.get("content"):
            raise ValueError("Responses replay call correlation")
    last = messages[-1]
    if pending or position != len(items) or complete != (last.get("role") == "assistant" and not last.get("tool_calls")):
        raise ValueError("Responses replay boundary")


def _validate_item(item, allowed):
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
        raise ValueError("Malformed Responses item identity")
    kind = item.get("type")
    if item.get("status") not in {None, "completed"}:
        raise ValueError("Incomplete Responses item")
    if kind == "message":
        if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
            raise ValueError("Malformed Responses message")
        if "phase" in item and item["phase"] not in {None, "commentary", "final_answer"}:
            raise ValueError("Malformed Responses message phase")
        for part in item["content"]:
            if not isinstance(part, dict) or part.get("type") not in {"output_text", "refusal"}:
                raise ValueError("Unsupported Responses content")
            field = "text" if part["type"] == "output_text" else "refusal"
            if not isinstance(part.get(field), str):
                raise ValueError("Malformed Responses text")
    elif kind == "function_call":
        if item.get("namespace") != NAMESPACE or item.get("name") not in allowed:
            raise ValueError("Unrecognized Responses Tool namespace or name")
        if not isinstance(item.get("call_id"), str) or not item["call_id"] or not isinstance(item.get("arguments"), str):
            raise ValueError("Malformed Responses Tool call")
        arguments = _json(item["arguments"])
        if not isinstance(arguments, dict):
            raise ValueError("Invalid Responses Tool arguments")
    elif kind == "reasoning":
        if "encrypted_content" in item and not isinstance(item["encrypted_content"], str):
            raise ValueError("Malformed encrypted reasoning")
        summary = item.get("summary", [])
        if not isinstance(summary, list) or any(not isinstance(part, dict) or part.get("type") != "summary_text"
                                               or not isinstance(part.get("text"), str) for part in summary):
            raise ValueError("Malformed reasoning summary")
    else:
        raise ValueError("Unsupported Responses item")


def call(model, system, messages, tools=None, replay=None, api_key=None, max_output_tokens=16000,
         prepared_input=None, on_text=None, session_id=None, chatgpt_binding=None, reasoning_effort="auto"):
    from personal_agent import call_log
    from personal_agent.routing.runtime_config import parse_reasoning_effort

    validate_output_allowance(max_output_tokens)
    parse_reasoning_effort(reasoning_effort)
    if chatgpt_binding is not None:
        api_key = chatgpt_auth.ChatGPTAuth().resolve(chatgpt_binding).access_token
    if not api_key:
        raise chatgpt_auth.AuthError("ChatGPT authorization missing; use /connect chatgpt")
    chatgpt_auth._learn(api_key)
    prepared = prepared_input if prepared_input is not None else prepare_input(system, messages, tools, replay)
    if set(prepared) - {"instructions", "input", "tools"}:
        raise ValueError("Unsupported ChatGPT request fields")
    prepared = call_log.redact_data(prepared, ())
    payload = {"model": model, **prepared, "store": False, "stream": True}
    if reasoning_effort != "auto":
        payload["reasoning"] = {"effort": reasoning_effort}
    usage = {"cost": None, "cost_estimated": False}
    items, done, text_parts, arguments, parts = {}, set(), {}, {}, {}
    part_types, text_closed, arguments_closed = {}, set(), set()
    reasoning_text = {}
    response_id, terminal, failure = None, None, None
    size = 0
    response_info = {}
    filtering = http.StreamText(lambda: chatgpt_auth.KNOWN_SECRETS)

    def emit(text):
        safe = filtering.feed(text)
        if safe and on_text is not None:
            on_text(safe)

    def locate(data):
        index = data.get("output_index")
        if type(index) is not int or not 0 <= index < 65536 or index not in items:
            raise ValueError("Invalid Responses output index")
        item = items[index]
        if "item_id" in data and data["item_id"] != item["id"]:
            raise ValueError("Inconsistent Responses item identity")
        if index in done:
            raise ValueError("Responses delta after item completion")
        return index, item

    def content_key(index, item, part_index, kind):
        if item["type"] != "message" or type(part_index) is not int or not 0 <= part_index < 65536:
            raise ValueError("Malformed Responses content part")
        key = index, part_index
        if key in part_types and part_types[key] != kind:
            raise ValueError("Contradictory Responses content type")
        part_types[key] = kind
        return key

    def observe(key, value, exact=False):
        prefix = text_parts.get(key, "")
        if ((exact or key in text_closed) and key in text_parts and value != prefix) or not value.startswith(prefix):
            raise ValueError("Contradictory Responses text snapshot")
        text_parts[key] = value
        emit(value[len(prefix):])

    def snapshot(index, item):
        if type(index) is not int or not 0 <= index < 65536:
            raise ValueError("Invalid Responses output index")
        _validate_item(item, {tool.name for tool in tools or ()})
        previous = items.get(index)
        if index in done:
            if previous != item:
                raise ValueError("Contradictory Responses item snapshots")
            return
        if previous is not None:
            for field in ("id", "type", "role", "call_id", "name", "namespace", "phase"):
                if field in previous and previous[field] != item.get(field):
                    raise ValueError("Inconsistent Responses item snapshot")
        if item["type"] == "message":
            for part_index, part in enumerate(item["content"]):
                key = content_key(index, item, part_index, part["type"])
                if key in parts and parts[key] != part:
                    raise ValueError("Contradictory Responses content snapshot")
                if part["type"] == "output_text":
                    observe(key, part["text"])
            if any(key[0] == index and key[1] >= len(item["content"]) for key in text_parts):
                raise ValueError("Missing Responses text part")
        if item["type"] == "reasoning":
            summary = item.get("summary", [])
            if any(key[0] == index and (key[1] >= len(summary) or summary[key[1]]["text"] != value)
                   for key, value in reasoning_text.items()):
                raise ValueError("Contradictory Responses reasoning snapshot")
        if item["type"] == "function_call" and index in arguments and arguments[index] != item["arguments"]:
            raise ValueError("Contradictory Responses arguments snapshot")
        items[index] = item
        done.add(index)

    try:
        with http.post_sse(API_URL, payload, {"Authorization": f"Bearer {api_key}"},
                           no_redirect=True, response_info=response_info) as events:
            for event, raw in events:
                size += len(raw.encode("utf-8"))
                if size > http.MAX_RESPONSE_BYTES:
                    raise ValueError("Stream response exceeds 8 MiB limit")
                data = _json(raw)
                if not isinstance(data, dict):
                    raise ValueError("Malformed Responses event")
                _usage(data.get("usage"), usage)
                envelope = data.get("response")
                if isinstance(envelope, dict):
                    _usage(envelope.get("usage"), usage)
                if not isinstance(data.get("type"), str):
                    raise ValueError("Malformed Responses event")
                kind = data["type"]
                if event and event != kind:
                    raise ValueError("Contradictory Responses event type")
                if envelope is not None:
                    if not isinstance(envelope, dict) or not isinstance(envelope.get("id"), str) or not envelope["id"]:
                        raise ValueError("Malformed Responses identity")
                    if response_id is not None and response_id != envelope["id"]:
                        raise ValueError("Inconsistent Responses identity")
                    response_id = envelope["id"]
                if kind in {"error", "response.failed"} or isinstance(envelope, dict) and envelope.get("error") is not None:
                    source = envelope if envelope is not None else data
                    current = _failure(source, status=response_info.get("status", 200),
                                       request_id=data.get("request_id") or response_info.get("request_id"))
                    if failure is not None and failure.code and current.code and failure.code != current.code:
                        raise ValueError("Contradictory Responses errors")
                    failure = failure or current
                    terminal = "failed"
                    continue
                if terminal is not None:
                    raise ValueError("Unexpected data after Responses termination")
                if kind == "response.incomplete":
                    raise ValueError("Incomplete Responses output")
                if kind == "response.completed":
                    if envelope is None or envelope.get("status") != "completed":
                        raise ValueError("Malformed Responses completion")
                    output = envelope.get("output")
                    if not isinstance(output, list):
                        raise ValueError("Malformed Responses output")
                    if output:
                        if items and set(items) - set(range(len(output))):
                            raise ValueError("Missing Responses output items")
                        for index, item in enumerate(output):
                            snapshot(index, item)
                    if not items or set(items) != done or sorted(items) != list(range(len(items))):
                        raise ValueError("Incomplete Responses items")
                    terminal = "completed"
                elif kind in {"response.created", "response.in_progress", "response.queued"}:
                    if envelope is None:
                        raise ValueError("Missing Responses envelope")
                elif kind == "keepalive":
                    continue
                elif kind == "response.metadata":
                    identifier = data.get("response_id")
                    if not isinstance(identifier, str) or not identifier or not isinstance(data.get("metadata"), dict):
                        raise ValueError("Malformed Responses metadata")
                    if response_id is not None and identifier != response_id:
                        raise ValueError("Inconsistent Responses identity")
                    response_id = identifier
                elif kind == "response.output_item.added":
                    index, item = data.get("output_index"), data.get("item")
                    if (type(index) is not int or not 0 <= index < 65536 or index in items
                            or not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]
                            or item.get("type") not in {"message", "function_call", "reasoning"}):
                        raise ValueError("Malformed Responses item start")
                    if item["type"] == "message" and item.get("role") != "assistant":
                        raise ValueError("Invalid Responses message role")
                    if item["type"] == "message":
                        content = item.get("content", [])
                        if not isinstance(content, list):
                            raise ValueError("Malformed Responses content")
                        for part_index, part in enumerate(content):
                            if not isinstance(part, dict) or part.get("type") not in {"output_text", "refusal"}:
                                raise ValueError("Malformed Responses content part")
                            key = content_key(index, item, part_index, part["type"])
                            if part["type"] == "output_text":
                                if not isinstance(part.get("text"), str):
                                    raise ValueError("Malformed Responses text part")
                                observe(key, part["text"])
                    items[index] = item
                elif kind == "response.output_item.done":
                    snapshot(data.get("output_index"), data.get("item"))
                elif kind in {"response.output_text.delta", "response.function_call_arguments.delta"}:
                    index, item = locate(data)
                    delta = data.get("delta")
                    if not isinstance(delta, str):
                        raise ValueError("Malformed Responses delta")
                    if kind == "response.output_text.delta":
                        key = content_key(index, item, data.get("content_index"), "output_text")
                        if key in text_closed:
                            raise ValueError("Responses text delta after completion")
                        text_parts[key] = text_parts.get(key, "") + delta
                        emit(delta)
                    else:
                        if item["type"] != "function_call" or index in arguments_closed:
                            raise ValueError("Invalid Responses arguments delta")
                        arguments[index] = arguments.get(index, "") + delta
                elif kind in {"response.content_part.added", "response.content_part.done", "response.output_text.done"}:
                    index, item = locate(data)
                    part = {"type": "output_text", "text": data.get("text")} if kind.endswith("text.done") else data.get("part")
                    if not isinstance(part, dict) or part.get("type") not in {"output_text", "refusal"}:
                        raise ValueError("Malformed Responses content part")
                    key = content_key(index, item, data.get("content_index"), part["type"])
                    if part["type"] == "output_text":
                        value = part.get("text")
                        if not isinstance(value, str):
                            raise ValueError("Malformed Responses text part")
                        if kind.endswith("added") and (key in parts or key in text_parts):
                            raise ValueError("Duplicate Responses content part")
                        observe(key, value, exact=kind.endswith("done"))
                    if kind.endswith("done"):
                        text_closed.add(key)
                    if kind.endswith("part.done"):
                        parts[key] = part
                elif kind == "response.function_call_arguments.done":
                    index, item = locate(data)
                    value = data.get("arguments")
                    if item["type"] != "function_call" or not isinstance(value, str):
                        raise ValueError("Malformed Responses arguments snapshot")
                    if index in arguments and arguments[index] != value:
                        raise ValueError("Contradictory Responses arguments snapshot")
                    arguments[index] = value
                    arguments_closed.add(index)
                elif kind.startswith("response.reasoning_summary_"):
                    index, item = locate(data)
                    summary_index = data.get("summary_index")
                    if item["type"] != "reasoning" or type(summary_index) is not int or not 0 <= summary_index < 65536:
                        raise ValueError("Malformed Responses reasoning index")
                    key = index, summary_index
                    if kind == "response.reasoning_summary_text.delta":
                        delta = data.get("delta")
                        if not isinstance(delta, str):
                            raise ValueError("Malformed Responses reasoning delta")
                        reasoning_text[key] = reasoning_text.get(key, "") + delta
                    elif kind in {"response.reasoning_summary_text.done", "response.reasoning_summary_part.added",
                                  "response.reasoning_summary_part.done"}:
                        part = data.get("part")
                        value = data.get("text") if kind.endswith("text.done") else part.get("text") if isinstance(part, dict) else None
                        if not isinstance(value, str) or part is not None and part.get("type") != "summary_text":
                            raise ValueError("Malformed Responses reasoning snapshot")
                        if key in reasoning_text and reasoning_text[key] != value:
                            raise ValueError("Contradictory Responses reasoning snapshot")
                        reasoning_text[key] = value
                    else:
                        raise ValueError("Unsupported Responses reasoning event")
                elif kind in {"response.refusal.delta", "response.refusal.done"}:
                    index, item = locate(data)
                    content_key(index, item, data.get("content_index"), "refusal")
                else:
                    raise ValueError("Unsupported Responses event: " + chatgpt_auth.safe(kind)[:160])
        if failure is not None:
            raise failure
        if terminal != "completed":
            raise ValueError("Incomplete response: stream ended before response.completed")
        ordered = [items[index] for index in sorted(items)]
        identifiers = [item["id"] for item in ordered]
        calls = [item for item in ordered if item["type"] == "function_call"]
        if len(set(identifiers)) != len(identifiers) or len({item["call_id"] for item in calls}) != len(calls) or len(calls) > 16:
            raise ValueError("Invalid Responses Tool correlation or batch")
        ordered = call_log.redact_data(ordered, ())
        calls = [item for item in ordered if item["type"] == "function_call"]
        tail = filtering.finish()
        if tail and on_text is not None:
            on_text(tail)
        text = "".join(part["text"] for item in ordered if item["type"] == "message"
                       for part in item["content"] if part["type"] == "output_text")
        if not text and not calls:
            raise ValueError("Responses completion has no ordinary answer or Tool calls")
        active_start = (replay["active_start"] if replay is not None else
                        max((index for index, message in enumerate(messages) if message["role"] == "user"), default=0))
        active_items_start = replay["active_items_start"] if replay is not None else len(_normalized(messages[:active_start]))
        assistant = AssistantMessage(text or None, tuple(ToolCall(item["call_id"], item["name"],
                      _json(item["arguments"]), item["arguments"]) for item in calls),
                      replay={"items": prepared["input"] + ordered, "consumed": len(messages) + 1,
                              "active_start": active_start, "active_items_start": active_items_start}, termination="completed")
        return assistant, usage
    except HTTPError as exc:
        detail, data = http._error_evidence(exc)
        _usage(data.get("usage"), usage)
        request_id = exc.headers.get("x-request-id") if exc.headers is not None else None
        failure = _failure(data or {"detail": detail}, exc.code, request_id)
        failure.usage = usage
        raise failure from None
    except BaseException as exc:
        exc.usage = usage
        if getattr(exc, "status", None) is None:
            exc.status = response_info.get("status")
        if getattr(exc, "request_id", None) is None and isinstance(response_info.get("request_id"), str):
            exc.request_id = chatgpt_auth.safe(response_info["request_id"])
        if failure is not None and exc is not failure:
            failure.usage = usage
            raise failure from None
        raise
