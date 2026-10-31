import json
from io import StringIO

import pytest

from personal_agent.providers import anthropic, gemini, openai, openrouter
from personal_agent.routing import runtime_config
from personal_agent.terminal.repl import run_repl

MARKER = {"type": "ephemeral"}


def _payload(provider, model, install_fake_urlopen, stream):
    calls = install_fake_urlopen("answer")
    provider.call(model, "system", [{"role": "user", "content": "task"}], api_key="fixture-key",
                  on_text=(lambda _: None) if stream else None)
    assert len(calls) == 1
    return json.loads(calls[0]["request"].data), calls[0]["request"]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("provider, model", [(anthropic, "claude-test"), (openrouter, "anthropic/claude-sonnet-4.5")])
def test_claude_routes_send_one_top_level_marker(install_fake_urlopen, provider, model, stream):
    payload, request = _payload(provider, model, install_fake_urlopen, stream)
    assert payload["cache_control"] == MARKER
    assert "cache_control" not in json.dumps(payload["messages"])
    assert "system" not in payload or "cache_control" not in json.dumps(payload["system"])
    assert request.get_header("Anthropic-beta") is None
    if provider is openrouter:
        assert payload["provider"] == {"sort": "price", "preferred_min_throughput": 85, "require_parameters": True}


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("provider, model", [
    (openrouter, "vendor/test-model"), (openrouter, "openai/anthropic/x"), (openrouter, "Anthropic/claude"),
    (openai, "gpt-5.4"), (gemini, "gemini-2.5-flash"),
])
def test_other_routes_send_no_marker(install_fake_urlopen, provider, model, stream):
    payload, _ = _payload(provider, model, install_fake_urlopen, stream)
    assert "cache_control" not in json.dumps(payload)


def test_compression_on_a_claude_route_carries_the_marker(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setenv("PA_PROVIDER", "anthropic")
    monkeypatch.setenv("PA_MODEL", "claude-test")
    calls = install_fake_urlopen(["first", "second", "third", "summary"])
    run_repl(runtime_config.load(), input_stream=StringIO("one\ntwo\nthree\n/compress\nexit\n"),
             output_stream=StringIO())
    payloads = [json.loads(call["request"].data) for call in calls]
    assert len(payloads) == 4 and "tools" not in payloads[-1]
    assert [payload["cache_control"] for payload in payloads] == [MARKER] * 4
