import json
import os

from personal_agent.providers import http
from tests.fakes import FakeOpenRouterResponse


def install_provider():
    def respond(request, timeout=None):
        payload = json.loads(request.data)
        answer = json.dumps({"pid": os.getpid(), "request": payload})
        response = FakeOpenRouterResponse({"choices": [{"message": {"content": answer}}],
                                           "usage": {"cost": 0.25}})
        return response.stream() if payload.get("stream") else response
    http.urlopen = respond


def install_scripted_provider():
    from pathlib import Path
    from urllib.error import URLError
    script = json.loads((Path.home() / "worker-script.json").read_text())
    if script.get("fail_evidence"):
        from personal_agent import call_log
        original = call_log._write_line
        def write(entry, **kwargs):
            if entry["type"] == script["fail_evidence"]:
                raise OSError("injected child evidence failure")
            return original(entry, **kwargs)
        call_log._write_line = write
    if script.get("fail_stop_all"):
        from personal_agent.tools import jobs
        def fail():
            raise OSError("injected job cleanup failure")
        jobs.stop_all = fail
    if script.get("change_settings"):
        from personal_agent import context_budget, model_catalog
        from personal_agent.routing import runtime_config
        os.environ["PA_MODEL"] = "different-model"
        os.environ["PA_PROVIDER"] = "different-provider"
        os.environ["PA_ENABLE_SHELL"] = "0"
        context_budget.model_info = lambda *args: {"max_input_tokens": 30000, "max_output_tokens": 1000}
        def forbidden(*args, **kwargs):
            raise AssertionError("child reread route settings or catalog")
        runtime_config.load = model_catalog.load = forbidden
    actions = iter(script["actions"])
    captures = []
    def respond(request, timeout=None):
        payload = json.loads(request.data)
        captures.append(payload)
        action = next(actions)
        if "error" in action:
            raise URLError(TimeoutError(action["error"]))
        if "crash" in action:
            os._exit(action["crash"])
        if "wait" in action:
            import signal
            import time
            if action.get("ignore_sigint"):
                signal.signal(signal.SIGINT, signal.SIG_IGN)
            Path(action["wait"]).write_text(str(os.getpid()))
            while True:
                time.sleep(0.05)
        if "assert_tools" in action:
            assert sorted(item["function"]["name"] for item in payload.get("tools", [])) == sorted(action["assert_tools"])
        if "assert_output" in action:
            assert payload["max_tokens"] == action["assert_output"]
            assert payload["model"] == "vendor/test-model"
        if "assert_system" in action:
            for phrase in action["assert_system"]:
                assert phrase in payload["messages"][0]["content"], phrase
        message = {"content": action.get("answer", json.dumps({"pid": os.getpid(), "requests": captures}))}
        if "calls" in action:
            message = {"content": None, "tool_calls": [
                {"id": str(index), "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
                for index, (name, arguments) in enumerate(action["calls"])]}
        response = FakeOpenRouterResponse({"choices": [{"message": message}],
                                           "usage": action.get("usage", {"cost": 0.25})})
        return response.stream() if payload.get("stream") else response
    http.urlopen = respond


def install_chatgpt_provider():
    import time
    from pathlib import Path
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from personal_agent import chatgpt_auth
    from personal_agent.providers import chatgpt
    from tests.test_chatgpt_provider import completed, exhaustion, function, message
    from tests.test_streaming import StreamResponse
    home = Path.home()
    script = json.loads((home / "worker-script.json").read_text())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="child", alg="RS256", use="sig")

    def transport(url, *, form=None, bearer=None):
        if url == chatgpt_auth.JWKS:
            return {"keys": [jwk]}
        if url == chatgpt_auth.TOKEN:
            with open(home / "token-calls", "a") as calls:
                calls.write(json.dumps({"process": "child", "refresh_token": form["refresh_token"]}) + "\n")
            time.sleep(script.get("refresh_delay", 0))
            claims = {"iss": chatgpt_auth.ISSUER, "sub": "account-1", "aud": "oaiapp_fixture",
                      "exp": int(time.time()) + 3600}
            return {"access_token": "child-access-" + str(os.getpid()), "refresh_token": "child-refresh",
                    "id_token": jwt.encode(claims, key, algorithm="RS256", headers={"kid": "child"}),
                    "token_type": "Bearer", "expires_in": 3600}
        raise AssertionError("unexpected child account request " + url)
    chatgpt_auth._request = transport
    actions = iter(script["actions"])

    def respond(request, timeout=None):
        payload = json.loads(request.data)
        bearer = request.get_header("Authorization")[len("Bearer "):]
        with open(home / "child-requests.jsonl", "a") as requests:
            requests.write(json.dumps({"bearer": bearer, "model": payload["model"], "input": payload["input"],
                                       **({"reasoning": payload["reasoning"]} if "reasoning" in payload else {})}) + "\n")
        action = next(actions)
        usage = action.get("usage", {"input_tokens": 10, "output_tokens": 2, "input_tokens_details": {"cached_tokens": 3},
                                     "output_tokens_details": {"reasoning_tokens": 1}})
        if "wait" in action:
            Path(action["wait"]).write_text(str(os.getpid()))
            while True:
                time.sleep(0.05)
        if action.get("exhaust"):
            return StreamResponse(exhaustion(usage))
        if "calls" in action:
            return StreamResponse([completed([function(str(index), name, json.dumps(arguments))
                                              for index, (name, arguments) in enumerate(action["calls"])], usage)])
        text = action.get("answer", "")
        if action.get("echo"):
            text += " " + " ".join(sorted(chatgpt_auth.KNOWN_SECRETS))
        return StreamResponse([completed([message(text)], usage)])
    chatgpt.http.urlopen = respond
