import json

import pytest

from personal_agent import chatgpt_auth
from personal_agent.providers import chatgpt
from personal_agent.providers.http import urlopen as production_open
from pathlib import Path
from personal_agent.providers.contract import ToolDef
from tests.test_streaming import frame, install_stream
from tests.test_chatgpt_auth import oauth


def event(kind, **fields):
    return frame({"type": kind, **fields})


def message(text="hello", identifier="message-1", **fields):
    return {"id": identifier, "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}], **fields}


def completed(output=None, usage=None, **fields):
    return event("response.completed", response={"id": "response-1", "status": "completed",
                 "output": output or [], **({"usage": usage} if usage is not None else {}), **fields})


@pytest.mark.parametrize("complete", [False, True])
def test_keepalive_preserves_output_and_still_requires_completion(monkeypatch, complete):
    chunks = [event("response.created", response={"id": "response-1"}), event("keepalive"),
              event("response.output_item.done", output_index=0, item=message()), event("keepalive")]
    if complete:
        chunks.append(completed([message()]))
    install_stream(monkeypatch, chunks)
    if complete:
        assistant, _ = chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
        assert assistant.text == "hello"
    else:
        with pytest.raises(ValueError, match="stream ended before response.completed"):
            chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")


def test_stream_text_and_empty_terminal_output_use_public_request(monkeypatch):
    seen = []
    item = message("héllo", phase="final_answer")

    def finish():
        assert seen == ["hé", "llo"]
        return event("response.output_item.done", output_index=0, item=item)

    response, requests = install_stream(monkeypatch, [
        event("response.created", response={"id": "response-1", "status": "in_progress"}),
        event("response.output_item.added", output_index=0,
              item={**item, "status": "in_progress", "content": []}),
        event("response.content_part.added", output_index=0, item_id=item["id"], content_index=0,
              part={"type": "output_text", "text": "", "annotations": []}),
        event("response.output_text.delta", output_index=0, item_id=item["id"], content_index=0, delta="hé"),
        event("response.output_text.delta", output_index=0, item_id=item["id"], content_index=0, delta="llo"),
        finish, completed(usage={"input_tokens": 12, "output_tokens": 4,
                                "input_tokens_details": {"cached_tokens": 3},
                                "output_tokens_details": {"reasoning_tokens": 2}})])
    assistant, usage = chatgpt.call("exact-1", "instructions", [{"role": "user", "content": "task"}],
                                  tools=(ToolDef("calculator", "calculate", {"type": "object"}),),
                                  api_key="synthetic-bearer", on_text=seen.append)
    assert assistant.text == "héllo" and assistant.termination == "completed"
    assert assistant.replay["items"][-1] == item
    assert usage == {"prompt_tokens": 12, "completion_tokens": 4, "cached_tokens": 3,
                     "reasoning_tokens": 2, "cost": None, "cost_estimated": False}
    request = requests[0]
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert request.get_header("Authorization") == "Bearer synthetic-bearer"
    payload = json.loads(request.data)
    assert set(payload) == {"model", "instructions", "input", "tools", "store", "stream"}
    assert payload["store"] is False and payload["stream"] is True
    assert payload["instructions"] == "instructions" and payload["input"] == [{"role": "user", "content": "task"}]
    assert payload["tools"][0]["type"] == "namespace" and payload["tools"][0]["name"] == "personal_agent"
    assert response.closed


def function(identifier="tool-1", name="calculator", arguments='{"expression":"2+2"}', namespace="personal_agent"):
    return {"type": "function_call", "id": "item-" + identifier, "call_id": identifier,
            "namespace": namespace, "name": name, "arguments": arguments, "status": "completed"}


@pytest.mark.parametrize("streamed", [False, True])
def test_metadata_event_preserves_text_without_rendering_or_replaying_metadata(monkeypatch, streamed):
    response, _ = install_stream(monkeypatch, [
        event("response.created", response={"id": "response-1", "status": "in_progress"}),
        event("response.output_item.added", output_index=0, item={**message(""), "content": []}),
        event("response.output_text.delta", output_index=0, item_id="message-1", content_index=0, delta="hello"),
        event("response.metadata", response_id="response-1", sequence_number=4,
              metadata={"moderation": {"text": "private metadata"}}),
        event("response.output_item.done", output_index=0, item=message()), completed([message()])])
    seen = []
    assistant, _ = chatgpt.call("exact-1", "", [], api_key="synthetic-bearer",
                              on_text=seen.append if streamed else None)
    assert assistant.text == "hello" and assistant.replay["items"] == [message()]
    assert "".join(seen) == ("hello" if streamed else "") and response.closed


@pytest.mark.parametrize("fields", [
    {"response_id": "other", "metadata": {}}, {"metadata": {}},
    {"response_id": "response-1", "metadata": None}, {"response_id": "response-1", "metadata": []},
])
def test_invalid_metadata_is_rejected(monkeypatch, fields):
    install_stream(monkeypatch, [event("response.created", response={"id": "response-1"}),
                                event("response.metadata", **fields), completed([message()])])
    with pytest.raises(ValueError, match="Responses (metadata|identity)"):
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")


def test_unknown_event_diagnostic_is_bounded_and_redacted(monkeypatch):
    response, _ = install_stream(monkeypatch, [event("response.future.synthetic-bearer\n" + "x" * 200)])
    response.headers = {"x-request-id": "request-synthetic-bearer\n"}
    with pytest.raises(ValueError) as caught:
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
    assert "synthetic-bearer" not in str(caught.value) and "[redacted]" in str(caught.value)
    assert "\n" not in str(caught.value) and len(str(caught.value)) <= len("Unsupported Responses event: ") + 160
    assert caught.value.request_id == "request-[redacted]\\n"


def test_router_executes_namespaced_tools_and_replays_reasoning(oauth, monkeypatch):
    from personal_agent import call_log
    from personal_agent.routing import router, runtime_config
    from tests.test_streaming import StreamResponse
    from collections import deque

    auth, state = oauth
    binding = auth.connect()
    auth.acknowledge(binding)
    auth.activate(binding, "exact-1", lambda: None)
    monkeypatch.setattr(chatgpt_auth, "ChatGPTAuth", lambda: auth)
    config = runtime_config.admit_chatgpt(runtime_config.RuntimeConfig("chatgpt", "exact-1", {}))
    reasoning = {"type": "reasoning", "id": "reason-1", "summary": [], "encrypted_content": "opaque-private"}
    calls = [function(), function("tool-2", arguments='{"expression":"3+3"}')]
    metadata = event("response.metadata", response_id="response-1", metadata={"moderation": {}})
    responses = deque([StreamResponse([metadata, completed([reasoning, *calls])]),
                       StreamResponse([metadata, completed([message("done")])])])
    requests = []

    def open_response(request, timeout):
        requests.append(request)
        return responses.popleft()

    monkeypatch.setattr(chatgpt.http, "urlopen", open_response)
    results, visible = [], []
    result = router.route("calculate", config, on_tool_result=results.append,
                          on_stream=lambda event, text: visible.append(text) if event == "text" else None)
    assert result.ok and result.answer == "done" and [r.content for r in results] == [{"result": 4}, {"result": 6}]
    assert "".join(visible) == "done" and len(requests) == 2
    followup = json.loads(requests[-1].data)
    assert followup["input"][1:4] == [reasoning, *calls]
    assert followup["input"][4:] == [{"type": "function_call_output", "call_id": "tool-1", "output": '{"result": 4}' },
                                        {"type": "function_call_output", "call_id": "tool-2", "output": '{"result": 6}' }]
    entries = [json.loads(row) for row in Path(call_log.session_log_path()).read_text().splitlines()]
    attempts = [entry for entry in entries if entry["type"] == "attempt"]
    assert len(attempts) == 2
    assert all(entry["access_method"] == "chatgpt_plan" and entry["registration_ref"] == binding.registration
               and entry["cost"] is None and not entry["cost_estimated"] for entry in attempts)


@pytest.mark.parametrize("namespace,name,arguments", [
    ("other", "calculator", '{}'), ("personal_agent", "other", '{}'),
    ("personal_agent", "calculator", '{"broken":'), ("personal_agent", "calculator", '[]'),
    ("personal_agent", "calculator", '{"expression":"2+2","expression":"3+3"}'),
])
def test_invalid_tool_calls_never_succeed(monkeypatch, namespace, name, arguments):
    install_stream(monkeypatch, [completed([function(namespace=namespace, name=name, arguments=arguments)])])
    with pytest.raises(ValueError):
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer", tools=(ToolDef("calculator", "", {}),))


@pytest.mark.parametrize("chunks", [
    [], [event("response.output_item.added", output_index=0, item=message(""))],
    [event("response.output_item.done", output_index=0, item=message()), event("response.incomplete", response={"id":"response-1"})],
    [completed([message()]), completed([message()])],
    [completed([message()]), b'data: {}\n'],
    [event("response.metadata", response_id="response-1", metadata={})],
    [event("response.metadata", response_id="other", metadata={}), completed([message()])],
    [completed([message()]), event("response.metadata", response_id="response-1", metadata={})],
    [event("response.output_item.done", output_index=0, item=message()), completed([message("different")])],
    [event("response.created", response={"id": "response-1"}),
     event("response.output_item.done", output_index=0, item=message()), completed([], id="other")],
    [event("response.output_item.added", output_index=0, item=message("")),
     event("response.output_text.delta", output_index=0, item_id="wrong", content_index=0, delta="bad")],
    [completed([message()]), b'\xc3'],
    [b'data: ' + b'a' * (256 * 1024)],
])
def test_incoherent_stream_never_completes(monkeypatch, chunks):
    response, _ = install_stream(monkeypatch, chunks)
    with pytest.raises((ValueError, UnicodeError)):
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
    assert response.closed


@pytest.mark.parametrize("code,retryable", [
    ("subscription_sharing_usage_limit_exceeded", False),
    ("subscription_sharing_usage_unavailable", True),
    ("subscription_sharing_user_unavailable", True),
    ("subscription_sharing_user_not_eligible", False),
    ("subscription_sharing_unsupported_capability", False),
    ("subscription_sharing_route_not_supported", False),
    ("chatpass_v2_scope_not_authorized", False),
    ("context_length_exceeded", False),
])
def test_http200_errors_keep_usage_and_classification(monkeypatch, code, retryable):
    from personal_agent.providers.contract import ContextOverflowError
    error = {"code": code, "param": "tools", "message": "failed"}
    install_stream(monkeypatch, [event("error", **error), event("response.failed", response={
        "id": "response-1", "error": error, "usage": {"input_tokens": 17, "output_tokens": 3}})])
    kind = ContextOverflowError if code == "context_length_exceeded" else chatgpt.ChatGPTError
    with pytest.raises(kind) as caught:
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
    assert caught.value.usage["prompt_tokens"] == 17 and caught.value.usage["completion_tokens"] == 3
    assert caught.value.code == code and caught.value.param == "tools" and caught.value.status == 200
    assert chatgpt.is_retryable(caught.value) is retryable
    if code == "subscription_sharing_usage_limit_exceeded":
        assert "Cota atingida" in str(caught.value) and chatgpt_auth.USAGE_URL in str(caught.value)


def test_invalid_optional_usage_is_independent_and_never_priced(monkeypatch):
    from personal_agent import cost
    monkeypatch.setattr(cost, "estimate", lambda *a, **kw: pytest.fail("plan usage must never be priced"))
    install_stream(monkeypatch, [completed([message()], usage={"input_tokens": 12, "output_tokens": 5,
        "input_tokens_details": {"cached_tokens": True}, "output_tokens_details": {"reasoning_tokens": 2}})])
    assistant, usage = chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
    assert assistant.text == "hello" and usage["prompt_tokens"] == 12 and usage["completion_tokens"] == 5
    assert usage["reasoning_tokens"] == 2 and usage["invalid_usage"] == ["cached_tokens"]
    assert "cached_tokens" not in usage and usage["cost"] is None and usage["cost_estimated"] is False


@pytest.mark.parametrize("kind", ["response.output_text.done", "response.content_part.done"])
def test_contradictory_text_done_snapshot_is_rejected(monkeypatch, kind):
    fields = {"text": "different"} if kind.endswith("text.done") else {"part": {"type": "output_text", "text": "different"}}
    install_stream(monkeypatch, [event("response.output_item.added", output_index=0,
                                      item={**message(""), "status": "in_progress", "content": []}),
        event("response.output_text.delta", output_index=0, item_id="message-1", content_index=0, delta="hello"),
        event(kind, output_index=0, item_id="message-1", content_index=0, **fields), completed([message()])])
    with pytest.raises(ValueError, match="Contradictory"):
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")


@pytest.mark.parametrize("snapshot_kind", ["item", "completion"])
@pytest.mark.parametrize("closure", [None, "response.output_text.done", "response.content_part.done"])
def test_consistent_text_snapshots_preserve_answer_once(monkeypatch, snapshot_kind, closure):
    chunks = [event("response.output_item.added", output_index=0, item={**message(""), "content": []}),
              event("response.output_text.delta", output_index=0, item_id="message-1", content_index=0, delta="hel")]
    if closure is not None:
        chunks.append(event("response.output_text.delta", output_index=0, item_id="message-1", content_index=0, delta="lo"))
        fields = {"text": "hello"} if closure.endswith("text.done") else {"part": message()["content"][0]}
        chunks.append(event(closure, output_index=0, item_id="message-1", content_index=0, **fields))
    if snapshot_kind == "item":
        chunks.append(event("response.output_item.done", output_index=0, item=message()))
    chunks.append(completed([message()]))
    response, _ = install_stream(monkeypatch, chunks)
    seen = []
    assistant, _ = chatgpt.call("exact-1", "", [], api_key="synthetic-bearer", on_text=seen.append)
    assert assistant.text == "hello" and "".join(seen) == "hello" and response.closed


@pytest.mark.parametrize("origin", ["item", "delta", "done"])
@pytest.mark.parametrize("first_type", ["output_text", "refusal"])
@pytest.mark.parametrize("boundary", ["delta", "done", "part.added", "part.done", "item", "completion"])
def test_content_type_cannot_change_between_events(monkeypatch, origin, first_type, boundary):
    first = {"type": first_type, "text" if first_type == "output_text" else "refusal": ""}
    last_type = "refusal" if first_type == "output_text" else "output_text"
    last = {"type": last_type, "text" if last_type == "output_text" else "refusal": ""}
    initial = {**message(""), "content": [first]}
    changed = {**message(""), "content": [last]}
    chunks = [event("response.output_item.added", output_index=0,
                    item=initial if origin == "item" else {**initial, "content": []})]
    if origin != "item":
        field = "delta" if origin == "delta" else "text" if first_type == "output_text" else "refusal"
        chunks.append(event(f"response.{first_type}.{origin}", output_index=0, item_id="message-1",
                            content_index=0, **{field: ""}))
    if boundary in {"delta", "done"}:
        field = "delta" if boundary == "delta" else "text" if last_type == "output_text" else "refusal"
        chunks.append(event(f"response.{last_type}.{boundary}", output_index=0, item_id="message-1",
                            content_index=0, **{field: ""}))
    elif boundary.startswith("part."):
        chunks.append(event(f"response.content_{boundary}", output_index=0, item_id="message-1",
                            content_index=0, part=last))
    elif boundary == "item":
        chunks.append(event("response.output_item.done", output_index=0, item=changed))
    final = initial if boundary in {"delta", "done"} else changed
    chunks.append(completed([final, message("answer", "message-2")]))
    response, _ = install_stream(monkeypatch, chunks)
    with pytest.raises(ValueError, match="Contradictory Responses content type"):
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
    assert response.closed


@pytest.mark.parametrize("origin", ["item", "delta", "done", "part.added", "part.done"])
@pytest.mark.parametrize("part_type,expected", [("output_text", "helloanswer"), ("refusal", "answer")])
def test_consistent_content_type_preserves_text_and_hides_refusal(monkeypatch, origin, part_type, expected):
    part = {"type": part_type, "text" if part_type == "output_text" else "refusal": "hello"}
    item = {**message(), "content": [part]}
    chunks = [event("response.output_item.added", output_index=0,
                    item=item if origin == "item" else {**item, "content": []})]
    if origin != "item":
        fields = {"part": part} if origin.startswith("part.") else {
            "delta" if origin == "delta" else "text" if part_type == "output_text" else "refusal":
            "hel" if origin == "delta" else "hello"}
        kind = f"response.content_{origin}" if origin.startswith("part.") else f"response.{part_type}.{origin}"
        chunks.append(event(kind, output_index=0, item_id="message-1", content_index=0, **fields))
    chunks.append(completed([item, message("answer", "message-2")]))
    response, _ = install_stream(monkeypatch, chunks)
    seen = []
    assistant, _ = chatgpt.call("exact-1", "", [], api_key="synthetic-bearer", on_text=seen.append)
    assert assistant.text == "".join(seen) == expected and response.closed


@pytest.mark.parametrize("status,detail,retryable", [(401, "auth denied", False), (403, {"policy": "denied"}, False),
                                                     (503, ["unavailable"], True), (429, "rate limit", True)])
def test_http_admission_detail_is_diagnostic_not_machine_code(monkeypatch, status, detail, retryable):
    from io import BytesIO
    from urllib.error import HTTPError
    error = HTTPError(chatgpt.API_URL, status, "failed", {"x-request-id": "request-safe"},
                      BytesIO(json.dumps({"detail": detail}).encode()))
    monkeypatch.setattr(chatgpt.http, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(error))
    with pytest.raises(chatgpt.ChatGPTError) as caught:
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
    assert caught.value.code is None and caught.value.param is None
    assert caught.value.status == status and caught.value.request_id == "request-safe"
    assert chatgpt.is_retryable(caught.value) is retryable


@pytest.fixture
def connected(oauth, monkeypatch):
    from personal_agent.routing import runtime_config
    auth, state = oauth
    binding = auth.connect()
    auth.acknowledge(binding)
    auth.activate(binding, "exact-1", lambda: None)
    monkeypatch.setattr(chatgpt_auth, "ChatGPTAuth", lambda: auth)
    return auth, state, runtime_config.admit_chatgpt(runtime_config.RuntimeConfig("chatgpt", "exact-1", {}))


def rows():
    from personal_agent import call_log
    return [json.loads(row) for row in Path(call_log.session_log_path()).read_text().splitlines()]


@pytest.mark.parametrize("visible", [False, True])
def test_tls_record_failure_retries_only_before_visible_text_and_keeps_tool_results(connected, monkeypatch, visible):
    import ssl
    from collections import deque
    from personal_agent.routing import router
    from tests.test_streaming import StreamResponse

    _, _, config = connected
    error = ssl.SSLError(ssl.SSL_ERROR_SSL, "TLS record failed")
    error.reason = "SSLV3_ALERT_BAD_RECORD_MAC"
    partial = [event("response.output_item.added", output_index=0, item={**message(""), "content": []}),
               event("response.output_text.delta", output_index=0, item_id="message-1", content_index=0, delta="partial")]
    responses = deque([StreamResponse([completed([function()])]),
                       StreamResponse([*(partial if visible else []), error]), StreamResponse([completed([message("4")])])])
    requests, results, seen = [], [], []

    def respond(request, timeout):
        requests.append(request)
        return responses.popleft()

    monkeypatch.setattr(chatgpt.http, "urlopen", respond)
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    result = router.route("calculate", config, on_tool_result=results.append,
                          on_stream=lambda kind, text: seen.append(text) if kind == "text" else None)
    assert len(results) == 1 and results[0].content == {"result": 4}
    assert result.ok is not visible and len(requests) == (2 if visible else 3)
    if not visible:
        assert result.answer == "4" and json.loads(requests[1].data) == json.loads(requests[2].data)


@pytest.mark.parametrize("header", ["x-request-id", "x-oai-request-id"])
def test_unknown_event_is_identified_in_failed_attempt(connected, monkeypatch, header):
    from personal_agent.routing import router

    _, _, config = connected
    response, _ = install_stream(monkeypatch, [
        event("response.created", response={"id": "response-1"}), event("response.future_event")])
    response.headers = {header: "request-protocol-safe"}
    result = router.route("task", config)
    assert not result.ok
    attempt, = [row for row in rows() if row["type"] == "attempt"]
    assert "Unsupported Responses event: response.future_event" in attempt["error"]
    assert attempt["http_status"] == 200 and attempt["request_id"] == "request-protocol-safe"


def exhaustion(usage=None):
    error = {"code": "subscription_sharing_usage_limit_exceeded", "message": "plan limit", "param": None}
    return [event("error", **error), event("response.failed", response={"id": "response-1", "error": error,
             **({"usage": usage} if usage is not None else {})})]


def test_plan_exhaustion_after_tool_batch_keeps_work_and_charges_one_attempt(connected, monkeypatch):
    from collections import deque
    from personal_agent.routing import router
    from tests.test_streaming import StreamResponse
    _, _, config = connected
    responses = deque([StreamResponse([completed([function()])]), StreamResponse(exhaustion({"input_tokens": 9, "output_tokens": 1}))])
    requests = []
    def transport(request, timeout):
        requests.append(request)
        return responses.popleft()
    monkeypatch.setattr(chatgpt.http, "urlopen", transport)
    monkeypatch.setattr(router, "_sleep", lambda _: pytest.fail("exhaustion must not wait"))
    tools = []
    result = router.route("calculate", config, on_tool_result=tools.append)
    assert not result.ok and "Cota atingida" in result.error
    assert len(requests) == 2 and len(tools) == 1
    assert result.continuation["messages"][-1]["content"] == {"result": 4}
    attempts = [row for row in rows() if row["type"] == "attempt"]
    assert len(attempts) == 2 and attempts[-1]["prompt_tokens"] == 9 and attempts[-1]["completion_tokens"] == 1
    assert all(attempt["streamed"] for attempt in attempts)
    assert attempts[-1]["error_code"] == "subscription_sharing_usage_limit_exceeded"
    assert attempts[-1]["cost"] is None and not attempts[-1]["cost_estimated"]


def test_plan_exhaustion_in_soft_compression_blocks_pending_request(connected, monkeypatch):
    from personal_agent import token_estimate
    from personal_agent.routing import router
    _, _, config = connected
    def estimate(model, prepared):
        tokens = 103000 if "tools" in prepared else max(1, len(json.dumps(prepared)) // 4)
        return token_estimate.TokenEstimate(tokens, "synthetic", True)
    monkeypatch.setattr(token_estimate, "estimate", estimate)
    response, requests = install_stream(monkeypatch, exhaustion({"input_tokens": 7}))
    history = [({"role": "user", "content": "older context " * 100}, {"role": "assistant", "content": "answer"})] * 3
    committed = []
    result = router.route("pending", config, history_turns=history, on_compression=committed.append)
    assert not result.ok and "Cota atingida" in result.error and not committed
    assert len(requests) == 1 and response.closed
    assert [row["purpose"] for row in rows() if row["type"] == "attempt"] == ["compression"]


@pytest.mark.parametrize("change", ["disconnect", "replace", "settings"])
def test_task_binding_and_capacity_stay_pinned_for_tool_followup(connected, monkeypatch, change):
    from personal_agent.routing import router, runtime_config
    auth, state, config = connected
    requests = []
    from tests.test_streaming import StreamResponse
    def transport(request, timeout):
        requests.append(request)
        return StreamResponse([completed([function()] if len(requests) == 1 else [message("done")])])
    monkeypatch.setattr(chatgpt.http, "urlopen", transport)
    def change_account(_):
        if change == "disconnect":
            auth.disconnect()
        elif change == "replace":
            state["claims"] = {"sub": "account-2"}
            new = auth.connect(different=True)
            auth.acknowledge(new)
            auth.activate(new, "exact-1", lambda: None)
        else:
            monkeypatch.setenv("PA_PROVIDER", "openai")
            monkeypatch.setenv("PA_MODEL", "other")
            monkeypatch.setenv("PA_CONTEXT_BUDGET_TOKENS", "1")
    result = router.route("calculate", config, on_tool_result=change_account)
    assert len(requests) == (2 if change == "settings" else 1)
    assert result.ok is (change == "settings")
    assert config.capacity_snapshot["input_ceiling"] == 102000
    if result.ok:
        assert all(json.loads(request.data)["model"] == "exact-1" for request in requests)
    else:
        assert result.continuation["messages"][-1]["content"] == {"result": 4}


def test_refreshed_split_secret_is_safe_in_input_stream_tools_and_audit(connected, monkeypatch):
    from personal_agent import call_log
    from personal_agent.routing import router
    auth, state, config = connected
    secret = "new-access-fixture"
    with auth._locked() as directory:
        record = auth._read(directory)
        record["session"].update(expires_at=0, earliest_refresh_at=0)
        auth._save(directory, record)
    original = auth.transport
    def refresh(url, **kwargs):
        data = original(url, **kwargs)
        if url == chatgpt_auth.TOKEN:
            data["access_token"] = secret
        return data
    auth.transport = refresh
    call_log.start_coverage(True)
    seen = []
    response, requests = install_stream(monkeypatch, [
        event("response.output_item.added", output_index=0, item={**message(""), "content": [], "status": "in_progress"}),
        event("response.output_text.delta", output_index=0, item_id="message-1", content_index=0, delta=secret[:5]),
        event("response.output_text.delta", output_index=0, item_id="message-1", content_index=0, delta=secret[5:]),
        completed([message(secret)])])
    result = router.route("echo " + secret, config,
                          on_stream=lambda kind, text: seen.append(text) if kind == "text" else None)
    call_log.end_coverage(True)
    assert result.ok and result.answer == "[redacted]" and "".join(seen) == "[redacted]"
    assert requests[0].get_header("Authorization") == "Bearer " + secret
    assert secret not in requests[0].data.decode()
    assert secret not in Path(call_log.session_log_path()).read_text()
    assert secret not in Path(call_log.detail_path()).read_text()
    assert response.closed


def test_oauth_inference_does_not_follow_redirect_or_disclose_bearer(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from personal_agent.providers import http
    captured = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", "/sink")
            self.end_headers()
        def do_GET(self):
            captured.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(http, "urlopen", production_open)
        monkeypatch.setattr(chatgpt, "API_URL", f"http://127.0.0.1:{server.server_port}/responses")
        with pytest.raises(chatgpt.ChatGPTError) as caught:
            chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
        assert caught.value.status == 302 and captured == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_capacity_uses_exact_public_metadata_then_manual_and_freezes(connected, monkeypatch):
    from dataclasses import replace
    from personal_agent import context_budget, model_catalog
    from personal_agent.routing import runtime_config
    auth, state, config = connected
    exact = model_catalog.Offering("openai", "exact-1", "Exact", None, 200000, 180000, None, None)
    catalog = model_catalog.Catalog("synthetic", {"openai": {"exact-1": exact}})
    monkeypatch.setattr(context_budget, "model_info", lambda provider, model: {
        "max_input_tokens": 150000, "max_output_tokens": 12000})
    config = replace(config, context_budget_tokens=160000, capacity_snapshot=None,
                     capacity_overrides=({"provider": "chatgpt", "model": "exact-1", "total_tokens": 210000},))
    admitted = runtime_config.admit_chatgpt(config, catalog)
    limits = context_budget.resolve(admitted, "chatgpt", "exact-1")
    assert (limits.total_tokens, limits.total_source) == (210000, "manual")
    assert (limits.input_tokens, limits.input_source) == (180000, "Models.dev")
    assert (limits.output_tokens, limits.output_source) == (12000, "LiteLLM")
    assert limits.effective_total == 160000 and limits.output_reserve == 12000 and limits.input_ceiling == 138000
    monkeypatch.setattr(context_budget, "model_info", lambda *_: pytest.fail("task capacity must be frozen"))
    assert context_budget.resolve(admitted.snapshot(), "chatgpt", "exact-1") == limits


def test_missing_capacity_never_borrows_similar_model(connected, monkeypatch):
    from dataclasses import replace
    from personal_agent import context_budget, model_catalog
    from personal_agent.routing import runtime_config
    _, _, config = connected
    lookups = []
    def info(provider, model):
        lookups.append((provider, model))
        return {}
    monkeypatch.setattr(context_budget, "model_info", info)
    similar = model_catalog.Offering("openai", "exact-1-api", "Other", None, 1000000, 900000, 90000, None)
    catalog = model_catalog.Catalog("synthetic", {"openai": {similar.id: similar}})
    admitted = runtime_config.admit_chatgpt(replace(config, capacity_snapshot=None), catalog)
    limits = context_budget.resolve(admitted, "chatgpt", "exact-1")
    assert lookups == [("chatgpt", "exact-1")]
    assert limits.total_source == "unknown; assumed" and limits.total_tokens == 128000
    assert limits.output_reserve == 16000 and limits.input_ceiling == 102000
    assert limits.input_source is None and limits.output_source is None


def test_repl_streams_account_task_and_shows_plan_safe_usage(connected, monkeypatch):
    from io import StringIO
    from personal_agent.terminal.repl import run_repl, render_footer
    _, _, config = connected
    seen = []
    class Output(StringIO):
        def flush(self):
            seen.append(self.getvalue())
    output = Output()
    def terminal():
        assert any("hello" in content for content in seen)
        return completed(usage={"input_tokens": 12, "output_tokens": 3})
    response, requests = install_stream(monkeypatch, [
        event("response.output_item.added", output_index=0, item={**message(""), "content": []}),
        event("response.output_text.delta", output_index=0, item_id="message-1", content_index=0, delta="hello "),
        event("response.output_item.done", output_index=0, item=message("hello ")), terminal])
    run_repl(config, input_stream=StringIO("task\n/usage\n/exit\n"), output_stream=output)
    assert "llm> hello" in output.getvalue() and len(requests) == 1 and response.closed
    assert "planning estimate" in output.getvalue() and "no guaranteed remote output cap" in output.getvalue()
    assert "unknown (ChatGPT plan)" in output.getvalue() and "$0" not in output.getvalue()
    footer = render_footer("chatgpt", "exact-1", 0)
    assert "Assinatura ChatGPT" in footer and "/usage" in footer and "$" not in footer
    attempt = next(row for row in rows() if row["type"] == "attempt")
    assert attempt["streamed"] and type(attempt["first_text_latency_ms"]) is int


@pytest.mark.parametrize("terminal", ["response.failed", "response.incomplete", "eof"])
def test_rejected_partial_stream_never_executes_tool_or_completes_turn(connected, monkeypatch, terminal):
    from personal_agent.routing import router
    _, _, config = connected
    chunks = [event("response.output_item.added", output_index=0, item={**message(""), "content": []}),
              event("response.output_text.delta", output_index=0, item_id="message-1", content_index=0, delta="partial"),
              event("response.metadata", response_id="response-1", metadata={"moderation": {}}),
              event("response.output_item.done", output_index=1, item=function())]
    if terminal != "eof":
        chunks.append(event(terminal, response={"id": "response-1", "status": terminal.split('.')[1],
                      "error": {"code": "permission_denied", "message": "denied"},
                      "usage": {"input_tokens": 9, "output_tokens": 2}}))
    response, requests = install_stream(monkeypatch, chunks)
    results, seen = [], []
    result = router.route("calculate", config, on_tool_result=results.append,
                          on_stream=lambda event, text: seen.append(text) if event == "text" else None)
    assert not result.ok and result.answer is None and not results and len(requests) == 1
    assert "partial".startswith("".join(seen)) and response.closed
    assert result.continuation["messages"] == [{"role": "user", "content": "calculate"}]
    attempts = [row for row in rows() if row["type"] == "attempt"]
    assert len(attempts) == 1 and attempts[0]["answer"] is None and not attempts[0]["ok"]
    if terminal != "eof":
        assert attempts[0]["prompt_tokens"] == 9 and attempts[0]["completion_tokens"] == 2


@pytest.mark.parametrize("snapshot_kind", ["item", "completion"])
@pytest.mark.parametrize("text_event,changed_part", [
    ("response.output_text.done", {"type": "output_text", "text": "hello changed after done", "annotations": []}),
    ("response.output_text.done", {"type": "refusal", "refusal": "changed after done"}),
    ("response.output_text.delta", {"type": "refusal", "refusal": "changed after delta"}),
])
def test_changed_text_never_executes_tool_or_completes_turn(connected, monkeypatch, snapshot_kind, text_event, changed_part):
    from personal_agent.routing import router
    from tests.test_streaming import StreamResponse
    _, _, config = connected
    changed = {**message(), "content": [changed_part]}
    chunks = [event("response.output_item.added", output_index=0, item={**message(""), "content": []}),
              event(text_event, output_index=0, item_id="message-1", content_index=0,
                    **{"delta" if text_event.endswith("delta") else "text": "hello"})]
    if snapshot_kind == "item":
        chunks.append(event("response.output_item.done", output_index=0, item=changed))
    chunks.append(completed([changed, function()]))
    responses = iter([StreamResponse(chunks), StreamResponse([completed([message("done")])])])
    requests = []

    def open_response(request, timeout):
        requests.append(request)
        return next(responses)

    monkeypatch.setattr(chatgpt.http, "urlopen", open_response)
    results = []
    result = router.route("calculate", config, on_tool_result=results.append)
    assert not result.ok and result.answer is None and not results and len(requests) == 1
    assert result.continuation["messages"] == [{"role": "user", "content": "calculate"}]
    attempts = [row for row in rows() if row["type"] == "attempt"]
    assert len(attempts) == 1 and attempts[0]["answer"] is None and not attempts[0]["ok"]


@pytest.mark.parametrize("snapshot_kind", ["item", "completion"])
@pytest.mark.parametrize("final_text", ["different text", "original text", "original text extended"])
def test_initial_item_text_must_be_kept_by_snapshots_before_tools(connected, monkeypatch, snapshot_kind, final_text):
    from personal_agent.routing import router
    from tests.test_streaming import StreamResponse
    _, _, config = connected
    final = message(final_text)
    chunks = [event("response.output_item.added", output_index=0, item=message("original text", status="in_progress"))]
    if snapshot_kind == "item":
        chunks.append(event("response.output_item.done", output_index=0, item=final))
    chunks.append(completed([final, function()]))
    responses = iter([StreamResponse(chunks), StreamResponse([completed([message("finished")])])])
    requests = []

    def open_response(request, timeout):
        requests.append(request)
        return next(responses)

    monkeypatch.setattr(chatgpt.http, "urlopen", open_response)
    results = []
    result = router.route("calculate", config, on_tool_result=results.append)
    if final_text.startswith("original text"):
        assert result.ok and result.answer == "finished" and len(results) == 1 and len(requests) == 2
    else:
        assert not result.ok and result.answer is None and not results and len(requests) == 1


def test_initial_item_text_plus_delta_completes_answer(connected, monkeypatch):
    from personal_agent.routing import router
    from tests.test_streaming import StreamResponse
    _, _, config = connected
    chunks = [event("response.output_item.added", output_index=0, item=message("original ", status="in_progress")),
              event("response.output_text.delta", output_index=0, item_id="message-1", content_index=0, delta="text"),
              completed([message("original text")])]
    monkeypatch.setattr(chatgpt.http, "urlopen", lambda *args, **kwargs: StreamResponse(chunks))
    result = router.route("answer", config)
    assert result.ok and result.answer == "original text"


@pytest.mark.parametrize("split", [1, 2, 7])
def test_utf8_sse_boundaries_work_without_callback_or_content_type(monkeypatch, split):
    body = completed([message("界é")])
    response, _ = install_stream(monkeypatch, [body[index:index + split] for index in range(0, len(body), split)])
    assistant, usage = chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
    assert assistant.text == "界é" and response.closed and usage["cost"] is None


def test_aggregate_stream_bound_rejects_before_completion(monkeypatch):
    chunks = [event("response.output_item.added", output_index=0, item={**message(""), "content": []})]
    chunks += [event("response.output_text.delta", output_index=0, item_id="message-1", content_index=0, delta="a" * 65536)] * 129
    response, _ = install_stream(monkeypatch, chunks)
    with pytest.raises(ValueError, match="8 MiB"):
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
    assert response.closed


@pytest.mark.parametrize("failure", [TimeoutError("transport failed"), KeyboardInterrupt()])
def test_interrupted_stream_keeps_observed_usage(monkeypatch, failure):
    response, _ = install_stream(monkeypatch, [event("response.created", response={"id": "response-1",
        "usage": {"input_tokens": 9, "output_tokens": 0, "input_tokens_details": {"cached_tokens": 3}}}), failure])
    with pytest.raises(type(failure)) as caught:
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
    assert caught.value.usage["prompt_tokens"] == 9 and caught.value.usage["completion_tokens"] == 0
    assert caught.value.usage["cached_tokens"] == 3 and response.closed


def test_sequential_tool_results_remain_correlated_and_tool_ceiling_applies(connected, monkeypatch):
    from collections import deque
    from dataclasses import replace
    from personal_agent.routing import router
    from tests.test_streaming import StreamResponse
    _, _, config = connected
    requests = []
    responses = deque([StreamResponse([completed([function()])]),
                       StreamResponse([completed([function("tool-2", arguments='{"expression":"3+3"}')])]),
                       StreamResponse([completed([message("done")])])])
    def transport(request, timeout):
        requests.append(request)
        return responses.popleft()
    monkeypatch.setattr(chatgpt.http, "urlopen", transport)
    results = []
    result = router.route("calculate", config, on_tool_result=results.append)
    assert result.ok and [tool.id for tool in results] == ["tool-1", "tool-2"] and len(requests) == 3
    inputs = json.loads(requests[-1].data)["input"]
    assert [item["call_id"] for item in inputs if item.get("type") == "function_call_output"] == ["tool-1", "tool-2"]
    responses.extend([StreamResponse([completed([function("tool-3")])]), StreamResponse([completed([function("tool-4")])])])
    result = router.route("calculate again", replace(config, max_tool_rounds=1), on_tool_result=results.append)
    assert not result.ok and "1-round limit" in result.error and len(requests) == 5 and len(results) == 3


def test_oversized_tool_batch_never_executes(connected, monkeypatch):
    from personal_agent.routing import router
    _, _, config = connected
    install_stream(monkeypatch, [completed([function(str(index)) for index in range(17)])])
    results = []
    result = router.route("calculate", config, on_tool_result=results.append)
    assert not result.ok and not results and result.continuation["messages"] == [{"role": "user", "content": "calculate"}]


@pytest.mark.parametrize("after_tools", [False, True])
def test_positive_overflow_uses_one_strictly_shrinking_same_route_recovery(connected, monkeypatch, after_tools):
    from collections import deque
    from personal_agent import token_estimate
    from personal_agent.routing import router
    from tests.test_streaming import StreamResponse
    _, _, config = connected
    def estimate(model, prepared):
        if "tools" in prepared:
            return token_estimate.TokenEstimate(90000 if "older-context" in json.dumps(prepared) else 10000, "synthetic", True)
        return token_estimate.TokenEstimate(max(1, len(json.dumps(prepared)) // 4), "synthetic", True)
    monkeypatch.setattr(token_estimate, "estimate", estimate)
    responses = deque([StreamResponse([event("response.failed", response={"id": "response-1", "error": {
        "code": "context_length_exceeded", "message": "too large"}})]),
        StreamResponse([completed([message("short summary")])]), StreamResponse([completed([message("done")])])])
    if after_tools:
        responses.appendleft(StreamResponse([completed([function()])]))
    requests = []
    def transport(request, timeout):
        requests.append(request)
        return responses.popleft()
    monkeypatch.setattr(chatgpt.http, "urlopen", transport)
    old = ({"role": "user", "content": "older-context " * 100}, {"role": "assistant", "content": "older answer"})
    recent = ({"role": "user", "content": "recent"}, {"role": "assistant", "content": "recent answer"})
    summaries = []
    result = router.route("pending", config, history_turns=[old, recent, recent], on_compression=summaries.append)
    assert result.ok and result.answer == "done" and summaries == ["short summary"] and len(requests) == 3 + after_tools
    assert all(request.full_url == "https://api.openai.com/v1/responses" and json.loads(request.data)["model"] == "exact-1"
               for request in requests)
    assert [row["retry_kind"] for row in rows() if row["type"] == "attempt"] == (["initial"] if after_tools else []) + ["initial", "initial", "context_overflow"]
    if after_tools:
        final_items = json.loads(requests[-1].data)["input"]
        assert "older-context" not in json.dumps(final_items)
        assert sum(item.get("type") == "function_call_output" for item in final_items) == 1


def test_http200_failure_keeps_request_id_from_transport(monkeypatch):
    response, _ = install_stream(monkeypatch, exhaustion({"input_tokens": 4}))
    response.headers = {"x-request-id": "request-200-safe"}
    with pytest.raises(chatgpt.ChatGPTError) as caught:
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
    assert caught.value.status == 200 and caught.value.request_id == "request-200-safe"


def test_argument_deltas_and_duplicate_snapshots_preserve_raw_call_once(monkeypatch):
    call = function()
    response, _ = install_stream(monkeypatch, [
        event("response.output_item.added", output_index=0, item={**call, "status": "in_progress", "arguments": ""}),
        event("response.function_call_arguments.delta", output_index=0, item_id=call["id"], delta=call["arguments"][:7]),
        event("response.function_call_arguments.delta", output_index=0, item_id=call["id"], delta=call["arguments"][7:]),
        event("response.function_call_arguments.done", output_index=0, item_id=call["id"], arguments=call["arguments"]),
        event("response.output_item.done", output_index=0, item=call),
        event("response.output_item.done", output_index=0, item=call), completed([call])])
    assistant, _ = chatgpt.call("exact-1", "", [], api_key="synthetic-bearer", tools=(ToolDef("calculator", "", {}),))
    assert len(assistant.tool_calls) == 1 and assistant.tool_calls[0].arguments_raw == call["arguments"]
    assert assistant.tool_calls[0].id == call["call_id"] and assistant.tool_calls[0].arguments == {"expression": "2+2"}
    assert response.closed


def test_tool_and_error_echoes_protect_current_and_retired_credentials(connected, monkeypatch, tmp_path):
    from collections import deque
    from personal_agent import call_log
    from personal_agent.routing import router
    from personal_agent.tools.workspace import configure_workspace
    from tests.test_streaming import StreamResponse
    auth, state, config = connected
    secret = "access-fixture"
    retired = "refresh-fixture"
    configure_workspace(tmp_path)
    (tmp_path / "fixture.txt").write_text(secret + " " + retired)
    call = function(name="read_file", arguments='{"path":"fixture.txt"}')
    responses = deque([StreamResponse([completed([call])]), StreamResponse([event("response.failed", response={
        "id": "response-1", "error": {"code": "permission_denied", "message": secret + " " + retired}})])])
    requests = []
    def transport(request, timeout):
        requests.append(request)
        return responses.popleft()
    monkeypatch.setattr(chatgpt.http, "urlopen", transport)
    call_log.start_coverage(True)
    results = []
    result = router.route("read fixture", config, on_tool_result=results.append)
    call_log.end_coverage(True)
    assert not result.ok and results and len(requests) == 2
    for text in (json.dumps(results[0].content), result.error, requests[1].data.decode(),
                 Path(call_log.session_log_path()).read_text(), Path(call_log.detail_path()).read_text()):
        assert secret not in text and retired not in text


def test_new_admission_rechecks_model_choices_without_browser_or_fallback(connected, monkeypatch):
    from personal_agent.routing import runtime_config
    auth, state, config = connected
    auth.browser = lambda *_: pytest.fail("admission must not launch browser")
    original = auth.transport
    auth.transport = lambda url, **kwargs: {"models": []} if url == chatgpt_auth.MODELS else original(url, **kwargs)
    with pytest.raises(chatgpt_auth.AuthError, match="no longer available"):
        runtime_config.admit_chatgpt(config)
    assert config.provider == "chatgpt" and config.model == "exact-1"


def test_protocol_failure_preserves_valid_usage_from_rejected_envelope(monkeypatch):
    install_stream(monkeypatch, [completed([message()], usage={"input_tokens": 11, "output_tokens": 3}, id=None)])
    with pytest.raises(ValueError) as caught:
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
    assert caught.value.usage["prompt_tokens"] == 11 and caught.value.usage["completion_tokens"] == 3


def test_completed_envelope_with_error_never_succeeds(monkeypatch):
    install_stream(monkeypatch, [completed([message()], error={"code": "permission_denied", "message": "denied"})])
    with pytest.raises(chatgpt.ChatGPTError) as caught:
        chatgpt.call("exact-1", "", [], api_key="synthetic-bearer")
    assert caught.value.code == "permission_denied" and not chatgpt.is_retryable(caught.value)


@pytest.mark.parametrize("contradictory", [False, True])
def test_reasoning_deltas_are_hidden_and_must_match_item_snapshot(monkeypatch, contradictory):
    reasoning = {"type": "reasoning", "id": "reasoning-1", "summary": [
        {"type": "summary_text", "text": "different" if contradictory else "private reasoning"}],
        "encrypted_content": "private-encrypted-state"}
    response, _ = install_stream(monkeypatch, [
        event("response.output_item.added", output_index=0, item={**reasoning, "summary": []}),
        event("response.reasoning_summary_text.delta", output_index=0, item_id="reasoning-1", summary_index=0, delta="private "),
        event("response.reasoning_summary_text.delta", output_index=0, item_id="reasoning-1", summary_index=0, delta="reasoning"),
        event("response.output_item.done", output_index=0, item=reasoning), completed([reasoning, message()])])
    seen = []
    if contradictory:
        with pytest.raises(ValueError, match="reasoning"):
            chatgpt.call("exact-1", "", [], api_key="synthetic-bearer", on_text=seen.append)
    else:
        assistant, _ = chatgpt.call("exact-1", "", [], api_key="synthetic-bearer", on_text=seen.append)
        assert assistant.replay["items"][0] == reasoning and assistant.text == "hello"
    assert "private" not in "".join(seen) and response.closed
