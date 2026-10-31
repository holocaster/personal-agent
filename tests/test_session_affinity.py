import json
from io import StringIO
from urllib.error import HTTPError

import pytest

from personal_agent import call_log
from personal_agent.providers import anthropic, gemini, openai, openrouter
from personal_agent.routing import router, runtime_config
from personal_agent.terminal.repl import run_repl


@pytest.mark.parametrize("provider", [openrouter, openai, anthropic, gemini])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("identity", [None, "20261014T120000Z-abc123"])
def test_provider_identity_is_optional_openrouter_metadata(provider, stream, identity, install_fake_urlopen):
    calls = install_fake_urlopen("answer")
    prepared = provider.prepare_input("system", [{"role": "user", "content": "task"}])
    assistant, _ = provider.call("fixture-model", "unused", [], api_key="fixture-key",
                                 prepared_input=prepared, session_id=identity,
                                 on_text=(lambda _: None) if stream else None)
    assert assistant.text == "answer"
    assert len(calls) == 1
    payload = json.loads(calls[0]["request"].data)
    if provider is openrouter and identity is not None:
        assert payload["session_id"] == identity
    else:
        assert "session_id" not in payload
    for key, value in prepared.items():
        assert payload[key] == value
    if provider is openrouter:
        assert payload["provider"] == {"sort": "price", "preferred_min_throughput": 85,
                                       "require_parameters": True}


def run(text, config, resumed=None):
    output = StringIO()
    run_repl(config, input_stream=StringIO(text), output_stream=output, resumed=resumed)
    return output.getvalue()


@pytest.mark.parametrize("identity", ["x" * 257, 123, []])
def test_invalid_openrouter_identity_stops_before_http(identity, install_fake_urlopen):
    calls = install_fake_urlopen("answer")
    with pytest.raises(ValueError, match="at most 256"):
        openrouter.call("fixture-model", "system", [], session_id=identity)
    assert calls == []


def test_openrouter_identity_accepts_exact_bound(install_fake_urlopen):
    calls = install_fake_urlopen("answer")
    openrouter.call("fixture-model", "system", [], session_id="x" * 256)
    assert json.loads(calls[0]["request"].data)["session_id"] == "x" * 256


def test_standalone_provider_omits_identity_even_during_active_session(route_env, install_fake_urlopen):
    call_log.start_session(runtime_config.load())
    calls = install_fake_urlopen("answer")
    openrouter.call("fixture-model", "system", [])
    assert "session_id" not in json.loads(calls[0]["request"].data)


@pytest.mark.parametrize("stream", [False, True])
def test_ordinary_affinity_survives_followups_retries_turns_and_resume(
    route_env, install_fake_urlopen, monkeypatch, stream
):
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    original_call = openrouter.call
    if not stream:
        monkeypatch.setattr(openrouter, "call", lambda *args, **kwargs: original_call(*args, **kwargs))
    config = runtime_config.load()
    failure = HTTPError("https://example.invalid", 503, "transient", None, None)
    permanent = HTTPError("https://example.invalid", 400, "permanent", None, None)
    calls = install_fake_urlopen([
        failure, {"tool_calls": [{"id": "calc", "name": "calculator", "arguments": {"expression": "2+2"}}]},
        "first answer", permanent, "retry answer", "next answer", "resumed answer", "other session answer",
    ])
    run("first\nfailed\n/retry\nnext\nexit\n", config)
    sid = call_log.current_session_id()
    resumed = (sid, *call_log.load_conversation(sid))
    call_log.reset_session()
    run("resumed\nexit\n", config, resumed)
    call_log.reset_session()
    run("other\nexit\n", config)
    other = call_log.current_session_id()
    assert sid != other
    bodies = [json.loads(call["request"].data) for call in calls]
    assert [body["session_id"] for body in bodies] == [sid] * 7 + [other]
    assert all(bool(body.get("stream")) == stream for body in bodies)
    assert bodies[0] == bodies[1]
    assert bodies[2]["messages"][-1]["role"] == "tool"


def test_compression_affinity_is_separate_and_survives_retries_and_resume(
    route_env, install_fake_urlopen, monkeypatch
):
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    failure = HTTPError("https://example.invalid", 503, "transient", None, None)
    calls = install_fake_urlopen(["a1", "a2", "a3", failure, "summary", "a4", failure, "summary two", "a5"])
    config = runtime_config.load()
    run("one\ntwo\nthree\n/compress\nfour\nexit\n", config)
    sid = call_log.current_session_id()
    resumed = (sid, *call_log.load_conversation(sid))
    call_log.reset_session()
    run("/compress\nfive\nexit\n", config, resumed)
    bodies = [json.loads(call["request"].data) for call in calls]
    compression = f"{sid}:compression"
    assert [body["session_id"] for body in bodies] == [sid] * 3 + [compression] * 2 + [sid] + [compression] * 2 + [sid]
    assert bodies[3] == bodies[4] and bodies[6] == bodies[7]
    assert {body["model"] for body in bodies} == {"vendor/test-model"}
