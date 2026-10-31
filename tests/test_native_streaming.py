import json
from collections import deque
from io import StringIO
from pathlib import Path

import pytest

from personal_agent.providers import anthropic, gemini, http
from tests.test_streaming import StreamResponse, frame, install_stream


def message_start(usage=None):
    message = {"role": "assistant", "content": [], "stop_reason": None}
    if usage is not None:
        message["usage"] = usage
    return frame({"type": "message_start", "message": message})


def block_start(index, block):
    return frame({"type": "content_block_start", "index": index, "content_block": block})


def block_delta(index, kind, **fields):
    return frame({"type": "content_block_delta", "index": index, "delta": {"type": kind, **fields}})


def block_stop(index):
    return frame({"type": "content_block_stop", "index": index})


def message_delta(reason="end_turn", usage=None):
    data = {"type": "message_delta", "delta": {"stop_reason": reason}}
    if usage is not None:
        data["usage"] = usage
    return frame(data)


def test_anthropic_text_precedes_native_completion_and_usage_is_cumulative(monkeypatch):
    seen = []

    def finish():
        assert seen == ["héllo"]
        return block_stop(0)

    response, requests = install_stream(monkeypatch, [
        message_start({"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 4}),
        block_start(0, {"type": "text", "text": ""}),
        block_delta(0, "text_delta", text="héllo"), finish,
        message_delta(usage={"output_tokens": 2}),
        message_delta(usage={"input_tokens": 12, "output_tokens": 3, "cache_creation_input_tokens": 0}),
        frame({"type": "message_stop"})])
    assistant, usage = anthropic.call("fixture", "system", [], api_key="fixture-key", on_text=seen.append)
    assert assistant.text == "héllo" and assistant.termination == "end_turn"
    assert usage["prompt_tokens"] == 16 and usage["completion_tokens"] == 3
    assert usage["cached_tokens"] == 4 and usage["cache_write_tokens"] == 0
    assert response.closed
    assert requests[0].full_url == anthropic.API_URL
    assert requests[0].get_header("Anthropic-version") == "2023-06-01"
    payload = json.loads(requests[0].data)
    assert payload["stream"] is True and payload["max_tokens"] == 16000


def candidate(parts=None, finish=None, **extra):
    value = {"index": 0}
    if parts is not None:
        value["content"] = {"role": "model", "parts": parts}
    if finish is not None:
        value["finishReason"] = finish
    return {"candidates": [value], **extra}


def test_gemini_collects_trailing_signature_and_usage_through_eof(monkeypatch):
    seen = []
    parts = [{"text": "private", "thought": True, "thoughtSignature": "thought-sig"},
             {"text": "hé"}, {"text": "llo", "thoughtSignature": "text-sig"},
             {"text": "", "thoughtSignature": "trailing-sig"}]

    def trailing():
        assert seen == ["hé", "llo"]
        return frame(candidate(parts[3:], usageMetadata={"promptTokenCount": 12, "candidatesTokenCount": 3,
                                                        "cachedContentTokenCount": 0}))

    response, requests = install_stream(monkeypatch, [
        frame(candidate(parts[:2], usageMetadata={"promptTokenCount": 10, "candidatesTokenCount": 1})),
        frame(candidate(parts[2:3], "STOP")), trailing])
    assistant, usage = gemini.call("fixture", "system", [], api_key="fixture-key", on_text=seen.append)
    assert assistant.text == "héllo" and assistant.termination == "STOP"
    assert assistant.replay["contents"] == [{"role": "model", "parts": parts}]
    assert usage["prompt_tokens"] == 12 and usage["completion_tokens"] == 3 and usage["cached_tokens"] == 0
    assert response.closed
    assert requests[0].full_url.endswith("/fixture:streamGenerateContent?alt=sse")
    assert requests[0].get_header("X-goog-api-key") == "fixture-key"
    assert json.loads(requests[0].data)["generationConfig"] == {"maxOutputTokens": 16000}


def test_streamed_gemini_completed_prefix_resumes_with_original_parts_and_ids(route_env, monkeypatch):
    from personal_agent import call_log
    from personal_agent.routing import runtime_config
    from personal_agent.terminal.repl import run_repl
    from tests.test_continuation import Box

    monkeypatch.setenv("PA_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-key")
    parts = [{"text": "private", "thought": True, "thoughtSignature": "thought-sig"},
             {"text": "check"}, {"text": "ing", "thoughtSignature": "text-sig"},
             {"functionCall": {"id": "vendor-id", "name": "calculator", "args": {"expression": "2+2"}},
              "thoughtSignature": "call-sig"},
             {"functionCall": {"name": "calculator", "args": {"expression": "3+3"}}},
             {"text": "", "thoughtSignature": "empty-sig"},
             {"thought": True, "thoughtSignature": "only-sig"}]
    responses = deque([
        StreamResponse([frame(candidate(parts[:3])), frame(candidate(parts[3:5], "STOP")), frame(candidate(parts[5:]))]),
        StreamResponse([frame(candidate([{"text": "partial"}])), TimeoutError("follow-up failed")]),
        StreamResponse([frame(candidate([{"text": "done"}], "STOP"))])])
    all_responses = list(responses)
    requests = []

    def open_response(request, timeout):
        requests.append(request)
        return responses.popleft()

    monkeypatch.setattr(http, "urlopen", open_response)
    output = StringIO()
    config = runtime_config.load()
    run_repl(config, input_stream=StringIO("task\nexit\n"), output_stream=output)
    sid = call_log.current_session_id()
    turns, summary, todos, state = call_log.load_conversation(sid)
    assert turns == ()
    pending = call_log.load_pending_turn(sid)
    assert pending[1]["replay"] is not None, output.getvalue()
    assert pending[1]["replay"]["contents"][1] == {"role": "model", "parts": parts}
    monkeypatch.setenv("GEMINI_API_KEY", "replacement-key")
    run_repl(runtime_config.load(), input_box=Box(["/mode plan", "/retry", "exit"]),
             resumed=(sid, turns, summary, todos, state), output_stream=output)
    assert len(requests) == 3 and not responses
    payload = json.loads(requests[-1].data)
    assert requests[-1].get_header("X-goog-api-key") == "replacement-key"
    assert "Investigate and discuss only" in payload["systemInstruction"]["parts"][0]["text"]
    assert payload["contents"][1] == {"role": "model", "parts": parts}
    assert payload["contents"][2]["parts"] == [
        {"functionResponse": {"id": "vendor-id", "name": "calculator", "response": {"result": 4}}},
        {"functionResponse": {"name": "calculator", "response": {"result": 6}}}]
    assert "partial" not in json.dumps(payload)
    rows = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    assert len([row for row in rows if row["type"] == "tool_execution"]) == 2
    assert len([row for row in rows if row["type"] == "turn_end" and row["status"] == "ok"]) == 1
    assert all(response.closed for response in all_responses)
    assert "private" not in output.getvalue() and "sig" not in output.getvalue()


@pytest.mark.parametrize("arguments, expected", [('{"expression":"2+2"}', {"expression": "2+2"}), ('{"broken":', None)])
def test_anthropic_hidden_blocks_and_completed_tool_json(monkeypatch, arguments, expected):
    seen = []
    response, _ = install_stream(monkeypatch, [message_start(),
        block_start(0, {"type": "thinking", "thinking": "", "signature": ""}),
        block_delta(0, "thinking_delta", thinking="private"),
        block_delta(0, "signature_delta", signature="hidden-signature"), block_stop(0),
        frame({"type": "ping"}), block_start(1, {"type": "redacted_thinking", "data": "hidden-data"}), block_stop(1),
        block_start(2, {"type": "text", "text": "check"}), block_delta(2, "text_delta", text="ing"), block_stop(2),
        block_start(3, {"type": "tool_use", "id": "vendor", "name": "calculator", "input": {}}),
        block_delta(3, "input_json_delta", partial_json=arguments[:5]),
        block_delta(3, "input_json_delta", partial_json=arguments[5:]), block_stop(3),
        message_delta("tool_use"), frame({"type": "message_stop"})])
    assistant, usage = anthropic.call("fixture", "", [], on_text=seen.append)
    assert seen == ["check", "ing"] and assistant.text == "checking"
    assert usage == {} and assistant.termination == "tool_use"
    assert len(assistant.tool_calls) == 1
    call = assistant.tool_calls[0]
    assert (call.id, call.name, call.arguments, call.arguments_raw) == ("vendor", "calculator", expected, arguments)
    assert response.closed


@pytest.mark.parametrize("chunks", [
    [], [message_start()], [block_start(0, {"type": "text", "text": "bad"})],
    [message_start(), message_start()],
    [message_start(), block_start(999999999, {"type": "text", "text": "bad"})],
    [message_start(), block_delta(0, "text_delta", text="bad")],
    [message_start(), block_start(True, {"type": "text", "text": "bad"})],
    [message_start(), block_start(0, {"type": "text", "text": ""}), message_delta()],
    [message_start(), block_start(0, {"type": "text", "text": ""}), block_delta(0, "thinking_delta", thinking="bad")],
    [message_start(), block_stop(0)],
    [message_start(), block_start(0, {"type": "text", "text": ""}), block_stop(0), block_stop(0)],
    [message_start(), message_delta(), frame({"type": "message_stop"}), frame({"type": "ping"})],
    [message_start(), message_delta(), frame({"type": "message_stop"}), b'data: {'],
    [message_start(), message_delta("bad"), frame({"type": "message_stop"})],
    [message_start(), message_delta("tool_use"), frame({"type": "message_stop"})],
    [message_start(), frame({"type": "message_stop"})],
])
def test_anthropic_invalid_order_or_incomplete_protocol_never_completes(monkeypatch, chunks):
    response, _ = install_stream(monkeypatch, chunks)
    with pytest.raises(ValueError):
        anthropic.call("fixture", "", [], on_text=lambda _: None)
    assert response.closed


@pytest.mark.parametrize("provider", [anthropic, gemini])
@pytest.mark.parametrize("failure", [TimeoutError("read failed"), KeyboardInterrupt(), RuntimeError("output failed")])
def test_native_failures_retain_trustworthy_usage_and_close(monkeypatch, provider, failure):
    if provider is anthropic:
        chunks = [message_start({"input_tokens": 5, "output_tokens": 0, "cache_read_input_tokens": 0})]
        text = block_start(0, {"type": "text", "text": "hello"})
    else:
        chunks = [frame({"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 0, "cachedContentTokenCount": 0}})]
        text = frame(candidate([{"text": "hello"}]))

    def callback(_):
        if isinstance(failure, RuntimeError):
            raise failure

    response, _ = install_stream(monkeypatch, [*chunks, text if isinstance(failure, RuntimeError) else failure])
    with pytest.raises(type(failure)) as caught:
        provider.call("fixture", "", [], on_text=callback)
    assert caught.value.usage["prompt_tokens"] == 5
    assert caught.value.usage["completion_tokens"] == 0 and caught.value.usage["cached_tokens"] == 0
    assert response.closed


@pytest.mark.parametrize("provider", [anthropic, gemini])
@pytest.mark.parametrize("invalid", [True, -1, 1.5, "3", None])
def test_native_invalid_final_usage_preserves_prior_and_other_valid_fields(monkeypatch, provider, invalid):
    if provider is anthropic:
        chunks = [message_start({"input_tokens": 5, "output_tokens": 1}),
                  block_start(0, {"type": "text", "text": "hello"}), block_stop(0),
                  message_delta(usage={"input_tokens": invalid, "output_tokens": 3}), frame({"type": "message_stop"})]
    else:
        chunks = [frame(candidate([{"text": "hello"}], "STOP", usageMetadata={"promptTokenCount": 5, "candidatesTokenCount": 1})),
                  frame({"usageMetadata": {"promptTokenCount": invalid, "candidatesTokenCount": 3}})]
    response, _ = install_stream(monkeypatch, chunks)
    with pytest.raises(ValueError) as caught:
        provider.call("fixture", "", [], on_text=lambda _: None)
    assert caught.value.usage["prompt_tokens"] == 5 and caught.value.usage["completion_tokens"] == 3
    assert "cached_tokens" not in caught.value.usage and response.closed


@pytest.mark.parametrize("chunks", [
    [], [frame(candidate([{"text": "partial"}]))],
    [frame(candidate([{"text": "hello"}], "SAFETY"))],
    [frame(candidate([{"text": "hello"}], "FINISH_REASON_UNSPECIFIED"))],
    [frame(candidate([], "STOP"))],
    [frame(candidate([{"text": "private", "thought": True}], "STOP"))],
    [frame({"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []})],
    [frame(candidate([{"text": "hello"}], "STOP")), b'data: {}\n'],
    [frame(candidate([{"text": "hello"}], "STOP")), frame(candidate(finish="MAX_TOKENS"))],
    [frame(candidate([{"text": "hello"}], "STOP")), frame(candidate([{"text": "later"}]))],
    [frame(candidate([{"text": "hello"}], "STOP")), frame(candidate([{"functionCall": {"name": "calculator"}}]))],
    [frame(candidate([{"functionCall": {"name": "calculator", "args": "partial"}}], "STOP"))],
    [frame(candidate([{"text": "bad", "thought": "true"}], "STOP"))],
    [frame(candidate([{"text": "bad", "thoughtSignature": []}], "STOP"))],
    [frame(candidate([{"functionCall": {"name": "calculator", "id": ""}}], "STOP"))],
    [frame({"candidates": [{"index": False, "content": {"parts": [{"text": "bad"}]}, "finishReason": "STOP"}]})],
    [frame({"candidates": [{"index": 1, "content": {"parts": [{"text": "wrong"}]}, "finishReason": "STOP"}]})],
])
def test_gemini_invalid_or_incomplete_protocol_never_completes(monkeypatch, chunks):
    response, _ = install_stream(monkeypatch, chunks)
    with pytest.raises(ValueError):
        gemini.call("fixture", "", [], on_text=lambda _: None)
    assert response.closed


@pytest.mark.parametrize("kind, message, expected", [
    ("invalid_request_error", "prompt is too long: 130000 tokens", "ContextOverflowError"),
    ("invalid_request_error", "This model does not support tools", "ToolsUnsupportedError"),
    ("authentication_error", "invalid key", 401),
    ("rate_limit_error", "rate limited", 429),
    ("overloaded_error", "overloaded", 529),
])
def test_anthropic_http200_native_errors_use_existing_classification(monkeypatch, kind, message, expected):
    from urllib.error import HTTPError
    from personal_agent.providers import contract
    from personal_agent.providers.contract import ToolDef
    response, _ = install_stream(monkeypatch, [message_start({"input_tokens": 5, "output_tokens": 0}),
        frame({"type": "error", "error": {"type": kind, "message": message}})])
    error_type = getattr(contract, expected) if isinstance(expected, str) else HTTPError
    with pytest.raises(error_type) as caught:
        anthropic.call("fixture", "", [], tools=(ToolDef("calculator", "calculate", {}),), on_text=lambda _: None)
    if isinstance(expected, int):
        assert caught.value.code == expected
        assert anthropic.is_retryable(caught.value) == (expected != 401)
    assert caught.value.usage["prompt_tokens"] == 5 and response.closed


def text_exchange(provider, fragments):
    if provider is anthropic:
        return [message_start(), block_start(0, {"type": "text", "text": ""}),
                *(block_delta(0, "text_delta", text=text) for text in fragments),
                block_stop(0), message_delta(), frame({"type": "message_stop"})]
    return [*(frame(candidate([{"text": text}])) for text in fragments), frame(candidate(finish="STOP"))]


@pytest.mark.parametrize("provider", [anthropic, gemini])
@pytest.mark.parametrize("split", [1, 2, 7])
def test_native_unicode_and_event_boundaries(monkeypatch, provider, split):
    body = b"".join(text_exchange(provider, ["界é"]))
    response, _ = install_stream(monkeypatch, [body[index:index + split] for index in range(0, len(body), split)])
    seen = []
    assistant, usage = provider.call("fixture", "", [], on_text=seen.append)
    assert seen == ["界é"] and assistant.text == "界é" and usage == {} and response.closed


@pytest.mark.parametrize("provider", [anthropic, gemini])
def test_native_limits_close_without_completion(monkeypatch, provider):
    response, _ = install_stream(monkeypatch, [b"data: " + b"a" * http.MAX_EVENT_BYTES])
    with pytest.raises(ValueError, match="256 KiB"):
        provider.call("fixture", "", [], on_text=lambda _: None)
    assert response.closed
    chunks = text_exchange(provider, ["a" * 65536] * 129)
    response, _ = install_stream(monkeypatch, chunks)
    with pytest.raises(ValueError, match="8 MiB"):
        provider.call("fixture", "", [], on_text=lambda _: None)
    assert response.closed


@pytest.mark.parametrize("provider", [anthropic, gemini])
def test_native_repl_flushes_before_completion_and_records_cache_timing(route_env, monkeypatch, provider):
    from personal_agent import call_log
    from personal_agent.routing import router, runtime_config
    from personal_agent.terminal.repl import run_repl

    monkeypatch.setenv("PA_PROVIDER", provider.PROVIDER_LABEL)
    monkeypatch.setenv(runtime_config.API_KEY_ENV_VARS[provider.PROVIDER_LABEL], "fixture-key")
    clock = [10.0]
    monkeypatch.setattr(router.time, "monotonic", lambda: clock[0])

    class Output(StringIO):
        def flush(self):
            self.flushed = self.getvalue()

    output = Output()
    chunks = text_exchange(provider, ["first second"])

    if provider is anthropic:
        chunks[0] = message_start({"input_tokens": 5, "output_tokens": 1, "cache_read_input_tokens": 0})
        chunks[-2] = message_delta(usage={"output_tokens": 3, "cache_creation_input_tokens": 2})
    else:
        chunks[0] = frame(candidate([{"text": "first second"}], usageMetadata={"promptTokenCount": 5,
                         "candidatesTokenCount": 1, "cachedContentTokenCount": 0}))
        chunks.insert(-1, frame({"usageMetadata": {"candidatesTokenCount": 3}}))
    terminal = chunks[-1]

    def final():
        assert "llm> first second" in output.flushed
        clock[0] += 0.25
        return terminal

    chunks[-1] = final
    response, requests = install_stream(monkeypatch, chunks)
    run_repl(runtime_config.load(), input_stream=StringIO("task\n/report\nexit\n"), output_stream=output)
    assert len(requests) == 1 and output.getvalue().count("llm>") == 1
    assert f"llm> first second\n[{provider.PROVIDER_LABEL}]" in output.getvalue()
    rows = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    attempt = next(row for row in rows if row["type"] == "attempt")
    assert attempt["streamed"] and attempt["outcome"] == "ok" and attempt["first_text_latency_ms"] == 0
    assert attempt["latency_ms"] == 250 and attempt["completion_tokens"] == 3 and attempt["cached_tokens"] == 0
    assert attempt["cache_write_tokens"] == (2 if provider is anthropic else None)
    turns = [row for row in rows if row["type"] == "turn_end"]
    assert len(turns) == 1 and turns[0]["messages"][-1]["content"] == "first second"
    assert response.closed


@pytest.mark.parametrize("provider", [anthropic, gemini])
def test_native_split_secret_and_controls_are_safe(route_env, monkeypatch, provider):
    from personal_agent.routing import router, runtime_config
    monkeypatch.setenv("PA_PROVIDER", provider.PROVIDER_LABEL)
    monkeypatch.setenv(runtime_config.API_KEY_ENV_VARS[provider.PROVIDER_LABEL], "fixture-key")
    for split in range(len("fixture-key") + 1):
        seen = []
        response, _ = install_stream(monkeypatch, text_exchange(provider, ["fixture-key"[:split], "fixture-key"[split:], "\x1b[31m界"]))
        result = router.route("task", runtime_config.load(),
                              on_stream=lambda event, text: seen.append(text) if event == "text" else None)
        assert result.ok and "".join(seen) == "[redacted]\\x1b[31m界" and response.closed


@pytest.mark.parametrize("provider", [anthropic, gemini])
def test_native_partial_tool_never_executes_or_enters_completed_state(route_env, monkeypatch, tmp_path, provider):
    from personal_agent.routing import router, runtime_config
    monkeypatch.setenv("PA_PROVIDER", provider.PROVIDER_LABEL)
    monkeypatch.setenv(runtime_config.API_KEY_ENV_VARS[provider.PROVIDER_LABEL], "fixture-key")
    arguments = {"path": "created.txt", "content": "data"}
    chunks = ([message_start(), block_start(0, {"type": "tool_use", "id": "mutate", "name": "write", "input": {}}),
               block_delta(0, "input_json_delta", partial_json=json.dumps(arguments))] if provider is anthropic else
              [frame(candidate([{"functionCall": {"id": "mutate", "name": "write", "args": arguments}}]))])
    response, _ = install_stream(monkeypatch, chunks)
    confirmations = []
    result = router.route("task", runtime_config.load(), on_stream=lambda *_: None,
                          confirm=lambda *args: confirmations.append(args))
    assert not result.ok and confirmations == [] and not (tmp_path / "created.txt").exists()
    assert result.continuation["messages"] == [{"role": "user", "content": "task"}] and response.closed
