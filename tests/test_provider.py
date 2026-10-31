import io
import json
import socket
import ssl

import pytest
from urllib.error import HTTPError, URLError

from personal_agent import cost
from personal_agent.providers import anthropic, gemini, http, openai, openrouter as provider
from personal_agent.providers.contract import ToolCall, ToolDef, ToolsUnsupportedError
from personal_agent.providers.registry import get_provider
from tests.fakes import FakeOpenRouterResponse

CALC_TOOL = ToolDef(
    name="calculator",
    description="Evaluate a basic arithmetic expression.",
    parameters={
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    },
)


def _http_error(code):
    return HTTPError("https://openrouter.ai", code, "err", None, None)


def _http_error_with_body(code, body: dict):
    return HTTPError(
        "https://openrouter.ai", code, "err", None, io.BytesIO(json.dumps(body).encode("utf-8"))
    )


def test_unknown_provider_does_not_fall_back_to_openrouter():
    with pytest.raises(KeyError):
        get_provider("unknown")


def test_openrouter_provider_diagnostics_defers_generation_lookup(monkeypatch):
    monkeypatch.setenv(provider.PROVIDER_DIAGNOSTICS_ENV_VAR, "1")
    monkeypatch.setattr(
        http, "post_json",
        lambda url, payload, headers: {
            "id": "gen-123",
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeOpenRouterResponse({"data": {"provider_name": "CoreWeave"}})

    monkeypatch.setattr(provider, "urlopen", fake_urlopen)

    answer, usage = provider.call("vendor/model", "system", [], api_key="test-key")

    assert answer.text == "hi"
    assert usage["generation_id"] == "gen-123"
    assert requests == []
    assert provider._lookup_upstream_provider(usage["generation_id"], "test-key") == "CoreWeave"
    request, timeout = requests[0]
    assert request.full_url == "https://openrouter.ai/api/v1/generation?id=gen-123"
    assert request.get_header("Authorization") == "Bearer test-key"
    assert timeout == 3
    assert len(requests) == 1


def test_openrouter_diagnostics_retries_delayed_generation(monkeypatch):
    monkeypatch.setenv(provider.PROVIDER_DIAGNOSTICS_ENV_VAR, "1")
    monkeypatch.setattr(
        http,
        "post_json",
        lambda url, payload, headers: {"id": "gen-123", "choices": [{"message": {"content": "hi"}}]},
    )
    attempts = []
    delays = []

    def fake_urlopen(request, timeout):
        attempts.append(request)
        if len(attempts) < 3:
            raise _http_error(404)
        return FakeOpenRouterResponse({"data": {"provider_name": "CoreWeave"}})

    monkeypatch.setattr(provider, "urlopen", fake_urlopen)
    monkeypatch.setattr(provider, "_sleep", delays.append)

    answer, usage = provider.call("vendor/model", "system", [], api_key="test-key")

    assert answer.text == "hi"
    assert usage["generation_id"] == "gen-123"
    assert provider._lookup_upstream_provider(usage["generation_id"], "test-key") == "CoreWeave"
    assert len(attempts) == 3
    assert delays == [5, 10]


def test_openrouter_diagnostics_reports_why_lookup_failed(monkeypatch):
    delays = []
    monkeypatch.setattr(provider, "_sleep", delays.append)
    monkeypatch.setattr(provider, "urlopen", lambda request, timeout: (_ for _ in ()).throw(_http_error(404)))

    with pytest.raises(LookupError, match="after 60s"):
        provider._lookup_upstream_provider("gen-123", "test-key")
    assert delays == [5, 10, 15, 15, 15]

    monkeypatch.setattr(provider, "urlopen", lambda request, timeout: (_ for _ in ()).throw(_http_error(429)))
    with pytest.raises(HTTPError):
        provider._lookup_upstream_provider("gen-123", "test-key")


def test_openrouter_diagnostics_skips_lookup_without_generation_id(monkeypatch):
    monkeypatch.setenv(provider.PROVIDER_DIAGNOSTICS_ENV_VAR, "1")
    monkeypatch.setattr(
        http,
        "post_json",
        lambda url, payload, headers: {"choices": [{"message": {"content": "hi"}}]},
    )
    monkeypatch.setattr(provider, "urlopen", lambda request, timeout: pytest.fail("unexpected lookup"))

    _, usage = provider.call("vendor/model", "system", [], api_key="test-key")

    assert usage["generation_id"] is None


def test_openrouter_diagnostics_is_off_by_default_even_with_generation_id(monkeypatch):
    monkeypatch.setattr(
        http,
        "post_json",
        lambda url, payload, headers: {"id": "gen-123", "choices": [{"message": {"content": "hi"}}]},
    )
    monkeypatch.setattr(provider, "urlopen", lambda request, timeout: pytest.fail("unexpected lookup"))

    _, usage = provider.call("vendor/model", "system", [], api_key="test-key")

    assert "upstream_provider" not in usage


def test_call_anthropic_uses_messages_shape_and_normalizes_usage(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeOpenRouterResponse(
            {
                "content": [{"type": "text", "text": "hi"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        )

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    answer, usage = anthropic.call(
        "claude-3-haiku-20240307", "system prompt", [{"role": "user", "content": "task"}]
    )

    request = captured["request"]
    assert request.full_url == "https://api.anthropic.com/v1/messages"
    assert request.get_header("X-api-key") == "anthropic-test-key"
    assert request.get_header("Anthropic-version") == "2023-06-01"
    assert json.loads(request.data) == {
        "model": "claude-3-haiku-20240307",
        "max_tokens": 16000,
        "system": "system prompt",
        "messages": [{"role": "user", "content": "task"}],
        "cache_control": {"type": "ephemeral"},
    }
    assert answer.text == "hi"
    assert answer.tool_calls == ()
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 5
    assert usage["cost_estimated"] is True
    assert isinstance(usage["cost"], float)
    assert usage["cost"] > 0


def test_call_anthropic_returns_none_for_missing_usage_fields(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    monkeypatch.setattr(
        http,
        "urlopen",
        lambda request, timeout=None: FakeOpenRouterResponse({"content": [{"type": "text", "text": "hi"}]}),
    )

    _, usage = anthropic.call("claude-3-haiku-20240307", "system prompt", [])

    assert usage == {"cost": None, "prompt_tokens": None, "completion_tokens": None, "cost_estimated": True}


@pytest.mark.parametrize("stop_reason,truncated", [
    ("end_turn", False), ("max_tokens", True), ("model_context_window_exceeded", True),
])
def test_anthropic_termination_classification_preserves_returned_answer_and_usage(
    monkeypatch, install_fake_urlopen, stop_reason, truncated
):
    calls = install_fake_urlopen([FakeOpenRouterResponse({
        "content": [{"type": "text", "text": "summary text"}], "stop_reason": stop_reason,
        "usage": {"input_tokens": 91, "cache_read_input_tokens": 15,
                  "cache_creation_input_tokens": 5, "output_tokens": 7},
    })])
    pricing = []
    monkeypatch.setattr(cost, "estimate", lambda *args, **kwargs: pricing.append((args, kwargs)) or 0.1)
    answer, usage = anthropic.call("fixture-model", "system", [{"role": "user", "content": "task"}])
    assert len(calls) == 1
    assert answer.text == "summary text" and answer.tool_calls == ()
    assert answer.termination == stop_reason and answer.truncated is truncated
    assert usage == {"prompt_tokens": 111, "completion_tokens": 7, "cached_tokens": 15,
                     "cache_write_tokens": 5, "cost": 0.1, "cost_estimated": True}
    assert pricing == [(("fixture-model", 111, 7), {"provider": "anthropic", "cached_tokens": 15,
                        "cache_write_tokens": 5, "cache_creation_token_details": None})]


@pytest.mark.parametrize(
    ("provider_module", "key_name", "model", "response", "url", "header", "messages", "body"),
    [
        (
            openai,
            "OPENAI_API_KEY",
            "gpt-5.4",
            {"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5,
             "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}}},
            "https://api.openai.com/v1/chat/completions",
            ("Authorization", "Bearer openai-test-key"),
            [{"role": "user", "content": "task"}],
            {"model": "gpt-5.4", "messages": [{"role": "system", "content": "system prompt"}, {"role": "user", "content": "task"}]},
        ),
        (
            gemini,
            "GEMINI_API_KEY",
            "gemini-2.5-flash",
            {"candidates": [{"content": {"parts": [{"text": "hi"}]}}], "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}},
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            ("X-goog-api-key", "gemini-test-key"),
            [{"role": "user", "content": "task"}, {"role": "assistant", "content": "earlier answer"}],
            {"systemInstruction": {"parts": [{"text": "system prompt"}]}, "contents": [{"role": "user", "parts": [{"text": "task"}]}, {"role": "model", "parts": [{"text": "earlier answer"}]}]},
        ),
    ],
)
def test_estimating_providers_use_vendor_wire_shape_and_normalize_usage(
    monkeypatch, provider_module, key_name, model, response, url, header, messages, body
):
    monkeypatch.setenv(key_name, header[1].split(" ")[-1])
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeOpenRouterResponse(response)

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    answer, usage = provider_module.call(model, "system prompt", messages)

    request = captured["request"]
    assert request.full_url == url
    assert request.get_header(header[0]) == header[1]
    cap = {"max_completion_tokens": 16000} if provider_module is openai else {"generationConfig": {"maxOutputTokens": 16000}}
    assert json.loads(request.data) == {**body, **cap}
    assert answer.text == "hi"
    assert answer.tool_calls == ()
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 5
    assert usage["cost_estimated"] is True
    assert isinstance(usage["cost"], float)
    assert usage["cost"] > 0


@pytest.mark.parametrize("provider_module, model", [(openai, "gpt-5.4"), (gemini, "gemini-2.5-flash")])
def test_estimating_providers_return_none_for_missing_usage_fields(monkeypatch, provider_module, model):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    response = {"choices": [{"message": {"content": "hi"}}]} if provider_module is openai else {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}
    monkeypatch.setattr(http, "urlopen", lambda request, timeout=None: FakeOpenRouterResponse(response))

    _, usage = provider_module.call(model, "system prompt", [])

    assert usage == {"cost": None, "prompt_tokens": None, "completion_tokens": None, "cost_estimated": True}


@pytest.mark.parametrize("provider_module", [openai, gemini])
@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_openai_and_gemini_retry_transient_http_codes(provider_module, code):
    assert provider_module.is_retryable(_http_error(code)) is True


@pytest.mark.parametrize("provider_module", [openai, gemini])
@pytest.mark.parametrize("code", [400, 401, 403, 404, 529])
def test_openai_and_gemini_reject_nonretryable_http_codes(provider_module, code):
    assert provider_module.is_retryable(_http_error(code)) is False


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504, 529])
def test_anthropic_is_retryable_for_its_transient_http_codes(code):
    assert anthropic.is_retryable(_http_error(code)) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_anthropic_is_not_retryable_for_permanent_http_codes(code):
    assert anthropic.is_retryable(_http_error(code)) is False


def test_estimate_uses_real_litellm_pricing_and_tolerates_unknown_models():
    estimate = cost.estimate("claude-3-haiku-20240307", 10, 5)

    assert isinstance(estimate, float)
    assert estimate > 0
    assert cost.estimate("not-a-real-model", 10, 5) is None
    assert cost.estimate("claude-3-haiku-20240307", None, 5) is None


@pytest.mark.parametrize("provider_name,model,expected", [
    ("anthropic", "exact", "exact"), ("openai", "exact", "exact"),
    ("openrouter", "exact", "openrouter/exact"), ("gemini", "exact", "gemini/exact")])
def test_capacity_metadata_looks_up_exact_provider_name(monkeypatch, provider_name, model, expected):
    from personal_agent import context_budget, token_estimate
    library, _ = token_estimate.local_library()
    seen = []
    monkeypatch.setattr(library, "get_model_info", lambda name, custom_llm_provider: seen.append((name, custom_llm_provider)) or {"max_input_tokens": 50000})
    assert context_budget.model_info(provider_name, model) == {"max_input_tokens": 50000}
    assert seen == [(expected, provider_name)]


def test_call_openrouter_returns_none_for_missing_usage_fields(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def fake_urlopen(request, timeout=None):
        return FakeOpenRouterResponse({"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    answer, usage = provider.call(
        "vendor/model", "system prompt", [{"role": "user", "content": "task"}]
    )

    assert answer.text == "hi"
    assert answer.tool_calls == ()
    assert usage == {
        "cost": None, "prompt_tokens": None, "completion_tokens": None,
        "cached_tokens": None, "cache_write_tokens": None,
    }


def test_call_openrouter_reads_present_usage_fields(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def fake_urlopen(request, timeout=None):
        return FakeOpenRouterResponse(
            {
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"cost": 0.002, "prompt_tokens": 10, "completion_tokens": 5},
            }
        )

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    _, usage = provider.call(
        "vendor/model", "system prompt", [{"role": "user", "content": "task"}]
    )

    assert usage == {
        "cost": 0.002, "prompt_tokens": 10, "completion_tokens": 5,
        "cached_tokens": None, "cache_write_tokens": None,
    }


def test_call_openrouter_uses_bounded_timeout(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["timeout"] = timeout
        return FakeOpenRouterResponse({"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    provider.call("vendor/model", "system prompt", [{"role": "user", "content": "task"}])

    assert captured["timeout"] == 60


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_is_retryable_true_for_retryable_http_codes(code):
    assert provider.is_retryable(_http_error(code)) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_is_retryable_false_for_other_http_codes(code):
    assert provider.is_retryable(_http_error(code)) is False


def test_is_retryable_true_for_timeout_error():
    assert provider.is_retryable(TimeoutError("timed out")) is True


def test_is_retryable_true_for_socket_timeout():
    assert provider.is_retryable(socket.timeout("timed out")) is True


def test_is_retryable_true_for_url_error_wrapping_timeout():
    assert provider.is_retryable(URLError(TimeoutError("timed out"))) is True


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("reason,retryable", [("SSLV3_ALERT_BAD_RECORD_MAC", True),
                                            ("DECRYPTION_FAILED_OR_BAD_RECORD_MAC", True),
                                            ("CERTIFICATE_VERIFY_FAILED", False), ("UNSUPPORTED_PROTOCOL", False)])
def test_tls_retry_classification_uses_the_transport_reason(wrapped, reason, retryable):
    error = ssl.SSLError(ssl.SSL_ERROR_SSL, "TLS failed")
    error.reason = reason
    assert provider.is_retryable(URLError(error) if wrapped else error) is retryable


@pytest.mark.parametrize("error", [ssl.SSLError("unknown TLS failure"), ssl.SSLCertVerificationError("invalid certificate")])
def test_unknown_tls_and_certificate_failures_are_not_retried(error):
    assert not provider.is_retryable(error)


def test_is_retryable_false_for_url_error_wrapping_other_reason():
    assert provider.is_retryable(URLError("connection refused")) is False


@pytest.mark.parametrize(
    "exc",
    [
        KeyError("choices"),
        IndexError("list index out of range"),
        json.JSONDecodeError("bad json", "doc", 0),
    ],
)
def test_is_retryable_false_for_parse_shaped_exceptions(exc):
    assert provider.is_retryable(exc) is False


def test_is_retryable_false_for_unrecognised_exception_type():
    assert provider.is_retryable(RuntimeError("something else")) is False


# --- Tool contract translation (R07-R09) -----------------------------------


def test_openai_sends_tool_schema_and_parses_tool_call(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeOpenRouterResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "calculator", "arguments": '{"expression": "2+2"}'},
                                }
                            ],
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    assistant, _ = openai.call("gpt-5.4", "system prompt", [{"role": "user", "content": "add"}], tools=(CALC_TOOL,))

    body = json.loads(captured["request"].data)
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": CALC_TOOL.description,
                "parameters": CALC_TOOL.parameters,
            },
        }
    ]
    assert assistant.text is None
    assert assistant.tool_calls == (
        ToolCall(id="call_1", name="calculator", arguments={"expression": "2+2"}, arguments_raw='{"expression": "2+2"}'),
    )


def test_openai_represents_malformed_tool_call_arguments_for_local_rejection(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setattr(
        http,
        "urlopen",
        lambda request, timeout=None: FakeOpenRouterResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {"id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": "not json"}}
                            ],
                        }
                    }
                ]
            }
        ),
    )

    assistant, _ = openai.call("gpt-5.4", "system prompt", [], tools=(CALC_TOOL,))

    assert assistant.tool_calls[0].arguments is None
    assert assistant.tool_calls[0].arguments_raw == "not json"


def test_openai_replays_prior_tool_round_with_json_string_arguments_and_tool_role_result(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeOpenRouterResponse({"choices": [{"message": {"content": "4"}}]})

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    messages = [
        {"role": "user", "content": "what is 2+2?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "name": "calculator", "arguments": {"expression": "2+2"}, "arguments_raw": '{"expression": "2+2"}'}
            ],
        },
        {"role": "tool_result", "id": "call_1", "name": "calculator", "content": {"result": 4}, "is_error": False},
    ]

    openai.call("gpt-5.4", "system prompt", messages, tools=(CALC_TOOL,))

    body = json.loads(captured["request"].data)
    assert body["messages"][2] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": '{"expression": "2+2"}'}}
        ],
    }
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "content": json.dumps({"result": 4})}


def test_anthropic_sends_input_schema_and_parses_mixed_text_and_tool_use(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeOpenRouterResponse(
            {
                "content": [
                    {"type": "text", "text": "let me check"},
                    {"type": "tool_use", "id": "toolu_1", "name": "calculator", "input": {"expression": "2+2"}},
                ]
            }
        )

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    assistant, _ = anthropic.call(
        "claude-3-haiku-20240307", "system prompt", [{"role": "user", "content": "add"}], tools=(CALC_TOOL,)
    )

    body = json.loads(captured["request"].data)
    assert body["tools"] == [
        {"name": "calculator", "description": CALC_TOOL.description, "input_schema": CALC_TOOL.parameters}
    ]
    assert assistant.text == "let me check"
    assert assistant.tool_calls[0].id == "toolu_1"
    assert assistant.tool_calls[0].name == "calculator"
    assert assistant.tool_calls[0].arguments == {"expression": "2+2"}


def test_anthropic_places_all_tool_results_in_one_immediately_following_user_message(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeOpenRouterResponse({"content": [{"type": "text", "text": "done"}]})

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    messages = [
        {"role": "user", "content": "compute two things"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "id_1", "name": "calculator", "arguments": {"expression": "1+1"}},
                {"id": "id_2", "name": "calculator", "arguments": {"expression": "2+2"}},
            ],
        },
        {"role": "tool_result", "id": "id_1", "name": "calculator", "content": {"result": 2}, "is_error": False},
        {"role": "tool_result", "id": "id_2", "name": "calculator", "content": {"error": "boom"}, "is_error": True},
    ]

    anthropic.call("claude-3-haiku-20240307", "system prompt", messages, tools=(CALC_TOOL,))

    body = json.loads(captured["request"].data)
    assert body["messages"][2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "id_1", "content": json.dumps({"result": 2})},
            {"type": "tool_result", "tool_use_id": "id_2", "content": json.dumps({"error": "boom"}), "is_error": True},
        ],
    }


def test_gemini_sends_function_declarations_and_parses_function_call_with_explicit_id(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeOpenRouterResponse(
            {"candidates": [{"content": {"parts": [{"functionCall": {"id": "call_9", "name": "calculator", "args": {"expression": "2+2"}}}]}}]}
        )

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    assistant, _ = gemini.call(
        "gemini-2.5-flash", "system prompt", [{"role": "user", "content": "add"}], tools=(CALC_TOOL,)
    )

    body = json.loads(captured["request"].data)
    assert body["tools"] == [
        {"functionDeclarations": [{"name": "calculator", "description": CALC_TOOL.description, "parameters": CALC_TOOL.parameters}]}
    ]
    assert assistant.tool_calls[0].id == "call_9"
    assert assistant.tool_calls[0].arguments == {"expression": "2+2"}


def test_gemini_generates_a_stable_internal_id_when_the_response_omits_one(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setattr(
        http,
        "urlopen",
        lambda request, timeout=None: FakeOpenRouterResponse(
            {"candidates": [{"content": {"parts": [{"functionCall": {"name": "calculator", "args": {"expression": "2+2"}}}]}}]}
        ),
    )

    assistant, _ = gemini.call("gemini-2.5-flash", "system prompt", [], tools=(CALC_TOOL,))

    assert assistant.tool_calls[0].id
    assert assistant.tool_calls[0].name == "calculator"


def test_gemini_replays_original_parts_and_thought_signature_across_tool_rounds(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    requests = []

    def fake_urlopen(request, timeout=None):
        requests.append(json.loads(request.data))
        if len(requests) == 1:
            return FakeOpenRouterResponse(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"functionCall": {"name": "calculator", "args": {"expression": "2+2"}}, "thoughtSignature": "sig-abc"}
                                ]
                            }
                        }
                    ]
                }
            )
        return FakeOpenRouterResponse({"candidates": [{"content": {"parts": [{"text": "the answer is 4"}]}}]})

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    messages = [{"role": "user", "content": "what is 2+2?"}]
    assistant1, _ = gemini.call("gemini-2.5-flash", "system prompt", messages, tools=(CALC_TOOL,))

    assert assistant1.tool_calls[0].name == "calculator"
    call_id = assistant1.tool_calls[0].id

    messages = [
        *messages,
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": call_id, "name": "calculator", "arguments": {"expression": "2+2"}, "id_is_generated": True}],
        },
        {
            "role": "tool_result",
            "id": call_id,
            "name": "calculator",
            "content": {"result": 4},
            "is_error": False,
            "id_is_generated": True,
        },
    ]
    assistant2, _ = gemini.call(
        "gemini-2.5-flash", "system prompt", messages, tools=(CALC_TOOL,), replay=assistant1.replay
    )

    assert assistant2.text == "the answer is 4"
    second_request_contents = requests[1]["contents"]
    model_turn = next(c for c in second_request_contents if c["role"] == "model")
    assert model_turn["parts"] == [
        {"functionCall": {"name": "calculator", "args": {"expression": "2+2"}}, "thoughtSignature": "sig-abc"}
    ]
    function_response_turn = next(c for c in second_request_contents if c["role"] == "user" and "functionResponse" in c["parts"][0])
    assert function_response_turn["parts"] == [{"functionResponse": {"name": "calculator", "response": {"result": 4}}}]


def test_gemini_preserves_vendor_ids_on_a_same_name_batch_so_results_are_not_transposed(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    requests = []

    def fake_urlopen(request, timeout=None):
        requests.append(json.loads(request.data))
        if len(requests) == 1:
            return FakeOpenRouterResponse(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"functionCall": {"id": "call_a", "name": "calculator", "args": {"expression": "2+2"}}},
                                    {"functionCall": {"id": "call_b", "name": "calculator", "args": {"expression": "3+3"}}},
                                ]
                            }
                        }
                    ]
                }
            )
        return FakeOpenRouterResponse({"candidates": [{"content": {"parts": [{"text": "4 and 6"}]}}]})

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    messages = [{"role": "user", "content": "what is 2+2 and 3+3?"}]
    assistant1, _ = gemini.call("gemini-2.5-flash", "system prompt", messages, tools=(CALC_TOOL,))

    assert [call.id for call in assistant1.tool_calls] == ["call_a", "call_b"]
    assert all(not call.id_is_generated for call in assistant1.tool_calls)

    messages = [
        *messages,
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_a", "name": "calculator", "arguments": {"expression": "2+2"}},
                {"id": "call_b", "name": "calculator", "arguments": {"expression": "3+3"}},
            ],
        },
        {"role": "tool_result", "id": "call_a", "name": "calculator", "content": {"result": 4}, "is_error": False},
        {"role": "tool_result", "id": "call_b", "name": "calculator", "content": {"result": 6}, "is_error": False},
    ]
    assistant2, _ = gemini.call(
        "gemini-2.5-flash", "system prompt", messages, tools=(CALC_TOOL,), replay=assistant1.replay
    )

    assert assistant2.text == "4 and 6"
    second_request_contents = requests[1]["contents"]
    function_response_turn = next(c for c in second_request_contents if c["role"] == "user" and "functionResponse" in c["parts"][0])
    assert function_response_turn["parts"] == [
        {"functionResponse": {"id": "call_a", "name": "calculator", "response": {"result": 4}}},
        {"functionResponse": {"id": "call_b", "name": "calculator", "response": {"result": 6}}},
    ]


@pytest.mark.parametrize(
    "provider_module, key_name, model, url",
    [
        (openai, "OPENAI_API_KEY", "gpt-5.4", "https://api.openai.com/v1/chat/completions"),
        (anthropic, "ANTHROPIC_API_KEY", "claude-3-haiku-20240307", "https://api.anthropic.com/v1/messages"),
        (gemini, "GEMINI_API_KEY", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"),
        (provider, "OPENROUTER_API_KEY", "vendor/model", "https://openrouter.ai/api/v1/chat/completions"),
    ],
)
def test_rejected_tool_support_raises_a_readable_nonretryable_error_naming_provider_and_model(
    monkeypatch, provider_module, key_name, model, url
):
    monkeypatch.setenv(key_name, "test-key")
    monkeypatch.setattr(
        http,
        "urlopen",
        lambda request, timeout=None: (_ for _ in ()).throw(
            _http_error_with_body(400, {"error": {"message": "this model does not support tools"}})
        ),
    )

    with pytest.raises(ToolsUnsupportedError) as exc_info:
        provider_module.call(model, "system prompt", [{"role": "user", "content": "task"}], tools=(CALC_TOOL,))

    assert model in str(exc_info.value)
    assert provider_module.is_retryable(exc_info.value) is False


def test_openai_invalid_skill_schema_remains_original_nonretryable_http_error(monkeypatch):
    message = ("Invalid schema for function 'skill': schema must have 'type: object' and not have "
               "'oneOf'/'anyOf'/'allOf'/'enum'/'const'/'not' at the top level")
    failure = _http_error_with_body(400, {"error": {"message": message,
        "type": "invalid_request_error", "param": "tools[12].function.parameters", "code": "invalid_function_parameters"}})
    monkeypatch.setattr(http, "urlopen", lambda request, timeout=None: (_ for _ in ()).throw(failure))

    with pytest.raises(HTTPError) as exc_info:
        openai.call("gpt-5.4", "system", [{"role": "user", "content": "task"}],
                    tools=(CALC_TOOL,), api_key="test-key")

    assert exc_info.value is failure
    assert message in str(failure)
    assert "invalid_function_parameters" in str(failure)
    assert openai.is_retryable(failure) is False


@pytest.mark.parametrize("code", [400, 404, 422])
@pytest.mark.parametrize("message", ["Invalid tool arguments", "Unsupported tool type: custom",
                                      "Tool request requires authorization", "Tool endpoint not found"])
def test_unrelated_tool_http_errors_are_preserved(code, message):
    usage = {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.01}
    failure = _http_error_with_body(code, {"error": {"message": message}})

    http.raise_for_provider_error(failure, "openai", "gpt-5.4", True, usage)

    assert message in str(failure)
    assert failure.usage == usage
    assert openai.is_retryable(failure) is False


@pytest.mark.parametrize("message", ["Tools are not supported for this model", "Tool calling is unavailable",
                                      "This model does not support function calling",
                                      "No endpoints found that support tool use"])
def test_explicit_tool_support_rejection_preserves_usage(message):
    usage = {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.01}
    failure = _http_error_with_body(400, {"error": {"message": message}})

    with pytest.raises(ToolsUnsupportedError) as exc_info:
        http.raise_for_provider_error(failure, "openrouter", "vendor/model", True, usage)

    assert exc_info.value.usage == usage
    assert exc_info.value.__cause__ is failure
    assert message in str(exc_info.value)


def test_openrouter_sorts_by_price_above_min_throughput_and_requires_parameters_with_tools(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeOpenRouterResponse({"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    provider.call("vendor/model", "system prompt", [{"role": "user", "content": "task"}], tools=(CALC_TOOL,))

    body = json.loads(captured["request"].data)
    assert body["provider"] == {"sort": "price", "preferred_min_throughput": 85, "require_parameters": True}
    assert body["tools"] == [
        {"type": "function", "function": {"name": "calculator", "description": CALC_TOOL.description, "parameters": CALC_TOOL.parameters}}
    ]


def test_no_tools_key_sent_when_tools_not_offered(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeOpenRouterResponse({"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    provider.call("vendor/model", "system prompt", [{"role": "user", "content": "task"}])

    body = json.loads(captured["request"].data)
    assert "tools" not in body
    assert body["provider"] == {"sort": "price", "preferred_min_throughput": 85, "require_parameters": True}
