import json

from personal_agent import chatgpt_auth
from personal_agent.providers import chatgpt
from personal_agent.providers.registry import PROVIDERS


def build(task, provider, model, registration=None, messages=None, replay=None, fetched_urls=()):
    value = {"version": 2 if provider == "chatgpt" else 1, "task": task, "provider": provider, "model": model,
             "messages": messages if messages is not None else [{"role": "user", "content": task}],
             "replay": replay, "fetched_urls": list(fetched_urls)}
    if provider == "chatgpt":
        value["registration"] = registration
    return value


def validate(value: dict) -> dict:
    message = "invalid pending turn continuation"
    keys = {"version", "task", "provider", "model", "messages", "replay", "fetched_urls"}
    if not isinstance(value, dict) or set(value) - {"registration"} != keys:
        raise ValueError(message)
    if (type(value["version"]) is not int or value["version"] not in {1, 2}
            or (value["version"] == 2) != (value["provider"] == "chatgpt") or ("registration" in value) != (value["version"] == 2)):
        raise ValueError(message + " version")
    if value["version"] == 2 and not chatgpt_auth.valid_reference(value["registration"]):
        raise ValueError(message + " registration")
    if not isinstance(value["task"], str) or not value["task"].strip():
        raise ValueError(message + " task")
    if (not isinstance(value["provider"], str) or value["provider"] not in PROVIDERS
            or not isinstance(value["model"], str) or not value["model"].strip()):
        raise ValueError(message + " route")
    messages = value["messages"]
    if not isinstance(messages, list) or not messages or messages[0] != {"role": "user", "content": value["task"]}:
        raise ValueError(message + " messages")
    pending = {}
    batches = []
    for item in messages[1:]:
        if not isinstance(item, dict):
            raise ValueError(message + " messages")
        if item.get("role") == "assistant" and not pending:
            if set(item) != {"role", "content", "tool_calls"} or item["content"] is not None and not isinstance(item["content"], str):
                raise ValueError(message + " assistant content")
            calls = item.get("tool_calls")
            if not isinstance(calls, list) or not 1 <= len(calls) <= 16:
                raise ValueError(message + " Tool calls")
            batches.append((item, []))
            for call in calls:
                if (not isinstance(call, dict) or not isinstance(call.get("id"), str) or not call["id"]
                        or call["id"] in pending or not isinstance(call.get("name"), str) or not call["name"]
                        or set(call) != {"id", "name", "arguments", "arguments_raw", "id_is_generated"}
                        or call["arguments"] is not None and not isinstance(call["arguments"], dict)
                        or call["arguments_raw"] is not None and not isinstance(call["arguments_raw"], str)
                        or type(call["id_is_generated"]) is not bool):
                    raise ValueError(message + " Tool calls")
                pending[call["id"]] = call
        elif item.get("role") == "tool_result" and pending:
            identifier = item.get("id")
            if (not isinstance(identifier, str) or identifier not in pending
                    or pending[identifier]["name"] != item.get("name")
                    or set(item) != {"role", "id", "name", "content", "is_error", "id_is_generated"}
                    or type(item.get("is_error")) is not bool or type(item["id_is_generated"]) is not bool
                    or item["id_is_generated"] != pending[identifier]["id_is_generated"]):
                raise ValueError(message + " Tool results")
            if item["is_error"] and (not isinstance(item["content"], dict) or not isinstance(item["content"].get("error"), str)):
                raise ValueError(message + " Tool error content")
            if item["name"] == "todo" and not item["is_error"]:
                todos = item["content"].get("todos") if isinstance(item["content"], dict) else None
                if not isinstance(todos, list) or any(
                    not isinstance(todo, dict) or set(todo) != {"content", "status"}
                    or not isinstance(todo["content"], str) or not isinstance(todo["status"], str)
                    or todo["status"] not in {"pending", "in_progress", "completed", "cancelled"} for todo in todos
                ):
                    raise ValueError(message + " Todo content")
            batches[-1][1].append(item)
            del pending[identifier]
        else:
            raise ValueError(message + " message graph")
    if pending:
        raise ValueError(message + " unfinished message graph")
    urls = value["fetched_urls"]
    if not isinstance(urls, list) or any(not isinstance(url, str) or not url for url in urls) or len(set(urls)) != len(urls):
        raise ValueError(message + " fetched URLs")
    replay = value["replay"]
    if replay is not None and value["version"] == 2:
        if (not isinstance(replay, dict) or set(replay) != {"items", "consumed", "active_start", "active_items_start"}
                or type(replay["consumed"]) is not int or replay["consumed"] != len(messages)
                or replay["active_start"] != 0 or replay["active_items_start"] != 0
                or type(replay["active_start"]) is not int or type(replay["active_items_start"]) is not int):
            raise ValueError(message + " replay indices")
        try:
            chatgpt.validate_items(replay["items"], messages, False)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError(message + " replay graph") from exc
    elif replay is not None:
        _validate_replay(replay, value, batches, message)
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(message) from exc


def _validate_replay(replay, state, batches, message):
    if (state["provider"] != "gemini" or not isinstance(replay, dict)
            or set(replay) != {"contents", "consumed", "active_start", "active_contents_start"}
            or type(replay["consumed"]) is not int or replay["consumed"] != len(state["messages"])
            or type(replay["active_start"]) is not int or replay["active_start"] != 0
            or type(replay["active_contents_start"]) is not int or replay["active_contents_start"] != 0):
        raise ValueError(message + " replay indices")
    contents = replay["contents"]
    if not isinstance(contents, list) or len(contents) != 1 + 2 * len(batches):
        raise ValueError(message + " replay graph")
    if contents[0] != {"role": "user", "parts": [{"text": state["task"]}]}:
        raise ValueError(message + " replay task")
    for index, (assistant, results) in enumerate(batches):
        model, user = contents[1 + index * 2:3 + index * 2]
        if (not isinstance(model, dict) or set(model) != {"role", "parts"} or model["role"] != "model"
                or not isinstance(model["parts"], list) or not model["parts"]
                or not isinstance(user, dict) or set(user) != {"role", "parts"} or user["role"] != "user"
                or not isinstance(user["parts"], list) or len(user["parts"]) != len(results)):
            raise ValueError(message + " replay contents")
        calls = []
        texts = []
        for part_index, part in enumerate(model["parts"]):
            if (not isinstance(part, dict) or not part
                    or part.keys() - {"text", "functionCall", "thought", "thoughtSignature"}
                    or "text" in part and "functionCall" in part
                    or not (part.keys() & {"text", "functionCall", "thoughtSignature"})):
                raise ValueError(message + " replay parts")
            if "thoughtSignature" in part and not isinstance(part["thoughtSignature"], str):
                raise ValueError(message + " replay signature")
            if "thought" in part and type(part["thought"]) is not bool:
                raise ValueError(message + " replay thought")
            if "text" in part:
                if not isinstance(part["text"], str):
                    raise ValueError(message + " replay text")
                if not part.get("thought"):
                    texts.append(part["text"])
            if "functionCall" in part:
                call = part["functionCall"]
                if (not isinstance(call, dict) or not isinstance(call.get("name"), str)
                        or "args" in call and call["args"] is not None and not isinstance(call["args"], dict)
                        or "id" in call and call["id"] is not None and not isinstance(call["id"], str)):
                    raise ValueError(message + " replay function call")
                calls.append((call.get("id") or f"gemini-call-{part_index}", call["name"], call.get("args") or {}, call.get("id") is None))
        expected = [(call["id"], call["name"], call["arguments"], call["id_is_generated"]) for call in assistant["tool_calls"]]
        text_forms = ("".join(texts), "\n".join(texts)) if texts else (None,)
        if calls != expected or assistant["content"] not in text_forms:
            raise ValueError(message + " replay call correlation")
        for part, result in zip(user["parts"], results):
            response = {"name": result["name"], "response": result["content"] if isinstance(result["content"], dict) else {"result": result["content"]}}
            if not result["id_is_generated"]:
                response["id"] = result["id"]
            if part != {"functionResponse": response}:
                raise ValueError(message + " replay result correlation")
