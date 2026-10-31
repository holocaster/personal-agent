import json
from collections import deque
from pathlib import Path

import pytest

from personal_agent.providers import http, openai, openrouter


class StreamResponse:
    def __init__(self, chunks):
        self.chunks = deque(chunks)
        self.closed = False

    def read1(self, size):
        assert 0 < size <= 4096
        if not self.chunks:
            return b""
        chunk = self.chunks.popleft()
        if callable(chunk):
            chunk = chunk()
        if isinstance(chunk, BaseException):
            raise chunk
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


def frame(data):
    return ("data: " + (data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)) + "\n\n").encode()


def choice(delta=None, finish=None, **extra):
    return {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}], **extra}


def install_stream(monkeypatch, chunks):
    response = StreamResponse(chunks)
    requests = []

    def open_response(request, timeout):
        requests.append(request)
        return response

    monkeypatch.setattr(http, "urlopen", open_response)
    return response, requests


@pytest.mark.parametrize("provider", [openai, openrouter])
@pytest.mark.parametrize("termination", ["stop", "content_filter"])
def test_provider_text_delivered_before_final_event(monkeypatch, provider, termination):
    visible = []

    def finish():
        assert visible == ["héllo"]
        return frame(choice(finish=termination, usage={"prompt_tokens": 10, "completion_tokens": 2}))

    response, requests = install_stream(monkeypatch, [frame(choice({"content": "héllo"})), finish, frame("[DONE]")])
    assistant, usage = provider.call("fixture-model", "system", [], api_key="fixture-key", on_text=visible.append)
    assert assistant.text == "héllo"
    assert assistant.termination == termination
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 2
    assert response.closed
    payload = json.loads(requests[0].data)
    assert payload["stream"] is True
    if provider is openai:
        assert payload["stream_options"] == {"include_usage": True}
    else:
        assert payload["provider"] == {"sort": "price", "preferred_min_throughput": 85, "require_parameters": True}


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("split", [1, 2, 3, 7, 4096])
def test_sse_boundaries_comments_names_and_multiline(monkeypatch, ending, split):
    body = (": heartbeat" + ending + ending + "event: message" + ending +
            'data: {"choices": [{"index": 0,' + ending +
            'data: "delta": {"content": "界é"}, "finish_reason": null}]}' + ending + ending +
            frame(choice(finish="stop")).decode().replace("\n", ending) +
            frame("[DONE]").decode().replace("\n", ending)).encode()
    response, _ = install_stream(monkeypatch, [body[i:i + split] for i in range(0, len(body), split)])
    seen = []
    assistant, usage = openai.call("fixture", "", [], on_text=seen.append)
    assert seen == ["界é"]
    assert assistant.text == "界é"
    assert usage == {}
    assert response.closed


@pytest.mark.parametrize("tail", [b'data: {}', b'data: {}\n', b'\xff', b'\xe2\x82', frame({})])
def test_pending_or_invalid_data_after_done_fails_and_closes(monkeypatch, tail):
    response, _ = install_stream(monkeypatch, [frame(choice(finish="stop")), frame("[DONE]"), tail])
    with pytest.raises(ValueError):
        openai.call("fixture", "", [], on_text=lambda _: None)
    assert response.closed


@pytest.mark.parametrize("chunks", [
    [], [frame(choice({"content": "partial"}))], [frame("[DONE]")],
    [frame(choice(finish="stop"))], [frame(choice(finish="unsupported")), frame("[DONE]")],
    [frame(choice(finish="content_filter"))],
    [frame(choice({"tool_calls": [{"index": 0, "id": "call", "function": {
        "name": "calculator", "arguments": '{"expression":"1+1"}'}}]}, finish="content_filter")), frame("[DONE]")],
    [frame(choice(finish="stop")), frame(choice(finish="length")), frame("[DONE]")],
    [frame(choice(finish="stop")), frame(choice({"content": "later"})), frame("[DONE]")],
    [frame({"choices": [{"delta": {"content": "bad"}}]}), frame("[DONE]")],
    [frame(choice({"content": 12})), frame("[DONE]")],
    [b'data: invalid\n\n'], [frame([])], [frame({"choices": {}})],
    [frame(choice({"tool_calls": [{"index": 999999999, "function": {"name": "calculator"}}]}))],
])
def test_invalid_protocol_never_completes(monkeypatch, chunks):
    response, _ = install_stream(monkeypatch, chunks)
    with pytest.raises(ValueError):
        openai.call("fixture", "", [], on_text=lambda _: None)
    assert response.closed


@pytest.mark.parametrize("provider", [openai, openrouter])
def test_interleaved_tool_fragments_and_hidden_metadata(monkeypatch, provider):
    response, _ = install_stream(monkeypatch, [
        frame(choice({"role": "assistant", "reasoning": "private", "refusal": "hidden", "tool_calls": [
            {"index": 1, "id": "c", "type": "function", "function": {"name": "current_", "arguments": "{"}},
            {"index": 0, "id": "a", "function": {"name": "cal", "arguments": '{"expression":'}}]})),
        frame(choice({"content": "working", "tool_calls": [
            {"index": 0, "id": "b", "function": {"name": "culator", "arguments": '"1+1"}'}},
            {"index": 1, "id": "d", "function": {"name": "time", "arguments": "}"}}]})),
        frame(choice(finish="tool_calls")), frame("[DONE]")])
    seen = []
    assistant, _ = provider.call("fixture", "", [], on_text=seen.append)
    assert seen == ["working"]
    assert [(call.id, call.name, call.arguments) for call in assistant.tool_calls] == [
        ("ab", "calculator", {"expression": "1+1"}), ("cd", "current_time", {})]
    assert response.closed


def test_openrouter_repeated_finish_and_openai_empty_accounting(monkeypatch):
    for provider in (openrouter, openai):
        final = choice({"content": ""}, finish="stop") if provider is openrouter else {"choices": []}
        final["usage"] = {"prompt_tokens": 4, "completion_tokens": 2, "cost": 0,
                          "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 1}}
        install_stream(monkeypatch, [frame(choice({"content": "hi"})), frame(choice(finish="stop")), frame(final), frame("[DONE]")])
        assistant, usage = provider.call("fixture", "", [], on_text=lambda _: None)
        assert assistant.text == "hi"
        assert usage["prompt_tokens"] == 4
        assert usage["cached_tokens"] == 0
        assert usage["cache_write_tokens"] == 1
        if provider is openrouter:
            assert usage["cost"] == 0


@pytest.mark.parametrize("invalid", [True, -1, 0.5, "1", None])
def test_bad_final_usage_retains_prior_and_other_valid_fields(monkeypatch, invalid):
    response, _ = install_stream(monkeypatch, [
        frame(choice({"content": "hi"}, usage={"prompt_tokens": 4, "completion_tokens": 1, "cost": 0.2})),
        frame(choice(finish="stop")),
        frame({"choices": [], "usage": {"prompt_tokens": invalid, "completion_tokens": 2}}), frame("[DONE]")])
    with pytest.raises(ValueError) as caught:
        openrouter.call("fixture", "", [], on_text=lambda _: None)
    assert caught.value.usage["prompt_tokens"] == 4
    assert caught.value.usage["completion_tokens"] == 2
    assert caught.value.usage["cost"] == 0.2
    assert response.closed


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), TimeoutError("read failed"), RuntimeError("callback failed")])
def test_failure_retains_usage_and_closes(monkeypatch, failure):
    chunks = [frame(choice(usage={"prompt_tokens": 5, "completion_tokens": 1})), failure]
    callback = lambda _: None
    if isinstance(failure, RuntimeError):
        chunks[-1] = frame(choice({"content": "hi"}))
        def callback(_):
            raise failure
    response, _ = install_stream(monkeypatch, chunks)
    with pytest.raises(type(failure)) as caught:
        openai.call("fixture", "", [], on_text=callback)
    assert caught.value.usage["prompt_tokens"] == 5
    assert response.closed


def test_http200_error_is_classified_and_retains_usage(monkeypatch):
    from personal_agent.providers.contract import ContextOverflowError
    response, _ = install_stream(monkeypatch, [frame(choice(usage={"prompt_tokens": 7})),
        frame({"error": {"code": 400, "type": "context_length_exceeded", "message": "too much input"}})])
    with pytest.raises(ContextOverflowError) as caught:
        openrouter.call("fixture", "", [], on_text=lambda _: None)
    assert caught.value.usage["prompt_tokens"] == 7
    assert response.closed


def test_event_and_assembled_bounds(monkeypatch):
    response, _ = install_stream(monkeypatch, [b"data: " + b"a" * http.MAX_EVENT_BYTES])
    with pytest.raises(ValueError, match="256 KiB"):
        openai.call("fixture", "", [], on_text=lambda _: None)
    assert response.closed
    chunk = frame(choice({"content": "a" * 65536}))
    response, _ = install_stream(monkeypatch, [chunk] * 129)
    with pytest.raises(ValueError, match="8 MiB"):
        openai.call("fixture", "", [], on_text=lambda _: None)
    assert response.closed


def attempt_records():
    from personal_agent import call_log
    return [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()
            if json.loads(line).get("type") == "attempt"]


def test_router_masks_split_keys_sanitizes_and_measures_delivery(route_env, monkeypatch):
    from personal_agent.routing import router, runtime_config
    clock = [10.0]
    monkeypatch.setattr(router.time, "monotonic", lambda: clock[0])
    notices = []

    def deliver(event, text):
        notices.append((event, text))
        if event == "text":
            clock[0] += 0.025

    install_stream(monkeypatch, [frame(choice({"content": "test-"})), frame(choice({"content": "key"})),
        frame(choice({"content": "\x1b[31m界"})), frame(choice(finish="stop")), frame("[DONE]")])
    result = router.route("task", runtime_config.load(), on_stream=deliver)
    assert result.ok
    assert result.answer == "[redacted]\x1b[31m界"
    assert notices == [("start", None), ("text", "[redacted]"), ("text", "\\x1b[31m界"), ("end", None)]
    record = attempt_records()[0]
    assert record["streamed"] is True
    assert record["first_text_latency_ms"] == 25
    assert record["latency_ms"] == 50


def test_visible_partial_failure_stops_retry_and_preserves_usage(route_env, monkeypatch):
    from personal_agent.routing import router, runtime_config
    response, requests = install_stream(monkeypatch, [frame(choice({"content": "partial"}, usage={"prompt_tokens": 4})), TimeoutError()])
    notices = []
    result = router.route("task", runtime_config.load(), on_stream=lambda event, text: notices.append((event, text)))
    assert not result.ok
    assert "Incomplete response" in result.error
    assert len(requests) == 1
    assert result.continuation["messages"] == [{"role": "user", "content": "task"}]
    assert attempt_records()[0]["prompt_tokens"] == 4
    assert attempt_records()[0]["first_text_latency_ms"] is not None
    assert notices[-1] == ("end", None)
    assert response.closed


def test_repl_flushes_before_completion_and_prints_once(route_env, monkeypatch):
    from io import StringIO
    from personal_agent import call_log
    from personal_agent.routing import runtime_config
    from personal_agent.terminal.repl import run_repl

    class FlushedOutput(StringIO):
        def flush(self):
            self.flushed = self.getvalue()

    output = FlushedOutput()

    def final():
        assert "llm> firs" in output.flushed
        assert "[openrouter]" not in output.getvalue()
        return frame(choice({"content": " second"}, finish="stop"))

    response, _ = install_stream(monkeypatch, [frame(choice({"content": "first"})), final, frame("[DONE]")])
    run_repl(runtime_config.load(), input_stream=StringIO("task\nexit\n"), output_stream=output)
    assert output.getvalue().count("llm>") == 1
    assert "llm> first second\n[openrouter]" in output.getvalue()
    records = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    turns = [record for record in records if record.get("type") == "turn_end"]
    assert len(turns) == 1
    assert turns[0]["messages"][-1]["content"] == "first second"
    assert response.closed


def test_repl_renders_streamed_markdown_before_completion(route_env, monkeypatch):
    from io import StringIO
    from personal_agent.routing import runtime_config
    from personal_agent.terminal import repl

    output = StringIO()
    monkeypatch.setattr(repl, "color_enabled", lambda *_: True)

    def finish():
        assert "\033[1mbold\033[0m" in output.getvalue()
        assert "**bold**" not in output.getvalue()
        return frame(choice({"content": "`inline`"}, finish="stop"))

    install_stream(monkeypatch, [frame(choice({"content": "**bo"})),
                                frame(choice({"content": "ld**\n\n"})), finish, frame("[DONE]")])
    repl.run_repl(runtime_config.load(), input_stream=StringIO("task\nexit\n"), output_stream=output)
    assert "`inline`" not in output.getvalue() and "inline" in output.getvalue()
    assert output.getvalue().count("llm>") == 1


@pytest.mark.parametrize("provider", [openai, openrouter])
def test_filtered_completion_drains_accounting_and_completes_turn(route_env, monkeypatch, provider):
    from io import StringIO
    from personal_agent import call_log
    from personal_agent.routing import runtime_config
    from personal_agent.terminal.repl import run_repl

    monkeypatch.setenv("PA_PROVIDER", provider.PROVIDER_LABEL)
    monkeypatch.setenv(provider.PROVIDER_LABEL.upper() + "_API_KEY", "fixture-key")
    final = choice(finish="content_filter") if provider is openrouter else {"choices": []}
    final["usage"] = {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.2,
                      "prompt_tokens_details": {"cached_tokens": 4}}
    response, requests = install_stream(monkeypatch, [frame(choice({"content": "safe text"})),
        frame(choice(finish="content_filter")), frame(final), frame("[DONE]")])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=["task", "/exit"], output_stream=output)

    record, = attempt_records()
    assert record["outcome"] == "ok"
    assert record["streamed"] is True
    assert record["prompt_tokens"] == 10
    assert record["completion_tokens"] == 2
    assert record["cached_tokens"] == 4
    if provider is openrouter:
        assert record["cost"] == 0.2
    records = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    turn, = [record for record in records if record.get("type") == "turn_end"]
    assert turn["status"] == "ok"
    assert turn["messages"][-1]["content"] == "safe text"
    assert output.getvalue().count("llm>") == 1
    assert "Error:" not in output.getvalue()
    assert len(requests) == 1
    assert requests[0].full_url == provider.API_URL
    assert response.closed
    assert not response.chunks


@pytest.mark.parametrize("key", ["test-key", "test-key-long", "overlap-key", "old\x1bkey"])
def test_every_secret_split_and_overlapping_prefix_is_masked(route_env, monkeypatch, key):
    from personal_agent.routing import router, runtime_config
    secrets = ("test-key-long", "overlap-key", "lap-key", "old\x1bkey")
    for split in range(len(key) + 1):
        visible = []
        install_stream(monkeypatch, [frame(choice({"content": key[:split]})), frame(choice({"content": key[split:]})),
                                   frame(choice(finish="stop")), frame("[DONE]")])
        result = router.route("task", runtime_config.load(), protected_api_keys=secrets,
                              on_stream=lambda event, text: visible.append(text) if event == "text" else None)
        assert result.ok
        assert "".join(visible) == "[redacted]"
        assert "\x1b" not in "".join(visible)


def test_failed_prefix_discarded_and_retry_filter_starts_fresh(route_env, monkeypatch):
    from personal_agent.routing import router, runtime_config
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    responses = deque([StreamResponse([frame(choice({"content": "test-"})), TimeoutError()]),
        StreamResponse([frame(choice({"content": "key"})), frame(choice(finish="stop")), frame("[DONE]")])])
    all_responses = list(responses)
    monkeypatch.setattr(http, "urlopen", lambda *args, **kwargs: responses.popleft())
    visible = []
    result = router.route("task", runtime_config.load(),
                          on_stream=lambda event, text: visible.append((event, text)))
    assert result.ok
    assert result.answer == "key"
    assert visible == [("start", None), ("end", None), ("start", None), ("text", "key"), ("end", None)]
    records = attempt_records()
    assert [record["retry_kind"] for record in records] == ["initial", "transient"]
    assert records[0]["first_text_latency_ms"] is None
    assert all(response.closed for response in all_responses)


def test_success_flushes_unfinished_prefix_but_cancel_discards_it(route_env, monkeypatch):
    from personal_agent.routing import router, runtime_config
    for end in ([frame(choice(finish="stop")), frame("[DONE]")], [KeyboardInterrupt()]):
        visible = []
        response, _ = install_stream(monkeypatch, [frame(choice({"content": "test-"})), *end])
        if isinstance(end[0], KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                router.route("task", runtime_config.load(),
                             on_stream=lambda event, text: visible.append(text) if event == "text" else None)
            assert visible == []
        else:
            result = router.route("task", runtime_config.load(),
                                  on_stream=lambda event, text: visible.append(text) if event == "text" else None)
            assert result.ok
            assert visible == ["test-"]
        assert response.closed


def test_stream_cancel_retains_zero_latency_usage_and_incomplete_flag(route_env, monkeypatch):
    from personal_agent.routing import router, runtime_config
    monkeypatch.setattr(router.time, "monotonic", lambda: 1)
    response, _ = install_stream(monkeypatch, [frame(choice({"content": "hello"}, usage={"prompt_tokens": 3})), KeyboardInterrupt()])
    events = []
    with pytest.raises(KeyboardInterrupt) as caught:
        router.route("task", runtime_config.load(), on_stream=lambda event, text: events.append(event))
    assert caught.value.incomplete_response is True
    assert events == ["start", "text", "end"]
    record = attempt_records()[0]
    assert record["first_text_latency_ms"] == 0
    assert record["prompt_tokens"] == 3
    assert record["outcome"] == "interrupted"
    assert response.closed


def test_controls_are_safe_but_do_not_count_as_first_text(route_env, monkeypatch):
    from personal_agent.routing import router, runtime_config
    install_stream(monkeypatch, [frame(choice({"content": "\x1b"})), frame(choice({"content": "\x9b\r\x00"})),
                               frame(choice(finish="stop")), frame("[DONE]")])
    texts = []
    result = router.route("task", runtime_config.load(),
                          on_stream=lambda event, text: texts.append(text) if event == "text" else None)
    assert result.ok
    assert "".join(texts) == "\\x1b\\x9b\\x0d\\x00"
    assert attempt_records()[0]["first_text_latency_ms"] is None


def test_partial_tool_never_executes_or_enters_continuation(route_env, monkeypatch, tmp_path):
    from personal_agent.routing import router, runtime_config
    response, _ = install_stream(monkeypatch, [frame(choice({"tool_calls": [{"index": 0, "id": "mutate", "function": {
        "name": "write", "arguments": '{"path":"created.txt","content":"data"}'}}]}))])
    confirmations = []
    result = router.route("task", runtime_config.load(), on_stream=lambda *_: None,
                          confirm=lambda *args: confirmations.append(args))
    assert not result.ok
    assert confirmations == []
    assert not (tmp_path / "created.txt").exists()
    assert result.continuation["messages"] == [{"role": "user", "content": "task"}]
    assert response.closed


def test_later_exchange_retry_keeps_completed_tools_and_text(route_env, monkeypatch):
    from personal_agent.routing import router, runtime_config
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    responses = deque([
        StreamResponse([frame(choice({"content": "checking", "tool_calls": [{"index": 0, "id": "once", "function": {
            "name": "calculator", "arguments": '{"expression":"2+2"}'}}]}, finish="tool_calls")), frame("[DONE]")]),
        StreamResponse([TimeoutError()]),
        StreamResponse([frame(choice({"content": "four"}, finish="stop")), frame("[DONE]")])])
    monkeypatch.setattr(http, "urlopen", lambda *args, **kwargs: responses.popleft())
    texts, tools = [], []
    result = router.route("task", runtime_config.load(),
                          on_stream=lambda event, text: texts.append(text) if event == "text" else None,
                          on_tool_result=tools.append)
    assert result.ok
    assert texts == ["checking", "four"]
    assert len(tools) == 1
    assert [record["retry_kind"] for record in attempt_records()] == ["initial", "initial", "transient"]
    assert [message["role"] for message in result.messages] == ["user", "assistant", "tool_result", "assistant"]


def test_bad_accounting_after_text_has_no_completed_turn(route_env, monkeypatch):
    from io import StringIO
    from personal_agent import call_log
    from personal_agent.routing import runtime_config
    from personal_agent.terminal.repl import run_repl
    response, requests = install_stream(monkeypatch, [frame(choice({"content": "provisional"}, usage={"prompt_tokens": 3})),
        frame(choice(finish="stop")), frame({"choices": [], "usage": {"completion_tokens": -1}})])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=["task", "/exit"], output_stream=output)
    assert "llm> provisional\nError: Incomplete response" in output.getvalue()
    assert len(requests) == 1
    assert attempt_records()[0]["prompt_tokens"] == 3
    turns = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()
             if json.loads(line).get("type") == "turn_end"]
    assert turns[0]["status"] == "error"
    assert "messages" not in turns[0]
    assert response.closed


def test_stream_output_failure_closes_without_retry_and_retains_accounting(route_env, monkeypatch):
    from personal_agent.routing import router, runtime_config
    response, requests = install_stream(monkeypatch, [frame(choice({"content": "hi"}, usage={"prompt_tokens": 4, "cost": .2}))])
    events = []

    def deliver(event, text):
        events.append(event)
        if event == "text":
            raise TimeoutError("output failed")

    result = router.route("task", runtime_config.load(), on_stream=deliver)
    assert not result.ok
    assert "Incomplete response" in result.error
    assert "/retry" in result.error
    assert len(requests) == 1
    assert events == ["start", "text", "end"]
    assert attempt_records()[0]["prompt_tokens"] == 4
    assert attempt_records()[0]["cost"] == .2
    assert attempt_records()[0]["first_text_latency_ms"] is None
    assert response.closed


def test_first_write_ctrl_c_marks_incomplete_without_first_text_timing(route_env, monkeypatch):
    import threading
    from io import StringIO
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from personal_agent import call_log
    from personal_agent.routing import runtime_config
    from personal_agent.terminal.input_box import InputBox
    from personal_agent.terminal.repl import COMMANDS, run_repl

    response, requests = install_stream(monkeypatch, [
        frame(choice({"content": "partial"}, usage={"prompt_tokens": 3, "cost": .2})),
        frame(choice(finish="stop")), frame("[DONE]"),
    ])
    with create_pipe_input() as pipe:
        class InterruptOutput(StringIO):
            def write(self, text):
                written = super().write(text)
                if text == "partial":
                    self.flush()
                    pipe.send_text("\x03/exit\r")
                    threading.Event().wait(2)
                    pytest.fail("busy Ctrl+C was not delivered during the first write")
                return written

        output = InterruptOutput()
        box = InputBox(COMMANDS, input=pipe, output=DummyOutput())
        pipe.send_text("task\r")
        run_repl(runtime_config.load(), output_stream=output, input_box=box)

    assert len(requests) == 1
    assert response.closed
    assert not any(thread.name == "agent-mode-input" for thread in threading.enumerate())
    record, = attempt_records()
    assert record["outcome"] == "interrupted"
    assert record["prompt_tokens"] == 3
    assert record["cost"] == .2
    assert record["first_text_latency_ms"] is None
    turns = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()
             if json.loads(line).get("type") == "turn_end"]
    turn, = turns
    assert turn["status"] == "interrupted"
    assert "messages" not in turn
    assert turn["continuation"]["messages"] == [{"role": "user", "content": "task"}]
    assert "llm> partial\nIncomplete response: interrupted. Use /retry to continue.\n" in output.getvalue()


def test_streamed_keys_do_not_leak_into_output_or_detailed_audit(route_env, monkeypatch):
    from io import StringIO
    from personal_agent import call_log
    from personal_agent.routing import runtime_config
    from personal_agent.terminal.repl import run_repl
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    response, _ = install_stream(monkeypatch, [frame(choice({"content": "test-"})), frame(choice({"content": "key"})),
        RuntimeError("failure test-key")])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=["task", "/exit"], output_stream=output)
    assert "[redacted]" in output.getvalue()
    for text in (output.getvalue(), Path(call_log.session_log_path()).read_text(), Path(call_log.detail_path()).read_text()):
        assert "test-key" not in text
    assert response.closed
