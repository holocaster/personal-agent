import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from personal_agent.providers import anthropic, gemini, http, openai, openrouter
from personal_agent.providers.contract import ContextOverflowError, ToolDef, ToolsUnsupportedError


def rejection(provider="openrouter", message=None, code=None, status=400):
    defaults = {
        "openai": "This model's maximum context length is 128000 tokens. However, you requested 130000 tokens (including tool tokens).",
        "openrouter": "This model's maximum context length is 128000 tokens. However, you requested 130000 tokens (including tool tokens).",
        "anthropic": "prompt is too long: 130000 tokens > 128000 maximum",
        "gemini": "The input token count (130000) exceeds the maximum number of tokens allowed (128000).",
    }
    error = {"message": defaults[provider] if message is None else message}
    if code is not None:
        error["code"] = code
    return HTTPError("https://example.invalid", status, "Bad Request", {},
                     BytesIO(json.dumps({"error": error}).encode()))


def choice_rejection(error=None):
    return {"choices": [{
        "message": {"role": "assistant", "content": "partial output..."},
        "finish_reason": "error",
        "error": error if error is not None else {
            "code": 400, "message": "Provider returned error including tool tokens",
            "metadata": {"error_type": "context_length_exceeded"},
        },
    }]}


@pytest.mark.parametrize("metadata", [
    {"error_type": "context_length_exceeded"},
    {"provider_code": "context_length_exceeded"},
    {"raw": json.dumps({"error": {"code": "context_length_exceeded", "message": "too much input"}})},
])
@pytest.mark.parametrize("choice_index", [0, 1])
@pytest.mark.parametrize("status", [400, 502])
def test_openrouter_choice_error_rejects_partial_content(monkeypatch, metadata, choice_index, status):
    data = choice_rejection({"code": status, "message": "Provider returned error including tool tokens", "metadata": metadata})
    if choice_index:
        data["choices"].insert(0, {"message": {"content": "other partial output"}, "finish_reason": "stop"})
    monkeypatch.setattr(http, "post_json", lambda *_: data)
    with pytest.raises(ContextOverflowError, match="context overflow.*including tool tokens"):
        openrouter.call("vendor/model", "system", [], tools=(ToolDef("calculator", "calculate", {}),))


@pytest.mark.parametrize("status,error_type,message,expected", [
    (400, "invalid_request", "This model does not support tools", ToolsUnsupportedError),
    (400, "max_tokens_exceeded", "Generation reached max_tokens", HTTPError),
    (400, "invalid_request", "Invalid request", HTTPError),
    (413, "payload_too_large", "Request payload too large", HTTPError),
    (401, "authentication", "Invalid credentials", HTTPError),
    (429, "rate_limit_exceeded", "Rate limit exceeded", HTTPError),
    (502, "provider_unavailable", "Provider disconnected mid-stream", HTTPError),
])
def test_openrouter_choice_errors_use_narrow_taxonomy(monkeypatch, status, error_type, message, expected):
    data = choice_rejection({"code": status, "message": message, "metadata": {"error_type": error_type}})
    data["choices"][0]["message"]["content"] = "partial output discussing tools " * 100
    monkeypatch.setattr(http, "post_json", lambda *_: data)
    with pytest.raises(expected, match=message) as caught:
        openrouter.call("vendor/model", "system", [], tools=(ToolDef("calculator", "calculate", {}),))
    assert type(caught.value) is expected
    if expected is HTTPError:
        assert caught.value.code == status
    assert "partial output" not in str(caught.value)


@pytest.mark.parametrize("provider", [openai, openrouter, anthropic, gemini])
def test_positive_overflow_precedes_tool_detection_and_keeps_evidence(provider, monkeypatch):
    failure = rejection(provider.PROVIDER_LABEL)
    reads = []
    original = failure.read
    def read():
        reads.append(1)
        return original()
    failure.read = read
    def reject(*args):
        raise failure
    monkeypatch.setattr(http, "post_json", reject)
    with pytest.raises(RuntimeError, match="context overflow") as caught:
        provider.call("test-model", "system", [{"role": "user", "content": "pending"}],
                      tools=(ToolDef("calculator", "calculate", {}),))
    assert type(caught.value).__name__ == "ContextOverflowError"
    assert "128000" in str(caught.value)
    assert caught.value.__cause__ is failure
    assert reads == [1]


@pytest.mark.parametrize("provider", [openai, openrouter, anthropic, gemini])
@pytest.mark.parametrize("message,status", [
    ("Invalid request", 400), ("Request payload too large", 413),
    ("INVALID_ARGUMENT", 400), ("max_tokens exceeds output limit", 400),
    ("max_completion_tokens is not supported", 400), ("Invalid API key", 401),
    ("This model's maximum context length is 128000 tokens; max_tokens exceeds the output limit", 400),
    ("input token rate limit exceeded", 429), ("Timed out", 504),
])
def test_non_overflow_errors_keep_type_and_readable_diagnostics(provider, monkeypatch, message, status):
    failure = rejection(provider.PROVIDER_LABEL, message, status=status)
    def reject(*args):
        raise failure
    monkeypatch.setattr(http, "post_json", reject)
    with pytest.raises(HTTPError, match=message) as caught:
        provider.call("test-model", "system", [])
    assert caught.value is failure


@pytest.mark.parametrize("provider", [openai, openrouter, anthropic, gemini])
def test_true_tool_rejection_stays_unsupported(provider, monkeypatch):
    failure = rejection(provider.PROVIDER_LABEL, "This model does not support tools")
    def reject(*args):
        raise failure
    monkeypatch.setattr(http, "post_json", reject)
    with pytest.raises(ToolsUnsupportedError, match="does not support tools"):
        provider.call("test-model", "system", [], tools=(ToolDef("calculator", "calculate", {}),))


@pytest.mark.parametrize("metadata", [
    {"error_type": "context_length_exceeded"},
    {"provider_name": "OpenAI", "raw": json.dumps({"error": {"code": "context_length_exceeded", "message": "too much input"}})},
    {"provider_name": "Anthropic", "raw": {"error": {"type": "invalid_request_error", "message": "prompt is too long: 130000 tokens > 128000 maximum"}}},
])
def test_openrouter_typed_and_nested_upstream_evidence(metadata, monkeypatch):
    failure = HTTPError("https://example.invalid", 400, "Bad Request", {}, BytesIO(json.dumps({
        "error": {"code": 400, "message": "Provider returned error", "metadata": metadata}}).encode()))
    def reject(*args):
        raise failure
    monkeypatch.setattr(http, "post_json", reject)
    with pytest.raises(RuntimeError, match="context overflow") as caught:
        openrouter.call("vendor/model", "system", [])
    assert type(caught.value).__name__ == "ContextOverflowError"


def test_openrouter_http_success_error_envelope_is_still_a_rejection(monkeypatch):
    monkeypatch.setattr(http, "post_json", lambda *_: {
        "error": {"code": 400, "message": "Provider returned error", "metadata": {"error_type": "context_length_exceeded"}}})
    with pytest.raises(RuntimeError, match="context overflow") as caught:
        openrouter.call("vendor/model", "system", [])
    assert type(caught.value).__name__ == "ContextOverflowError"


def test_plain_anthropic_prompt_overflow_keeps_readable_evidence(monkeypatch):
    failure = HTTPError("fake", 400, "Bad Request", {}, BytesIO(b"prompt is too long: 130000 tokens > 128000 maximum"))
    def reject(*args):
        raise failure
    monkeypatch.setattr(http, "post_json", reject)
    with pytest.raises(RuntimeError, match="context overflow"):
        anthropic.call("model", "system", [])


def test_official_openai_requested_token_message_is_positive_without_a_code(monkeypatch):
    failure = rejection("openai", "This model's maximum context length is 8192 tokens, however you requested "
                        "10001 tokens (10001 in your prompt; 0 for the completion). Please reduce your prompt; or completion length.")
    def reject(*args):
        raise failure
    monkeypatch.setattr(http, "post_json", reject)
    with pytest.raises(RuntimeError, match="context overflow"):
        openai.call("model", "system", [])
