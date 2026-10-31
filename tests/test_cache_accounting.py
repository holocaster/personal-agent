import pytest

from personal_agent import cost
from personal_agent.providers import http
from personal_agent.token_estimate import local_library


@pytest.fixture
def fixed_prices(monkeypatch):
    library, _ = local_library()
    for provider in ("anthropic", "openai", "gemini"):
        monkeypatch.setitem(library.model_cost, f"{provider}/cache-fixture", {
            "litellm_provider": provider, "mode": "chat", "max_tokens": 1000000,
            "input_cost_per_token": .01, "output_cost_per_token": .02,
            "cache_read_input_token_cost": .001, "cache_creation_input_token_cost": .03,
            "cache_creation_input_token_cost_above_1hr": .05,
        })
    return library


def test_anthropic_cache_counts_and_ttl_are_normalized_and_billed_once(fixed_prices):
    usage = http.response_usage({"usage": {
        "input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 20,
        "cache_creation_input_tokens": 30,
        "cache_creation": {"ephemeral_5m_input_tokens": 10, "ephemeral_1h_input_tokens": 20},
    }}, "anthropic", "cache-fixture")
    assert usage["prompt_tokens"] == 60
    assert usage["cached_tokens"] == 20
    assert usage["cache_write_tokens"] == 30
    assert usage["cache_creation_token_details"] == {
        "ephemeral_5m_input_tokens": 10, "ephemeral_1h_input_tokens": 20}
    assert usage["cost"] == pytest.approx(1.52)
    assert usage["cost_estimated"] is True


@pytest.mark.parametrize("provider,raw,expected", [
    ("openai", {"prompt_tokens": 60, "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 30}}, 1.12),
    ("gemini", {"promptTokenCount": 30, "candidatesTokenCount": 5,
                "cachedContentTokenCount": 20}, .22),
])
def test_direct_cache_subsets_are_not_added_twice(fixed_prices, provider, raw, expected):
    usage = http.response_usage({"usageMetadata" if provider == "gemini" else "usage": raw},
                                provider, "cache-fixture")
    assert usage["prompt_tokens"] == (30 if provider == "gemini" else 60)
    assert usage["cached_tokens"] == 20
    assert usage["cost"] == pytest.approx(expected)


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
@pytest.mark.parametrize("invalid", [True, -1, "20", [], {}, None])
def test_invalid_cache_never_creates_an_estimate(fixed_prices, provider, invalid):
    raw = ({"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": invalid,
            "cache_creation_input_tokens": 0} if provider == "anthropic" else
           {"promptTokenCount": 10, "candidatesTokenCount": 5, "cachedContentTokenCount": invalid}
           if provider == "gemini" else {"prompt_tokens": 10, "completion_tokens": 5,
           "prompt_tokens_details": {"cached_tokens": invalid, "cache_write_tokens": 0}})
    usage = http.response_usage({"usageMetadata" if provider == "gemini" else "usage": raw},
                                provider, "cache-fixture")
    assert usage["completion_tokens"] == 5
    assert usage["cost"] is None


@pytest.mark.parametrize("details", [None, True, [], {"ephemeral_5m_input_tokens": 30},
    {"ephemeral_5m_input_tokens": 10, "ephemeral_1h_input_tokens": 10},
    {"ephemeral_5m_input_tokens": True, "ephemeral_1h_input_tokens": 29}])
def test_invalid_or_partial_ttl_breakdown_is_unavailable(fixed_prices, details):
    usage = http.response_usage({"usage": {"input_tokens": 10, "output_tokens": 5,
        "cache_read_input_tokens": 20, "cache_creation_input_tokens": 30,
        "cache_creation": details}}, "anthropic", "cache-fixture")
    assert usage["prompt_tokens"] == 60 and usage["cached_tokens"] == 20
    assert usage["cost"] is None


@pytest.mark.parametrize("name", ["anthropic", "gemini", "openai", "openrouter"])
@pytest.mark.parametrize("failure", [False, True])
def test_supplied_cache_evidence_matches_stream_nonstream_and_failure(fixed_prices, monkeypatch, name, failure):
    from personal_agent.providers import anthropic, gemini, openai, openrouter
    from tests.fakes import FakeOpenRouterResponse
    from tests.test_native_streaming import block_start, block_stop, candidate, message_delta, message_start
    from tests.test_streaming import frame, install_stream

    provider = {"anthropic": anthropic, "gemini": gemini, "openai": openai, "openrouter": openrouter}[name]
    if name == "anthropic":
        raw = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 20,
               "cache_creation_input_tokens": 30,
               "cache_creation": {"ephemeral_5m_input_tokens": 10, "ephemeral_1h_input_tokens": 20}}
        data = {"content": [{"type": "text", "text": "hi"}], "usage": raw}
        chunks = [message_start(raw), block_start(0, {"type": "text", "text": "hi"}), block_stop(0),
                  message_delta(), frame({"type": "message_stop"})]
    elif name == "gemini":
        raw = {"promptTokenCount": 30, "candidatesTokenCount": 5, "cachedContentTokenCount": 20}
        data = candidate([{"text": "hi"}], "STOP", usageMetadata=raw)
        chunks = [frame(data)]
    else:
        raw = {"prompt_tokens": 60, "completion_tokens": 5, "cost": .123456789,
               "prompt_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 30}}
        data = {"choices": [{"message": {"content": "hi"}}], "usage": raw}
        chunks = [frame({"choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": "stop"}], "usage": raw}),
                  frame("[DONE]")]
    monkeypatch.setattr(http, "urlopen", lambda *a, **kw: FakeOpenRouterResponse(data))
    _, expected = provider.call("cache-fixture", "", [])
    if failure:
        chunks = chunks[:1] + [TimeoutError()]
    install_stream(monkeypatch, chunks)
    if failure:
        with pytest.raises(TimeoutError) as caught:
            provider.call("cache-fixture", "", [], on_text=lambda _: None)
        actual = caught.value.usage
    else:
        _, actual = provider.call("cache-fixture", "", [], on_text=lambda _: None)
    for key in ("prompt_tokens", "completion_tokens", "cached_tokens", "cache_write_tokens",
                "cache_creation_token_details", "cost", "cost_estimated"):
        assert actual.get(key) == expected.get(key), key


def test_missing_cache_coverage_stays_absent_and_unproven_estimates_unavailable(fixed_prices):
    usage = http.response_usage({"usage": {"prompt_tokens": 10000, "completion_tokens": 5}},
                                "openai", "cache-fixture")
    assert "cached_tokens" not in usage and "cache_write_tokens" not in usage
    assert usage["cost"] is None
    uncached = http.response_usage({"usage": {"input_tokens": 10, "output_tokens": 5}},
                                   "anthropic", "cache-fixture")
    assert "cached_tokens" not in uncached and uncached["cost"] == pytest.approx(.2)


@pytest.mark.parametrize("field", ["input_cost_per_token", "output_cost_per_token", "cache_read_input_token_cost",
                                    "cache_creation_input_token_cost", "cache_creation_input_token_cost_above_1hr"])
def test_missing_applicable_local_rate_never_becomes_free(fixed_prices, monkeypatch, field):
    prices = {key: value for key, value in fixed_prices.model_cost["anthropic/cache-fixture"].items() if key != field}
    model = "missing-" + field
    monkeypatch.setitem(fixed_prices.model_cost, f"anthropic/{model}", prices)
    assert cost.estimate(model, 60, 5, provider="anthropic", cached_tokens=20,
                         cache_write_tokens=30, cache_creation_token_details={
                             "ephemeral_5m_input_tokens": 10, "ephemeral_1h_input_tokens": 20}) is None


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
def test_zero_and_uncached_prices_use_real_calculator(fixed_prices, provider):
    assert cost.estimate(f"{provider}/cache-fixture", 10, 5, provider=provider) == pytest.approx(.2)
    assert cost.estimate(f"{provider}/cache-fixture", 0, 0, provider=provider) == 0
    assert cost.estimate(f"{provider}/cache-fixture", 10, 5, provider=provider, cached_tokens=11) is None


@pytest.mark.parametrize("provider,expected", [("anthropic", 1.12), ("openai", 1.12), ("gemini", .22)])
@pytest.mark.parametrize("failure", [False, True])
def test_available_estimate_is_logged_and_charged_once_per_physical_attempt(
        fixed_prices, route_env, monkeypatch, provider, expected, failure):
    import json
    from pathlib import Path
    from personal_agent import call_log
    from personal_agent.routing import router, runtime_config
    from tests.fakes import FakeOpenRouterResponse

    monkeypatch.setenv("PA_PROVIDER", provider)
    monkeypatch.setenv("PA_MODEL", "cache-fixture")
    monkeypatch.setenv({"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}[provider], "fake")
    if provider == "anthropic":
        data = {"content": [{"type": "text", "text": "hi"}], "usage": {
            "input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 20, "cache_creation_input_tokens": 30}}
    elif provider == "gemini":
        data = {"candidates": [{"content": {"parts": [{"text": "hi"}]}}], "usageMetadata": {
            "promptTokenCount": 30, "candidatesTokenCount": 5, "cachedContentTokenCount": 20}}
    else:
        data = {"choices": [{"message": {"content": "hi"}}], "usage": {
            "prompt_tokens": 60, "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 30}}}
    if failure:
        data["error"] = {"code": 400, "message": "request rejected"}
    calls = []
    def respond(*args, **kwargs):
        calls.append(1)
        return FakeOpenRouterResponse(data)
    monkeypatch.setattr(http, "urlopen", respond)
    router.route("task", runtime_config.load())
    entries = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    attempts = [entry for entry in entries if entry["type"] == "attempt"]
    assert len(calls) == len(attempts) == 1
    assert attempts[0]["cost"] == pytest.approx(expected)
    assert attempts[0]["cost_estimated"] is True
    assert attempts[0]["outcome"] == ("error" if failure else "ok")
    assert call_log.total_cost() == pytest.approx(expected)


@pytest.mark.parametrize("name", ["anthropic", "gemini", "openai", "openrouter"])
@pytest.mark.parametrize("invalid", [True, -1, "bad"])
def test_malformed_stream_cache_keeps_independent_tokens_and_no_direct_estimate(
        fixed_prices, monkeypatch, name, invalid):
    from personal_agent.providers import anthropic, gemini, openai, openrouter
    from tests.test_native_streaming import message_start
    from tests.test_streaming import frame, install_stream

    if name == "anthropic":
        chunk = message_start({"input_tokens": 10, "output_tokens": 5,
            "cache_read_input_tokens": invalid, "cache_creation_input_tokens": 0})
    elif name == "gemini":
        chunk = frame({"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5,
                                        "cachedContentTokenCount": invalid}})
    else:
        chunk = frame({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5,
            "cost": .125, "prompt_tokens_details": {"cached_tokens": invalid, "cache_write_tokens": 0}}})
    install_stream(monkeypatch, [chunk])
    provider = {"anthropic": anthropic, "gemini": gemini, "openai": openai, "openrouter": openrouter}[name]
    with pytest.raises(ValueError) as caught:
        provider.call("cache-fixture", "", [], on_text=lambda _: None)
    usage = caught.value.usage
    assert usage["completion_tokens"] == 5
    assert usage["cached_tokens"] == invalid
    assert usage.get("cache_write_tokens") == (None if name == "gemini" else 0)
    assert usage["cost"] == (.125 if name == "openrouter" else None)


@pytest.mark.parametrize("name", ["openai", "openrouter"])
@pytest.mark.parametrize("details", [None, False, [], "bad"])
def test_malformed_cache_details_are_invalid_instead_of_missing(fixed_prices, name, details):
    usage = http.response_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 5,
        "cost": .125, "prompt_tokens_details": details}}, name, "cache-fixture")
    assert usage["cached_tokens"] == "invalid details"
    assert usage["cache_write_tokens"] == "invalid details"
    assert usage["prompt_tokens"] == 10 and usage["completion_tokens"] == 5
    assert usage["cost"] == (.125 if name == "openrouter" else None)


@pytest.mark.parametrize("invalid", [True, -1, float("inf"), "bad", {}])
@pytest.mark.parametrize("prior", [False, True])
def test_invalid_stream_money_never_replaces_available_reported_cost(monkeypatch, invalid, prior):
    from personal_agent.providers import openrouter
    from tests.test_streaming import frame, install_stream

    chunks = [frame({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                                              "cost": .25}})] if prior else []
    chunks.append(frame({"choices": [], "usage": {"cost": invalid, "completion_tokens": 6}}))
    install_stream(monkeypatch, chunks)
    with pytest.raises(ValueError) as caught:
        openrouter.call("synthetic", "", [], on_text=lambda _: None)
    assert caught.value.usage["cost"] == (.25 if prior else None)
    assert caught.value.usage["completion_tokens"] == 6
