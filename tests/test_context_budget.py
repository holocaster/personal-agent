import pytest
import json
import os
import subprocess
import sys
from pathlib import Path
from io import StringIO

from personal_agent.routing import runtime_config
from personal_agent import context_budget
from personal_agent import token_estimate, call_log
from personal_agent.routing import router
from personal_agent.terminal.repl import run_repl
from personal_agent.providers import openai, openrouter, anthropic, gemini
from personal_agent.providers.contract import ToolDef


@pytest.mark.parametrize("metadata,override,expected", [
    ({}, {"total_tokens": 250000}, (250000, 16000, 224000)),
    ({}, {}, (128000, 16000, 102000)),
    ({"max_input_tokens": 90000, "max_tokens": 999999}, {}, (90000, 16000, 64000)),
    ({"max_input_tokens": 90000}, {"total_tokens": 250000}, (250000, 16000, 80000)),
    ({"max_output_tokens": 4000}, {"total_tokens": 100000}, (100000, 4000, 86000)),
    ({"max_input_tokens": 80000, "max_output_tokens": 4000}, {"total_tokens": 250000}, (250000, 4000, 70000)),
    ({}, {"total_tokens": 9000}, (9000, 16000, -17000)),
    ({"max_context_tokens": True, "max_input_tokens": -5, "max_output_tokens": 1.2}, {}, (128000, 16000, 102000)),
])
def test_route_budget_arithmetic(monkeypatch, metadata, override, expected):
    monkeypatch.setattr(context_budget, "model_info", lambda *_: metadata)
    records = ({"provider": "openai", "model": "exact", **override},) if override else ()
    limits = context_budget.resolve(runtime_config.RuntimeConfig("", "", {}, capacity_overrides=records), "openai", "exact")
    assert (limits.effective_total, limits.output_reserve, limits.input_ceiling) == expected


def test_openrouter_model_bounds_do_not_verify_upstream_and_manual_fields_replace_bounds(monkeypatch):
    monkeypatch.setattr(context_budget, "model_info", lambda *_: {
        "max_tokens": 250000, "max_input_tokens": 100000, "max_output_tokens": 8000})
    config = runtime_config.RuntimeConfig("", "", {})
    limits = context_budget.resolve(config, "openrouter", "exact")
    assert limits.total_source == "published model-wide"
    assert limits.total_tokens == 100000
    assert limits.input_source == "published model-wide"
    assert limits.input_ceiling == 82000
    config = runtime_config.RuntimeConfig("", "", {}, capacity_overrides=({
        "provider": "openrouter", "model": "exact", "total_tokens": 300000, "input_tokens": 280000},))
    limits = context_budget.resolve(config, "openrouter", "exact")
    assert limits.effective_total == 250000
    assert limits.input_ceiling == 232000
    assert limits.total_source == "manual"
    assert limits.input_source == "manual"
    assert limits.output_source == "published model-wide"


@pytest.mark.parametrize("provider,model,source,expected", [
    ("anthropic", "claude-sonnet-4-5", "published", (200000, 16000, 174000)),
    ("openrouter", "anthropic/claude-sonnet-4.5", "published model-wide", (200000, 16000, 174000)),
    ("openai", "gpt-5", "published", (250000, 16000, 224000)),
    ("gemini", "gemini-2.5-pro", "published", (250000, 16000, 224000)),
])
def test_real_bundled_metadata_gives_known_capacity_without_override(monkeypatch, provider, model, source, expected):
    import socket
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    limits = context_budget.resolve(runtime_config.RuntimeConfig("", "", {}), provider, model)
    assert limits.total_source == source
    assert (limits.effective_total, limits.output_reserve, limits.input_ceiling) == expected


@pytest.mark.parametrize("custom", ["missing", "corrupt", "valid"])
def test_real_locked_counter_is_offline_repeatable_and_counts_tokens(tmp_path, custom):
    script = r'''
import json, sys, importlib.metadata
events = []
def deny(event, args):
    if event in ("socket.connect", "socket.getaddrinfo"):
        events.append(event)
        raise RuntimeError("network forbidden")
sys.addaudithook(deny)
from personal_agent.token_estimate import estimate
from personal_agent.context_budget import model_info
assert importlib.metadata.version("litellm") == "1.102.0"
assert importlib.metadata.version("tiktoken") == "0.14.0"
assert importlib.metadata.version("tokenizers") == "0.23.2"
prepared = {"messages": [{"role":"system","content":"规则 café Python: def λ(x): return x ** 2"},
                         {"role":"user","content":"こんにちは ∑"}]}
known = estimate("gpt-4o", prepared)
assert known.encoding == "o200k_base" and not known.generic
for model in ("claude-sonnet-4-5", "gemini-3.1-pro-preview", "minimax/minimax-m2.5", "unknown-model"):
    count = estimate(model, prepared)
    assert count.encoding == "cl100k_base" and count.generic
    assert count == estimate(model, prepared)
    assert count.tokens != len(json.dumps(prepared, ensure_ascii=False).encode("utf-8"))
assert estimate("gpt-4o", prepared) == known
assert "generic fallback" in count.label and "approximate" in known.label
model_info("openrouter", "unknown-model")
for provider in ("openai", "anthropic", "gemini", "openrouter"):
    model_info(provider, "huggingface/example")
assert events == [], events
print("LiteLLM 1.102.0; o200k and generic cl100k; repeatable Unicode/code counts; zero network attempts")
'''
    cache = tmp_path / "custom-cache"
    cache.mkdir()
    if custom in {"corrupt", "valid"}:
        import importlib.util
        directory = Path(importlib.util.find_spec("litellm").origin).parent / "litellm_core_utils" / "tokenizers"
        for asset, _ in token_estimate._ASSETS.values():
            (cache / asset).write_bytes((directory / asset).read_bytes() if custom == "valid" else b"corrupt")
    env = {**os.environ, "CUSTOM_TIKTOKEN_CACHE_DIR": str(cache), "LITELLM_LOCAL_MODEL_COST_MAP": "False"}
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "zero network attempts" in result.stdout


@pytest.mark.parametrize("provider", [openai, openrouter, anthropic, gemini])
def test_measured_prepared_input_matches_wire_including_tools_and_caps(provider, monkeypatch):
    sent = []
    def post(url, payload, headers):
        sent.append(payload)
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "length"}],
                "content": [{"type": "text", "text": "ok"}], "stop_reason": "max_tokens",
                "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "MAX_TOKENS"}]}
    monkeypatch.setattr("personal_agent.providers.http.post_json", post)
    tool = ToolDef("example", "complete description", {"type": "object", "properties": {
        "key": {"type": "string", "description": "rare property " * 100}}, "$defs": {"custom": {"const": "schema"}},
        "additionalProperties": False, "required": ["key"]})
    messages = [{"role": "user", "content": "task λ"}, {"role": "assistant", "content": "assistant",
        "tool_calls": [{"id": "call-opaque", "name": "example", "arguments": None, "arguments_raw": "{malformed"}]},
        {"role": "tool_result", "id": "call-opaque", "name": "example", "content": {"error": "rejected"}, "is_error": True}]
    replay = None
    if provider is gemini:
        replay = {"contents": [{"role": "user", "parts": [{"text": "task λ"}]},
                  {"role": "model", "parts": [{"functionCall": {"name": "example", "args": {}, "id": "call-opaque"},
                                               "thoughtSignature": "opaque-signature"}]}], "consumed": 2}
    prepared = provider.prepare_input("Memory Summary Todos Skill rules", messages, (tool,), replay)
    rendered = token_estimate.render_input(prepared)
    before = token_estimate.estimate("gpt-4o", provider.prepare_input("short", [{"role": "user", "content": "task λ"}]))
    after = token_estimate.estimate("gpt-4o", prepared)
    assert after.tokens > before.tokens + 100
    assert rendered.count("task λ") == 1
    assert "rare property" in rendered and "additionalProperties" in rendered and "$defs" in rendered
    if provider is gemini:
        assert rendered.count("opaque-signature") == 1
        assert rendered.count("call-opaque") == 2
    elif provider in (openai, openrouter):
        assert "{malformed" in rendered
    assistant, _ = provider.call("gemini-3.1-pro-preview" if provider is gemini else "model", "unused", [],
                                 max_output_tokens=1234, prepared_input=prepared)
    payload = sent[0]
    for key, value in prepared.items():
        assert payload[key] == value
    assert assistant.truncated
    if provider is openai:
        assert payload["max_completion_tokens"] == 1234
    elif provider is gemini:
        assert payload["generationConfig"] == {"maxOutputTokens": 1234}
    else:
        assert payload["max_tokens"] == 1234
    if provider is openrouter:
        assert payload["provider"] == {"sort": "price", "preferred_min_throughput": 85, "require_parameters": True}


@pytest.mark.parametrize("candidate", [
    {"content": {"role": "model"}},
    {},
    {"content": None},
    {"content": {"parts": []}},
    {"content": {"parts": None}},
])
def test_gemini_empty_capped_response_preserves_termination_and_usage(monkeypatch, candidate):
    monkeypatch.setattr("personal_agent.providers.http.post_json", lambda *_: {
        "candidates": [{**candidate, "finishReason": "MAX_TOKENS"}],
        "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 0,
                          "thoughtsTokenCount": 16000, "totalTokenCount": 16050},
    })
    assistant, usage = gemini.call("gemini-2.5-flash", "system", [{"role": "user", "content": "task"}],
                                   max_output_tokens=16000)
    assert assistant.text is None
    assert assistant.tool_calls == ()
    assert assistant.termination == "MAX_TOKENS"
    assert assistant.truncated
    assert usage["prompt_tokens"] == 50
    assert usage["completion_tokens"] == 0
    assert usage["cost_estimated"]
    assert usage["cost"] > 0


@pytest.mark.parametrize("estimated,dispatched", [(223999, True), (224000, True), (224001, False)])
def test_budget_ceiling_boundary_is_visible_and_never_dispatches_unchecked(
    route_env, install_fake_urlopen, monkeypatch, estimated, dispatched
):
    monkeypatch.setattr(token_estimate, "estimate", lambda *_: token_estimate.TokenEstimate(estimated, "fixture", True))
    calls = install_fake_urlopen(["answer"])
    output = StringIO()
    config = runtime_config.load()
    config = runtime_config.RuntimeConfig(config.provider, config.model, config.api_keys, capacity_overrides=({
        "provider": "openrouter", "model": "vendor/test-model", "total_tokens": 250000},))
    run_repl(config, input_stream=StringIO("summarize task\n/usage\nexit\n"), output_stream=output)
    assert len(calls) == int(dispatched)
    text = output.getvalue()
    assert "input ceiling: 224000; output reserve: 16000" in text
    assert "approximate fixture (generic fallback)" in text
    if not dispatched:
        assert "locally blocked" in text and "reported input: unknown" in text
        entries = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
        assert not [entry for entry in entries if entry["type"] == "attempt"]


def test_more_than_twenty_retained_turns_are_all_sent_below_budget(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["answer"] * 24)
    run_repl(runtime_config.load(), input_stream=StringIO("".join(f"summarize task {n}\n" for n in range(24)) + "exit\n"),
             output_stream=StringIO())
    users = [m["content"] for m in json.loads(calls[-1]["request"].data)["messages"] if m["role"] == "user"]
    assert users == [f"summarize task {n}" for n in range(24)]


@pytest.mark.parametrize("value", [0, -1, True, 1.5, None])
def test_invalid_library_counts_stop_before_dispatch(route_env, install_fake_urlopen, monkeypatch, value):
    library, _ = token_estimate.local_library()
    monkeypatch.setattr(library, "token_counter", lambda **_: value)
    calls = install_fake_urlopen([])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("summarize task\n/usage\nexit\n"), output_stream=output)
    assert calls == []
    assert "Context budget blocked" in output.getvalue()


def test_disabled_or_failed_counter_and_invalid_json_stop_visibly(route_env, install_fake_urlopen, monkeypatch):
    library, _ = token_estimate.local_library()
    monkeypatch.setattr(library, "disable_token_counter", True)
    calls = install_fake_urlopen([])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("summarize task\nexit\n"), output_stream=output)
    assert calls == [] and "counting is disabled" in output.getvalue()
    for malformed in ({"n": float("nan")}, {1: "coerced key"}, {"bad": object()}, {"text": "\ud800"}):
        with pytest.raises((ValueError, UnicodeError)):
            token_estimate.render_input(malformed)


def test_no_usable_local_assets_or_counting_exception_never_dispatches(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setattr(token_estimate, "_valid_asset", lambda *_: False)
    calls = install_fake_urlopen([])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("summarize task\n/usage\nexit\n"), output_stream=output)
    assert calls == [] and "no valid local tokenizer assets" in output.getvalue()


def test_large_tool_follow_up_keeps_execution_evidence_and_does_not_repeat_tools(route_env, install_fake_urlopen, monkeypatch):
    estimates = iter([1000, 102001])
    monkeypatch.setattr(token_estimate, "estimate", lambda *_: token_estimate.TokenEstimate(next(estimates), "fixture", True))
    calls = install_fake_urlopen([{"tool_calls": [{"id": "calc-1", "name": "calculator", "arguments": {"expression": "2+2"}}]}])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("calculate task\n/usage\nexit\n"), output_stream=output)
    assert len(calls) == 1
    assert "locally blocked" in output.getvalue()
    entries = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    assert len([entry for entry in entries if entry["type"] == "attempt"]) == 1
    execution = [entry for entry in entries if entry["type"] == "tool_execution"]
    assert len(execution) == 1 and execution[0]["result"] == {"result": 4}
    assert [entry for entry in entries if entry["type"] == "turn_end"][0]["status"] == "error"
    assert call_log.load_conversation(call_log.current_session_id())[0] == ()


def test_every_retry_is_reassessed_and_local_failure_does_not_escalate(route_env, install_fake_urlopen, monkeypatch):
    from urllib.error import HTTPError
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    estimates = iter([1000, 102001])
    monkeypatch.setattr(token_estimate, "estimate", lambda *_: token_estimate.TokenEstimate(next(estimates), "fixture", True))
    calls = install_fake_urlopen([HTTPError("fake", 503, "transient", None, None)])
    result = router.route("summarize task", runtime_config.load())
    assert len(calls) == 1 and not result.ok
    assert "Context budget blocked" in result.error
    assert result.model == "vendor/test-model"


def test_retry_exhaustion_does_not_assess_another_routes_capacity(route_env, install_fake_urlopen, monkeypatch):
    from urllib.error import HTTPError
    from dataclasses import replace
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    monkeypatch.setattr(token_estimate, "estimate", lambda *_: token_estimate.TokenEstimate(120000, "fixture", True))
    config = replace(runtime_config.load(), capacity_overrides=(
        {"provider": "openrouter", "model": "vendor/test-model", "total_tokens": 250000},
        {"provider": "openrouter", "model": "vendor/medium-model", "total_tokens": 100000}))
    calls = install_fake_urlopen([HTTPError("fake", 503, "transient", None, None)] * 3)
    result = router.route("summarize task", config)
    assert len(calls) == 3 and result.model == "vendor/test-model"
    assert "HTTPError" in result.error
    assert all(json.loads(call["request"].data)["model"] == "vendor/test-model" for call in calls)


def test_task_snapshot_keeps_original_routes_keys_and_overrides_across_tool_follow_up(route_env, install_fake_urlopen):
    from dataclasses import replace
    config = replace(runtime_config.load(), capacity_overrides=({
        "provider": "openrouter", "model": "vendor/test-model", "total_tokens": 250000, "output_tokens": 4000},))
    calls = install_fake_urlopen([{"tool_calls": [{"id": "calc-1", "name": "calculator", "arguments": {"expression": "2+2"}}]}, "four"])
    def mutate_source(_):
        object.__setattr__(config, "model", "changed")
        config.api_keys["openrouter"] = "changed-key"
        object.__setattr__(config, "provider", "openai")
        config.capacity_overrides[0]["output_tokens"] = 1
    result = router.route("summarize task", config, on_tool_result=mutate_source)
    assert result.ok
    assert [json.loads(call["request"].data)["model"] for call in calls] == ["vendor/test-model"] * 2
    assert [json.loads(call["request"].data)["max_tokens"] for call in calls] == [4000] * 2
    assert [call["request"].get_header("Authorization") for call in calls] == ["Bearer test-key"] * 2


@pytest.mark.parametrize("provider_name", ["openrouter", "openai", "anthropic", "gemini"])
def test_ordinary_and_manual_compression_requests_are_bounded_for_every_provider(
    route_env, install_fake_urlopen, monkeypatch, provider_name
):
    key_var = runtime_config.API_KEY_ENV_VARS[provider_name]
    monkeypatch.setenv(key_var, "fake-key")
    monkeypatch.setenv("PA_PROVIDER", provider_name)
    calls = install_fake_urlopen(["first", "second", "third", "summary"])
    run_repl(runtime_config.load(), input_stream=StringIO("summarize 1\nsummarize 2\nsummarize 3\n/compress\nexit\n"), output_stream=StringIO())
    assert len(calls) == 4
    for call in calls:
        payload = json.loads(call["request"].data)
        if provider_name == "openai":
            assert payload["max_completion_tokens"] == 16000
        elif provider_name == "gemini":
            assert payload["generationConfig"]["maxOutputTokens"] == 16000
        else:
            assert payload["max_tokens"] == 16000
        if provider_name == "openrouter":
            assert payload["provider"] == {"sort": "price", "preferred_min_throughput": 85, "require_parameters": True}
    assert "tools" not in json.loads(calls[-1]["request"].data)


@pytest.mark.parametrize("candidate,error", [
    ({"content": {"role": "model"}}, "empty"),
    ({}, "empty"),
    ({"content": {"parts": [{"text": "unfinished summary"}]}}, "length-truncated"),
])
def test_gemini_capped_manual_compression_keeps_conversation_and_summary_and_counts_cost(
    route_env, monkeypatch, install_fake_urlopen, candidate, error
):
    from dataclasses import replace
    from tests.fakes import FakeOpenRouterResponse
    config = replace(runtime_config.load(), api_keys={"gemini": "fake-key"}, model="gemini-2.5-flash", provider="gemini")
    responses = [
        *({"candidates": [{"content": {"parts": [{"text": text}]}}]}
          for text in ("first", "second", "third", "ORIGINAL SUMMARY", "fourth")),
        {"candidates": [{**candidate, "finishReason": "MAX_TOKENS"}],
         "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 0,
                           "thoughtsTokenCount": 16000, "totalTokenCount": 16050}},
        {"candidates": [{"content": {"parts": [{"text": "fifth"}]}}]},
    ]
    calls = install_fake_urlopen([FakeOpenRouterResponse(data) for data in responses])
    output = StringIO()
    run_repl(config, input_stream=StringIO(
        "summarize one\nsummarize two\nsummarize three\n/compress\nsummarize four\n"
        "/compress\n/history\nsummarize five\nexit\n"), output_stream=output)
    sent = [json.loads(call["request"].data) for call in calls]
    assert len(calls) == 7
    assert [":streamGenerateContent?alt=sse" in call["request"].full_url for call in calls] == [
        True, True, True, False, True, False, True]
    assert f"Error: the summary answer was {error}" in output.getvalue()
    assert "summary: ORIGINAL SUMMARY" in output.getvalue()
    assert "ORIGINAL SUMMARY" in sent[-1]["systemInstruction"]["parts"][0]["text"]
    assert [content["parts"][0]["text"] for content in sent[-1]["contents"] if content["role"] == "user"] == [
        "summarize two", "summarize three", "summarize four", "summarize five"]
    entries = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    assert len([entry for entry in entries if entry["type"] == "conversation_compressed"]) == 1
    attempts = [entry for entry in entries if entry.get("task") == "/compress"]
    assert len(attempts) == 2
    assert attempts[-1]["prompt_tokens"] == 50
    assert attempts[-1]["completion_tokens"] == 0
    assert attempts[-1]["cost"] > 0
    assert call_log.total_cost() == pytest.approx(attempts[-1]["cost"])


def test_usage_replaces_last_success_after_provider_failure_and_ignores_internal_compression(route_env, install_fake_urlopen):
    output = StringIO()
    install_fake_urlopen([{"content": "first", "usage": {"prompt_tokens": 55}}, "second", "third", "summary", ValueError("rejected")])
    run_repl(runtime_config.load(), input_stream=StringIO(
        "summarize one\nsummarize two\nsummarize three\n/compress\n/usage\nsummarize rejected\n/usage\nexit\n"), output_stream=output)
    text = output.getvalue()
    assert "outcome: completed" in text and "outcome: provider failure" in text
    assert "reported input: unknown" in text and "reported input: 55" not in text
    assert "task snapshot context budget: 250000" in text


def test_anthropic_cache_counts_are_input_occupancy_and_complete_cost_breakdown(monkeypatch):
    captured = []
    monkeypatch.setattr("personal_agent.providers.http.post_json", lambda *_: {
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 10, "cache_read_input_tokens": 40, "cache_creation_input_tokens": 50, "output_tokens": 3}})
    monkeypatch.setattr("personal_agent.cost.estimate", lambda *args, **kwargs: captured.append((args, kwargs)) or 0.1)
    _, usage = anthropic.call("model", "system", [])
    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 3
    assert captured == [(("model", 100, 3), {"provider": "anthropic", "cached_tokens": 40,
                        "cache_write_tokens": 50, "cache_creation_token_details": None})]


@pytest.mark.parametrize("constituent", ["task", "skill", "memory", "summary", "todos"])
def test_complete_large_input_constituents_block_without_silent_cut(route_env, install_fake_urlopen, monkeypatch, constituent):
    from personal_agent.workspace_skills import Skill
    marker = "protected-large-constituent " * 200
    seen = []
    def count(model, prepared):
        rendered = token_estimate.render_input(prepared)
        seen.append(rendered)
        assert marker in rendered
        return token_estimate.TokenEstimate(102001, "fixture", True)
    monkeypatch.setattr(token_estimate, "estimate", count)
    calls = install_fake_urlopen([])
    kwargs = {"skills": (Skill("large", "active", marker, b"fingerprint"),)} if constituent == "skill" else (
             {"memory_notes": [{"text": marker}]} if constituent == "memory" else (
             {"summary": marker} if constituent == "summary" else (
             {"todos": [{"content": marker, "status": "in_progress"}]} if constituent == "todos" else {})))
    result = router.route(marker if constituent == "task" else "summarize task", runtime_config.load(), **kwargs)
    assert not result.ok and calls == []
    assert len(seen) == 1 and "input ceiling 102000" in result.error


def _offering(provider="openai", model="exact", context=200000, input=None, output=8000):
    from personal_agent.model_catalog import Offering
    return Offering(provider, model, "Exact", None, context, input, output, None)


@pytest.mark.parametrize("metadata,offering,override,expected", [
    ({}, _offering(input=150000), {}, ((200000, "Models.dev"), (150000, "Models.dev"), (8000, "Models.dev"))),
    ({"max_input_tokens": 90000, "max_output_tokens": 4000}, _offering(), {},
     ((200000, "Models.dev"), (90000, "published"), (8000, "Models.dev"))),
    ({}, _offering(input=150000), {"total_tokens": 100000},
     ((100000, "manual"), (150000, "Models.dev"), (8000, "Models.dev"))),
    ({"max_input_tokens": 90000}, _offering(model="other"), {},
     ((90000, "published"), (90000, "published"), (None, None))),
    ({}, None, {}, ((128000, "unknown; assumed"), (None, None), (None, None))),
])
def test_capacity_provenance_per_field(monkeypatch, metadata, offering, override, expected):
    monkeypatch.setattr(context_budget, "model_info", lambda *_: metadata)
    records = ({"provider": "openai", "model": "exact", **override},) if override else ()
    config = runtime_config.RuntimeConfig("openai", "exact", {}, capacity_overrides=records, offering=offering)
    limits = context_budget.resolve(config.snapshot(), "openai", "exact")
    assert ((limits.total_tokens, limits.total_source), (limits.input_tokens, limits.input_source),
            (limits.output_tokens, limits.output_source)) == expected


def test_models_dev_limits_size_the_exchange(monkeypatch):
    monkeypatch.setattr(context_budget, "model_info", lambda *_: {})
    config = runtime_config.RuntimeConfig("openai", "exact", {}, context_budget_tokens=250000,
                                          offering=_offering(context=100000, input=60000, output=4000))
    limits = context_budget.resolve(config, "openai", "exact")
    assert (limits.effective_total, limits.output_reserve, limits.input_ceiling) == (100000, 4000, 50000)
