import copy
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spike import API, RESOURCE, TOKEN_URL, TOKENS_FILE

MODEL = "gpt-6.1-sol"
REVOKE_URL = "https://auth.openai.com/api/accounts/oauth/revoke"
JWKS_URL = "https://auth.openai.com/.well-known/jwks.json"
SSE_LIMIT = 256 * 1024
RESULTS = []

NAMESPACE = {
    "type": "namespace",
    "name": "pa",
    "description": "personal-agent local workspace tools.",
    "tools": [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a text file from the workspace and return its content.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    ],
}


def load() -> dict:
    return json.loads(TOKENS_FILE.read_text())


def save(data: dict):
    tmp = TOKENS_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, TOKENS_FILE)


def check(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""), flush=True)


def note(text: str):
    print(f"       {text}", flush=True)


def redact(body: dict) -> dict:
    return {k: (f"<{len(v)} chars>" if k.endswith("token") and isinstance(v, str) else v) for k, v in body.items()}


def read_error(exc: urllib.error.HTTPError) -> dict:
    raw = exc.read().decode(errors="replace")
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw[:500]}


def post_form(url: str, form: dict) -> tuple[int, dict]:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        return exc.code, read_error(exc)


def get_models(token: str) -> tuple[int, dict]:
    request = urllib.request.Request(API + "/models", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, read_error(exc)


def respond(extra: dict, token: str | None = None) -> dict:
    body = {"model": MODEL, "store": False, "stream": True, **extra}
    body = {k: v for k, v in body.items() if v is not None}
    request = urllib.request.Request(API + "/responses", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {token or load()['access_token']}",
                                              "Content-Type": "application/json",
                                              "Accept": "text/event-stream"})
    out = {"status": None, "request_id": None, "events": [], "max_event": 0, "error": None,
           "response": None, "text": "", "items": []}
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            out["status"] = response.status
            out["request_id"] = response.headers.get("x-oai-request-id")
            if not body["stream"]:
                out["response"] = json.loads(response.read())
                return out
            for raw in response:
                out["max_event"] = max(out["max_event"], len(raw))
                line = raw.decode().rstrip("\r\n")
                if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                    continue
                event = json.loads(line[5:])
                out["events"].append(event.get("type"))
                if event.get("type") == "response.output_text.delta":
                    out["text"] += event["delta"]
                elif event.get("type") == "response.output_item.done":
                    out["items"].append(event["item"])
                elif event.get("type") in ("response.completed", "response.incomplete", "response.failed"):
                    out["response"] = event["response"]
                elif event.get("type") == "error":
                    out["error"] = event
    except urllib.error.HTTPError as exc:
        out["status"] = exc.code
        out["request_id"] = exc.headers.get("x-oai-request-id")
        out["error"] = read_error(exc)
    return out


def completed(out: dict) -> bool:
    return out["status"] == 200 and "response.completed" in out["events"]


def output_items(out: dict) -> list[dict]:
    return out["items"]


def describe(item: dict) -> str:
    shown = {k: (f"<{len(v)} chars>" if k == "encrypted_content" and v else v)
             for k, v in item.items() if k not in ("content", "summary")}
    return json.dumps(shown)[:400]


def tool_loop(prompt: str, files: dict, strip_ids: bool = False, max_turns: int = 5) -> dict:
    history = [{"role": "user", "content": prompt}]
    calls_per_turn = []
    for _ in range(max_turns):
        out = respond({"input": history, "tools": [NAMESPACE]})
        if not completed(out):
            return {"ok": False, "out": out, "calls_per_turn": calls_per_turn}
        items = output_items(out)
        calls = [i for i in items if i.get("type") == "function_call"]
        calls_per_turn.append([(c.get("namespace"), c.get("name"), c.get("arguments")) for c in calls])
        replay = copy.deepcopy(items)
        if strip_ids:
            for item in replay:
                item.pop("id", None)
        history += replay
        if not calls:
            return {"ok": True, "out": out, "calls_per_turn": calls_per_turn, "items": items}
        for call in calls:
            path = json.loads(call["arguments"]).get("path", "")
            history.append({"type": "function_call_output", "call_id": call["call_id"],
                            "output": files.get(Path(path).name, "ERROR: file not found")})
    return {"ok": False, "out": out, "calls_per_turn": calls_per_turn}


def t_jwks():
    import jwt
    saved = load()
    client = jwt.PyJWKClient(JWKS_URL)
    for label, token, audience in (("id_token", saved["id_token"], saved["client_id"]),
                                   ("access_token", saved["access_token"], RESOURCE)):
        alg = jwt.get_unverified_header(token)["alg"]
        try:
            key = client.get_signing_key_from_jwt(token)
            jwt.decode(token, key.key, algorithms=[alg], audience=audience,
                       issuer="https://auth.openai.com", options={"verify_exp": False})
            check(f"jwks signature {label}", True, f"alg={alg} aud={audience}")
        except Exception as exc:
            check(f"jwks signature {label}", False, f"alg={alg} {type(exc).__name__}: {exc}")


def t_models():
    status, data = get_models(load()["access_token"])
    models = data.get("models", [])
    check("models list", status == 200 and bool(models), f"{len(models)} models")
    for m in models:
        note(f"{m['slug']:<20} vis={m.get('visibility'):<5} ctx={m.get('context_window')} "
             f"max_ctx={m.get('max_context_window')} parallel={m.get('supports_parallel_tool_calls')} "
             f"api={m.get('supported_in_api')} efforts={[e['effort'] for e in m.get('supported_reasoning_levels', [])]}")


def t_text():
    out = respond({"instructions": "Answer tersely.", "input": [{"role": "user", "content": "Say exactly: pong"}]})
    check("text streaming", completed(out) and "pong" in out["text"].lower(),
          f"text={out['text']!r} request_id={out['request_id']}")
    check("request id header x-oai-request-id", bool(out["request_id"]))
    note(f"event types: {sorted(set(out['events']))}")
    note(f"usage keys: {sorted((out['response'] or {}).get('usage', {}))}")


def t_developer_message():
    out = respond({"input": [{"role": "developer", "content": "Reply only in UPPERCASE letters."},
                             {"role": "user", "content": "say hello world"}]})
    check("developer message instead of system", completed(out) and out["text"].strip().isupper(),
          f"text={out['text']!r}")


def t_tool_single():
    result = tool_loop("Use the read_file tool to read notes.txt, then reply with exactly its content.",
                       {"notes.txt": "banana-42"})
    calls = result["calls_per_turn"]
    check("tool call in namespace + function_call_output round trip",
          result["ok"] and "banana-42" in result["out"]["text"],
          f"calls={calls} final={result['out']['text'][:80]!r}")
    if result.get("items") is not None or calls:
        note(f"namespace field on function_call: {calls[0][0] if calls and calls[0] else None!r}")
    if not result["ok"]:
        note(f"error={json.dumps(result['out']['error'])[:500]}")


def t_tool_first_items():
    out = respond({"input": [{"role": "user", "content": "Read config.txt with the tool."}], "tools": [NAMESPACE]})
    for item in output_items(out):
        note(f"output item: {describe(item)}")


def t_tool_strip_ids():
    result = tool_loop("Use the read_file tool to read notes.txt, then reply with exactly its content.",
                       {"notes.txt": "kiwi-7"}, strip_ids=True)
    check("tool round trip with item ids stripped", result["ok"] and "kiwi-7" in result["out"]["text"],
          f"final={result['out']['text'][:80]!r}")


def t_tool_parallel():
    result = tool_loop("Read a.txt and b.txt with the read_file tool, calling it for both files in the same turn, "
                       "then reply with both contents separated by a comma.",
                       {"a.txt": "alpha-1", "b.txt": "beta-2"})
    first = result["calls_per_turn"][0] if result["calls_per_turn"] else []
    text = result["out"]["text"]
    check("parallel tool calls", result["ok"] and "alpha-1" in text and "beta-2" in text,
          f"calls in first turn={len(first)} turns={len(result['calls_per_turn'])} final={text[:80]!r}")


def t_tool_error_result():
    result = tool_loop("Use read_file to read missing.txt and tell me what happened.", {})
    check("tool error result handled", result["ok"], f"final={result['out']['text'][:120]!r}")


def t_reasoning_replay():
    first_input = [{"role": "user", "content": "Pick a secret 4-digit number, do not reveal it, just say 'ready'."}]
    first = respond({"input": first_input, "reasoning": {"effort": "medium", "summary": "auto"}})
    items = output_items(first)
    reasoning = [i for i in items if i.get("type") == "reasoning"]
    check("reasoning effort+summary accepted", completed(first), f"error={first['error']}")
    check("reasoning item has encrypted_content by default", any(i.get("encrypted_content") for i in reasoning),
          f"{len(reasoning)} reasoning items")
    for item in items:
        note(f"turn1 item: {describe(item)}")
    follow = {"role": "user", "content": "Now reveal the secret number you picked."}
    second = respond({"input": first_input + items + [follow], "reasoning": {"effort": "medium"}})
    check("multi-turn replay with reasoning items", completed(second), f"text={second['text'][:80]!r}")
    stripped = [i for i in items if i.get("type") != "reasoning"]
    third = respond({"input": first_input + stripped + [follow]})
    check("multi-turn replay without reasoning items", completed(third), f"text={third['text'][:80]!r}")
    explicit = respond({"input": first_input, "include": ["reasoning.encrypted_content"]})
    check("include reasoning.encrypted_content accepted", completed(explicit), f"error={explicit['error']}")
    for effort in ("low", "xhigh"):
        out = respond({"input": [{"role": "user", "content": "2+2?"}], "reasoning": {"effort": effort}})
        check(f"reasoning effort {effort}", completed(out), f"error={out['error']}")


def t_other_model():
    out = respond({"model": "gpt-5.6-luna", "input": [{"role": "user", "content": "Say exactly: luna"}]})
    check("second model (gpt-5.6-luna)", completed(out), f"text={out['text']!r} error={out['error']}")


def t_restrictions():
    base = {"input": [{"role": "user", "content": "Say ok"}]}
    variants = {
        "max_output_tokens": {"max_output_tokens": 100},
        "temperature": {"temperature": 0.2},
        "top_p": {"top_p": 0.5},
        "previous_response_id": {"previous_response_id": "resp_does_not_exist"},
        "metadata": {"metadata": {"k": "v"}},
        "truncation": {"truncation": "auto"},
        "store=true": {"store": True},
        "stream=false": {"stream": False},
        "system message": {"input": [{"role": "system", "content": "Be terse."}, {"role": "user", "content": "Say ok"}]},
        "parallel_tool_calls=false": {"parallel_tool_calls": False, "tools": [NAMESPACE]},
        "tool_choice=auto": {"tool_choice": "auto", "tools": [NAMESPACE]},
        "plain top-level function tool": {"tools": [NAMESPACE["tools"][0]]},
        "text.verbosity=low": {"text": {"verbosity": "low"}},
    }
    for label, extra in variants.items():
        out = respond({**base, **extra})
        error = out["error"] or {}
        err = error.get("error", error) if isinstance(error, dict) else {}
        verdict = "accepted" if completed(out) else f"rejected {out['status']} code={err.get('code')} param={err.get('param')}"
        note(f"{label:<30} {verdict} {'' if completed(out) else (err.get('message') or json.dumps(error))[:160]}")


def t_invalid_token():
    saved = load()["access_token"]
    status, body = get_models(saved[:-4] + ("AAAA" if not saved.endswith("AAAA") else "BBBB"))
    check("tampered token rejected", status == 401, f"status={status} body={json.dumps(redact(body))[:200]}")
    out = respond({"input": [{"role": "user", "content": "hi"}]}, token="not-a-token")
    check("garbage token rejected on /responses", out["status"] == 401,
          f"status={out['status']} error={json.dumps(out['error'])[:200]}")


def t_large_output():
    out = respond({"input": [{"role": "user", "content": "Write a detailed essay of about 2500 words on the history "
                                                         "of the Unix shell. Plain prose, no lists."}]})
    usage = (out["response"] or {}).get("usage", {})
    check("large output completes", completed(out), f"output_tokens={usage.get('output_tokens')}")
    check("largest SSE event within 256 KiB", out["max_event"] <= SSE_LIMIT,
          f"max_event={out['max_event']} bytes")


def t_context_overflow():
    filler = "lorem ipsum dolor sit amet " * 200_000
    out = respond({"input": [{"role": "user", "content": filler + "\nSay ok"}]})
    error = out["error"] or {}
    err = error.get("error", error) if isinstance(error, dict) else {}
    check("context overflow returns structured error", not completed(out),
          f"status={out['status']} code={err.get('code')} msg={(err.get('message') or json.dumps(error))[:200]}")


def cmd_api():
    tests = (t_jwks, t_models, t_text, t_developer_message, t_tool_first_items, t_tool_single, t_tool_strip_ids,
             t_tool_parallel, t_tool_error_result, t_reasoning_replay, t_other_model, t_restrictions,
             t_invalid_token, t_large_output, t_context_overflow)
    only = set(sys.argv[2:])
    for test in tests:
        if only and test.__name__ not in only:
            continue
        print(f"\n== {test.__name__}", flush=True)
        try:
            test()
        except Exception as exc:
            check(test.__name__, False, f"{type(exc).__name__}: {exc}")


def refresh(refresh_token: str) -> tuple[int, dict]:
    saved = load()
    return post_form(TOKEN_URL, {"grant_type": "refresh_token", "client_id": saved["client_id"],
                                 "refresh_token": refresh_token, "resource": RESOURCE})


def cmd_refresh():
    saved = load()
    now = int(time.time())
    note(f"now={now} earliest_refresh_at={saved.get('earliest_refresh_at')} "
         f"delta={saved.get('earliest_refresh_at', now) - now}s")
    status, body = refresh(saved["refresh_token"])
    if status != 200:
        check("refresh", False, f"status={status} body={json.dumps(redact(body))[:300]}")
        return
    rotated = body.get("refresh_token") not in (None, saved["refresh_token"])
    check("refresh", True, f"keys={sorted(body)} expires_in={body.get('expires_in')}")
    check("refresh token rotated", rotated)
    note(f"new earliest_refresh_at delta={body.get('earliest_refresh_at', 0) - int(time.time())}s scope={body.get('scope')}")
    save({**saved, **body, "obtained_at": int(time.time()), "previous_refresh_token": saved["refresh_token"]})
    status, _ = get_models(body["access_token"])
    check("new access token works", status == 200, f"status={status}")


def cmd_reuse():
    saved = load()
    status, body = refresh(saved["previous_refresh_token"])
    check("reused old refresh token rejected", status != 200, f"status={status} body={json.dumps(redact(body))[:300]}")
    status, body = refresh(saved["refresh_token"])
    note(f"current refresh token after reuse attempt: status={status} body={json.dumps(redact(body))[:200]}")
    if status == 200:
        save({**saved, **body, "obtained_at": int(time.time())})


def cmd_logout():
    saved = load()
    status, body = post_form(REVOKE_URL, {"token": saved["refresh_token"], "token_type_hint": "refresh_token",
                                          "client_id": saved["client_id"]})
    check("revoke refresh token", status == 200, f"status={status} body={json.dumps(redact(body))[:200]}")
    status, body = post_form(REVOKE_URL, {"token": saved["refresh_token"], "token_type_hint": "refresh_token",
                                          "client_id": saved["client_id"]})
    check("revoke is idempotent", status == 200, f"status={status}")
    status, body = refresh(saved["refresh_token"])
    check("refresh after revoke fails", status != 200, f"status={status} body={json.dumps(redact(body))[:300]}")
    status, _ = get_models(saved["access_token"])
    note(f"access token after revoke: /models status={status}")
    out = respond({"input": [{"role": "user", "content": "Say ok"}]}, token=saved["access_token"])
    note(f"access token after revoke: /responses status={out['status']} completed={completed(out)}")


if __name__ == "__main__":
    {"api": cmd_api, "refresh": cmd_refresh, "reuse": cmd_reuse, "logout": cmd_logout}[sys.argv[1]]()
    print(f"\nSUMMARY: {sum(ok for _, ok in RESULTS)}/{len(RESULTS)} passed")
    for name, ok in RESULTS:
        if not ok:
            print("  FAILED:", name)
