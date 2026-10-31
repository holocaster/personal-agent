import json
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from personal_agent import call_log, cost
from personal_agent.routing import runtime_config
from personal_agent.routing import router
from personal_agent.providers.contract import AssistantMessage, ToolCall, ToolResult
from personal_agent.tools import registry as tools_registry, shell as shell_tool, workspace
from tests.test_runtime_config import _ScriptedInputBox
from personal_agent.terminal.repl import run_repl


def lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def test_coverage_and_mixed_resume(route_env, install_fake_urlopen, monkeypatch):
    config = runtime_config.load()
    install_fake_urlopen(["first", "second", "third"])
    run_repl(config, input_stream=StringIO("hello\nexit\n"), output_stream=StringIO())
    session_id = call_log.current_session_id()
    path = call_log.session_log_path()
    audit_path = Path(path).with_suffix(".audit.jsonl")
    assert not audit_path.exists()
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    resumed = (session_id, *call_log.load_conversation(session_id))
    run_repl(config, resumed=resumed, input_stream=StringIO("again\nexit\n"), output_stream=StringIO())
    assert audit_path.stat().st_mode & 0o777 == 0o600
    audit = lines(audit_path)
    main = lines(path)
    coverage = [row for row in main if row["type"].startswith("audit_coverage_")]
    assert [(row["type"], row["enabled"]) for row in coverage] == [
        ("audit_coverage_start", False), ("audit_coverage_end", False),
        ("audit_coverage_start", True), ("audit_coverage_end", True),
    ]
    assert [row["type"] for row in audit] == ["run_start", "attempt_start", "attempt_end", "run_end"]
    attempt = [row for row in main if row["type"] == "attempt"][-1]
    assert audit[1]["attempt_id"] == audit[2]["attempt_id"] == attempt["attempt_id"]
    assert audit[1]["messages"][-1] == {"role": "user", "content": "again"}
    assert len(call_log.load_conversation(session_id)[0]) == 2
    monkeypatch.setenv("PA_DETAILED_AUDIT", "0")
    resumed = (session_id, *call_log.load_conversation(session_id))
    run_repl(config, resumed=resumed, input_stream=StringIO("third\nexit\n"), output_stream=StringIO())
    assert lines(audit_path) == audit
    assert len(call_log.load_conversation(session_id)[0]) == 3


def test_invalid_flag_before_run(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "yes")
    with pytest.raises(ValueError, match="PA_DETAILED_AUDIT"):
        run_repl(runtime_config.load(), input_stream=StringIO("/clear\n"), output_stream=StringIO())


def test_bad_tail_refused_only_when_enabled(route_env, monkeypatch):
    config = runtime_config.load()
    run_repl(config, input_stream=StringIO("exit\n"), output_stream=StringIO())
    sid = call_log.current_session_id()
    path = Path(call_log.session_log_path()).with_suffix(".audit.jsonl")
    path.write_text('{"type":"incomplete"')
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    with pytest.raises(call_log.AuditError, match="tail"):
        run_repl(config, resumed=(sid, *call_log.load_conversation(sid)), input_stream=StringIO("/clear\n"), output_stream=StringIO())
    monkeypatch.setenv("PA_DETAILED_AUDIT", "0")
    run_repl(config, resumed=(sid, *call_log.load_conversation(sid)), input_stream=StringIO("exit\n"), output_stream=StringIO())


def test_exchanges_match_provider_inputs_across_retry_tools_and_compression(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    seen = []
    outcomes = [ValueError("temporary"), AssistantMessage(None, (ToolCall("c1", "calculator", {"expression": "2+2"}),)),
                AssistantMessage("four"), AssistantMessage("a2"), AssistantMessage("a3"), AssistantMessage("summary")]

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            seen.append((model, system, messages, kwargs))
            answer = outcomes.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer, {}

        def is_retryable(self, exc):
            return isinstance(exc, ValueError)

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    run_repl(runtime_config.load(), input_stream=StringIO("first\nsecond\nthird\n/compress\nexit\n"), output_stream=StringIO())
    audit = lines(call_log.detail_path())
    starts = [row for row in audit if row["type"] == "attempt_start"]
    ends = [row for row in audit if row["type"] == "attempt_end"]
    assert len(starts) == len(ends) == len(seen) == 6
    assert [row["outcome"] for row in ends] == ["error", "ok", "ok", "ok", "ok", "ok"]
    assert [row["attempt_id"] for row in starts] == [row["attempt_id"] for row in ends]
    for row, (model, system, messages, kwargs) in zip(starts, seen):
        assert row["model"] == model
        assert row["system"] == system
        assert row["messages"] == messages
        assert row["replay"] == kwargs["replay"]
        assert row["tools"] == [
            {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
            for tool in (kwargs["tools"] or ())
        ]
    assert starts[-1]["tools"] == []
    assert starts[2]["messages"][-1]["role"] == "tool_result"
    assert len([row for row in audit if row["type"] == "action_start" and row["action"] == "tool"]) == 1
    assert len([row for row in lines(call_log.session_log_path()) if row["type"] == "attempt"]) == 6


def test_retry_exhaustion_and_manual_compression_each_trace_their_actual_exchange(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    seen = []

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            seen.append((model, system, messages, kwargs))
            if len(seen) <= 3:
                raise TimeoutError("temporary")
            if len(seen) == 7:
                return AssistantMessage("summary"), {}
            return AssistantMessage("ok"), {"prompt_tokens": 9 if len(seen) == 6 else 1}

        def is_retryable(self, exc):
            return isinstance(exc, TimeoutError)

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    run_repl(runtime_config.load(), input_stream=StringIO("hi\ntwo\nthree\nfour\n/compress\nexit\n"), output_stream=StringIO())
    starts = [row for row in lines(call_log.detail_path()) if row["type"] == "attempt_start"]
    assert len(starts) == len(seen) == 7
    assert all("tier" not in row and row["provider"] == "openrouter" for row in starts)
    assert starts[6]["tools"] == []
    for start, (model, system, messages, kwargs) in zip(starts, seen):
        assert start["model"] == model
        assert start["system"] == system
        assert start["messages"] == messages
        assert start["replay"] == kwargs["replay"]
    assert len([row for row in lines(call_log.session_log_path()) if row["type"] == "attempt"]) == 7


def test_known_keys_in_dynamic_arguments_and_payload_but_not_schema(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    config = runtime_config.load()
    config.api_keys["openrouter"] = "ok"
    seen = []

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            seen.append(messages)
            if len(seen) == 1:
                return AssistantMessage("ok", (ToolCall("c1", "calculator", {"ok": {"prefix-ok": "ok"}}),),
                                        replay={"nested-ok": "ok"}), {}
            return AssistantMessage("done"), {}

        def is_retryable(self, exc):
            return False

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    run_repl(config, input_stream=StringIO("ok\nexit\n"), output_stream=StringIO())
    main = lines(call_log.session_log_path())
    audit = lines(call_log.detail_path())
    assert "ok" in str(seen[1])
    assert all("prefix-ok" not in json.dumps(row) for row in main + audit if row["type"] != "turn_end")
    assert audit[1]["messages"] == [{"role": "user", "content": "[redacted]"}]
    assert [row for row in audit if row["type"] == "attempt_start"][1]["replay"] == {"nested-[redacted]": "[redacted]"}
    assert [row for row in audit if row["type"] == "attempt_end"][0]["outcome"] == "ok"
    assert [row for row in main if row["type"] == "attempt"][0]["tool_calls"][0]["arguments"] == {
        "[redacted]": {"prefix-[redacted]": "[redacted]"}}


def test_malformed_tool_arguments_redact_raw_text_and_preserve_tool_schema(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    config = runtime_config.load()
    config.api_keys["openrouter"] = "object"
    responses = [AssistantMessage(None, (ToolCall("c1", "calculator", None, '{"object":"object"'),)),
                 AssistantMessage("done")]

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            return responses.pop(0), {}

        def is_retryable(self, exc):
            return False

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    run_repl(config, input_stream=StringIO("first\nexit\n"), output_stream=StringIO())
    audit = lines(call_log.detail_path())
    first = next(row for row in audit if row["type"] == "attempt_start")
    calculator = next(tool for tool in first["tools"] if tool["name"] == "calculator")
    assert calculator["parameters"]["type"] == "object"
    assert calculator["parameters"]["properties"]["expression"]["type"] == "string"
    assert first["messages"] == [{"role": "user", "content": "first"}]
    assert "object" not in json.dumps([row for row in audit if row["type"] in {"attempt_end", "local_outcome"}])
    attempt = next(row for row in lines(call_log.session_log_path()) if row["type"] == "attempt")
    assert attempt["tool_calls"][0]["arguments_raw"] == '{"[redacted]":"[redacted]"'


def test_known_key_equal_to_builtin_tool_name_does_not_hide_offered_definition(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    config = runtime_config.load()
    config.api_keys["openrouter"] = "calculator"
    captured = []

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            captured.append(kwargs["tools"])
            return AssistantMessage("calculator"), {}

        def is_retryable(self, exc):
            return False

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    run_repl(config, input_stream=StringIO("calculator\nexit\n"), output_stream=StringIO())
    start = next(row for row in lines(call_log.detail_path()) if row["type"] == "attempt_start")
    assert [tool["name"] for tool in start["tools"]] == [tool.name for tool in captured[0]]
    assert "calculator" in [tool["name"] for tool in start["tools"]]
    assert start["messages"] == [{"role": "user", "content": "[redacted]"}]
    assert next(row for row in lines(call_log.detail_path()) if row["type"] == "attempt_end")["answer"] == "[redacted]"


def test_tool_result_schema_survives_credential_collision(route_env, monkeypatch, tmp_path):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    config = runtime_config.load()
    config.api_keys["openrouter"] = "exit_code"
    responses = [AssistantMessage(None, (ToolCall("s", "shell", {"command": "exit 3"}),)),
                 AssistantMessage("done")]

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            return responses.pop(0), {}

        def is_retryable(self, exc):
            return False

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    run_repl(config, input_stream=StringIO("/mode auto\nrun\nexit\n"), output_stream=StringIO())
    tool = next(row for row in lines(call_log.session_log_path()) if row["type"] == "tool_execution")
    follow_up = [row for row in lines(call_log.detail_path()) if row["type"] == "attempt_start"][1]
    assert tool["result"]["exit_code"] == 3
    assert follow_up["messages"][-1]["content"]["exit_code"] == 3


def test_tool_result_dynamic_keys_do_not_leak_in_detailed_follow_up(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    config = runtime_config.load()
    config.api_keys["openrouter"] = "secret"
    responses = [AssistantMessage(None, (ToolCall("c1", "shell", {"command": "true"}),)),
                 AssistantMessage("done")]
    seen = []

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            seen.append(messages)
            return responses.pop(0), {}

        def is_retryable(self, exc):
            return False

    def execute(calls, **kwargs):
        return [ToolResult(id="c1", name="shell", content={
            "exit_code": 0, "prefix-secret": {"inner-secret": "secret"}}, is_error=False)]

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    monkeypatch.setattr(tools_registry, "execute_batch", execute)
    run_repl(config, input_stream=StringIO("run\nexit\n"), output_stream=StringIO())
    follow_up = [row for row in lines(call_log.detail_path()) if row["type"] == "attempt_start"][1]
    assert "prefix-secret" in seen[1][-1]["content"]
    assert follow_up["messages"][-1]["content"] == {
        "exit_code": 0, "prefix-[redacted]": {"inner-[redacted]": "[redacted]"}}


def test_nested_tool_result_schema_preserved_but_dynamic_keys_redacted(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    config = runtime_config.load()
    config.api_keys["openrouter"] = "title"
    responses = [AssistantMessage(None, (ToolCall("c1", "websearch", {"query": "safe"}),)),
                 AssistantMessage("done")]

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            return responses.pop(0), {}

        def is_retryable(self, exc):
            return False

    def execute(calls, **kwargs):
        return [ToolResult(id="c1", name="websearch", content={"results": [{
            "title": "public", "url": "https://example.com", "snippet": "ok",
            "prefix-title": {"inner-title": "title"}}]}, is_error=False)]

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    monkeypatch.setattr(tools_registry, "execute_batch", execute)
    run_repl(config, input_stream=StringIO("run\nexit\n"), output_stream=StringIO())
    follow_up = [row for row in lines(call_log.detail_path()) if row["type"] == "attempt_start"][1]
    assert follow_up["messages"][-1]["content"]["results"] == [{
        "title": "public", "url": "https://example.com", "snippet": "ok",
        "prefix-[redacted]": {"inner-[redacted]": "[redacted]"}}]


@pytest.mark.parametrize("calls,error_fragment", [
    ([ToolCall(str(i), "calculator", {"expression": "1+1"}) for i in range(17)], "exceeds"),
    ([ToolCall("same", "calculator", {"expression": "1+1"}),
      ToolCall("same", "calculator", {"expression": "2+2"})], "duplicate"),
    ([ToolCall("", "calculator", {"expression": "1+1"})], "missing an id"),
])
def test_rejected_tool_batches_have_linked_intents_without_execution(
    route_env, monkeypatch, calls, error_fragment
):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    responses = [AssistantMessage(None, tuple(calls))]

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            return responses.pop(0), {}

        def is_retryable(self, exc):
            return False

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    run_repl(runtime_config.load(), input_stream=StringIO("run\nexit\n"), output_stream=StringIO())
    main = lines(call_log.session_log_path())
    audit = lines(call_log.detail_path())
    starts = [row for row in audit if row["type"] == "action_start" and row["action"] == "tool"]
    assert len(starts) == len(calls)
    assert len({row["action_id"] for row in starts}) == len(calls)
    assert not any(row["type"] == "tool_execution" for row in main)
    assert error_fragment in next(row for row in main if row["type"] == "turn_end")["error"]
    for start in starts:
        outcomes = [row for row in main if row.get("action_id") == start["action_id"]]
        assert len(outcomes) == 1
        assert outcomes[0]["action"] == "tool_batch" and outcomes[0]["outcome"] == "error"
        assert not any(row["type"] == "tool_execution" and row.get("action_id") == start["action_id"]
                       for row in main)


def test_rejected_batch_intent_write_failure_prevents_next_action(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    calls = []

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            calls.append(messages)
            return AssistantMessage(None, (ToolCall("same", "calculator", {"expression": "1+1"}),
                                           ToolCall("same", "calculator", {"expression": "2+2"}))), {}

        def is_retryable(self, exc):
            return False

    original = call_log.write_detail

    def fail(kind, **fields):
        if kind == "action_start" and fields.get("action") == "tool":
            raise call_log.AuditError("intent unavailable")
        original(kind, **fields)

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    monkeypatch.setattr(call_log, "write_detail", fail)
    with pytest.raises(call_log.AuditError, match="intent unavailable"):
        run_repl(runtime_config.load(), input_stream=StringIO("run\nnext\n"), output_stream=StringIO())
    assert len(calls) == 1
    assert not any(row["type"] in {"turn_end", "audit_coverage_end", "tool_execution"}
                   for row in lines(call_log.session_log_path()))


def test_round_limit_records_unexecuted_tool_intent(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    monkeypatch.setenv("PA_MAX_TOOL_ROUNDS", "2")
    count = 0

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            nonlocal count
            count += 1
            return AssistantMessage(None, (ToolCall(str(count), "calculator", {"expression": "1+1"}),)), {}

        def is_retryable(self, exc):
            return False

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    run_repl(runtime_config.load(), input_stream=StringIO("run\nexit\n"), output_stream=StringIO())
    main = lines(call_log.session_log_path())
    starts = [row for row in lines(call_log.detail_path()) if row["type"] == "action_start"]
    assert count == 3
    assert len(starts) == count
    assert len([row for row in main if row["type"] == "tool_execution"]) == 2
    assert [row for row in main if row.get("action_id") == starts[-1]["action_id"]][0]["action"] == "tool_batch"


def test_gemini_replay_keeps_model_role_but_redacts_dynamic_argument_keys(route_env, monkeypatch, install_fake_urlopen):
    from tests.fakes import FakeOpenRouterResponse

    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    config = replace(runtime_config.load(), provider="gemini")
    config.api_keys["gemini"] = "model"
    parts = [{"functionCall": {"name": "calculator", "args": {"expression": "2+2", "prefix-model": "model"}}}]
    install_fake_urlopen([FakeOpenRouterResponse({"candidates": [{"content": {"parts": parts}}]}), "done"])

    run_repl(config, input_stream=StringIO("hi\nexit\n"), output_stream=StringIO())

    follow_up = [row for row in lines(call_log.detail_path()) if row["type"] == "attempt_start"][1]
    assert follow_up["replay"] == {
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}, {"role": "model", "parts": [
            {"functionCall": {"name": "calculator", "args": {"expression": "2+2", "prefix-[redacted]": "[redacted]"}}}]}],
        "consumed": 2, "active_start": 0, "active_contents_start": 0}


def test_gemini_replay_preserves_tool_result_schema_and_redacts_dynamic_data(route_env, monkeypatch, install_fake_urlopen):
    from tests.fakes import FakeOpenRouterResponse

    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    config = replace(runtime_config.load(), provider="gemini")
    config.api_keys["gemini"] = "exit_code"
    config.api_keys["openrouter"] = "title"
    parts = [{"functionCall": {"name": "shell", "args": {"command": "true"}}},
             {"functionCall": {"name": "websearch", "args": {"query": "test"}}}]
    results = {
        "shell": {"exit_code": 3, "prefix-exit_code": {"inner-exit_code": "exit_code"}},
        "websearch": {"results": [{"title": "title", "prefix-title": "title"}]}, "calculator": {"result": 4}}
    monkeypatch.setattr(tools_registry, "execute_batch", lambda calls, **kwargs: [
        ToolResult(call.id, call.name, results[call.name], False, call.id_is_generated) for call in calls])
    install_fake_urlopen([FakeOpenRouterResponse({"candidates": [{"content": {"parts": parts}}]}),
                         {"tool_calls": [{"id": "next", "name": "calculator", "arguments": {"expression": "2+2"}}]}, "done"])

    run_repl(config, input_stream=StringIO("hi\nexit\n"), output_stream=StringIO())

    follow_up = [row for row in lines(call_log.detail_path()) if row["type"] == "attempt_start"][2]
    assert follow_up["replay"]["contents"][2] == {"role": "user", "parts": [
        {"functionResponse": {"name": "shell", "response": {
            "exit_code": 3, "prefix-[redacted]": {"inner-[redacted]": "[redacted]"}}}},
        {"functionResponse": {"name": "websearch", "response": {"results": [
            {"title": "[redacted]", "prefix-[redacted]": "[redacted]"}]}}}]}


def test_unknown_command_name_is_redacted_in_companion_but_fixed_name_is_kept(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    config = runtime_config.load()
    config.api_keys["openrouter"] = "help"
    run_repl(config, input_stream=StringIO("/prefix-help\n/help\nexit\n"), output_stream=StringIO())
    audit = lines(call_log.detail_path())
    starts = [row for row in audit if row["type"] == "action_start"]
    assert [row["name"] for row in starts] == ["/prefix-[redacted]", "/help"]
    assert "prefix-help" not in json.dumps(audit)
    main = [row for row in lines(call_log.session_log_path()) if row["type"] == "audit_event"]
    assert main[0]["name"] == "/prefix-[redacted]"
    assert [row["action_id"] for row in main] == [row["action_id"] for row in starts]


def test_invalid_tool_and_local_command_link_their_intents_to_outcomes(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    responses = [AssistantMessage(None, (ToolCall("bad", "calculator", {"expression": 5}),)),
                 AssistantMessage("done")]

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            return responses.pop(0), {}

        def is_retryable(self, exc):
            return False

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    run_repl(runtime_config.load(), input_stream=StringIO("/unknown\nhi\nexit\n"), output_stream=StringIO())
    main = lines(call_log.session_log_path())
    audit = lines(call_log.detail_path())
    for action in ("command", "tool"):
        starts = [row for row in audit if row["type"] == "action_start" and row["action"] == action]
        assert len(starts) == 1
        outcomes = [row for row in main if row.get("action_id") == starts[0]["action_id"]]
        assert len(outcomes) == 1
        if action == "command":
            assert outcomes[0]["outcome"] == "error"
        else:
            assert outcomes[0]["ok"] is False
        assert any(row["type"] == "action_end" and row["action_id"] == starts[0]["action_id"] for row in audit)


def test_local_outcome_failure_stops_before_another_command(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    original = call_log.write_detail

    def fail(kind, **fields):
        if kind == "local_outcome":
            raise call_log.AuditError("outcome unavailable")
        original(kind, **fields)

    monkeypatch.setattr(call_log, "write_detail", fail)
    with pytest.raises(call_log.AuditError, match="outcome unavailable"):
        run_repl(runtime_config.load(), input_stream=StringIO("/mode plan\n/clear\n"), output_stream=StringIO())
    main = lines(call_log.session_log_path())
    assert not any(row["type"] in {"conversation_cleared", "audit_coverage_end", "turn_end"} for row in main)
    assert len([row for row in main if row["type"] == "audit_event"]) == 1
    sid = call_log.current_session_id()
    monkeypatch.setenv("PA_DETAILED_AUDIT", "0")
    run_repl(runtime_config.load(), resumed=(sid, *call_log.load_conversation(sid)),
             input_stream=StringIO("exit\n"), output_stream=StringIO())
    assert call_log.load_conversation(sid)[0] == ()


def test_short_audit_write_fails_closed_before_provider_call(route_env, monkeypatch, install_fake_urlopen):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    provider_calls = install_fake_urlopen("unexpected")
    original = call_log.open_detail

    def install_short_writer():
        original()
        file = call_log._detail_file

        class ShortWriter:
            def write(self, line):
                if '"type": "attempt_start"' in line:
                    return file.write(line[:-1])
                return file.write(line)

            def flush(self):
                file.flush()

            def close(self):
                file.close()

        monkeypatch.setattr(call_log, "_detail_file", ShortWriter())

    monkeypatch.setattr(call_log, "open_detail", install_short_writer)
    with pytest.raises(call_log.AuditError, match="write detailed audit"):
        run_repl(runtime_config.load(), input_stream=StringIO("first\nsecond\n"), output_stream=StringIO())
    assert provider_calls == []
    main = lines(call_log.session_log_path())
    assert not any(row["type"] in {"attempt", "turn_end", "audit_coverage_end"} for row in main)
    assert call_log.load_conversation(call_log.current_session_id())[0] == ()


def test_close_failure_does_not_claim_complete_coverage(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    original = call_log.close_detail

    def fail():
        original()
        raise call_log.AuditError("injected close failure")

    monkeypatch.setattr(call_log, "close_detail", fail)
    with pytest.raises(call_log.AuditError, match="close failure"):
        run_repl(runtime_config.load(), input_stream=StringIO("exit\n"), output_stream=StringIO())
    assert not any(row["type"] in {"audit_coverage_end", "session_end"}
                   for row in lines(call_log.session_log_path()))


@pytest.mark.parametrize("fail_kind,script", [
    ("run_start", "hello\n"), ("attempt_start", "hello\n"), ("attempt_end", "hello\nnext\n"),
    ("action_start", "/clear\nhello\n"), ("action_end", "/remember note\nhello\n"),
    ("run_end", "exit\n"),
])
def test_detail_write_failure_stops_without_false_end(route_env, monkeypatch, install_fake_urlopen, fail_kind, script):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    calls = install_fake_urlopen(["answer", "second"])
    original = call_log.write_detail

    def fail(kind, **fields):
        if kind == fail_kind:
            raise call_log.AuditError("injected write failure")
        original(kind, **fields)

    monkeypatch.setattr(call_log, "write_detail", fail)
    with pytest.raises(call_log.AuditError, match="injected"):
        run_repl(runtime_config.load(), input_stream=StringIO(script), output_stream=StringIO())
    main = lines(call_log.session_log_path())
    assert not any(row["type"] == "audit_coverage_end" for row in main)
    assert len(calls) == (0 if fail_kind in {"run_start", "attempt_start", "action_start", "action_end", "run_end"} else 1)
    assert call_log.load_conversation(call_log.current_session_id())


@pytest.mark.parametrize("unsafe", ["symlink", "open"])
def test_refuse_unsafe_existing_companion(route_env, monkeypatch, unsafe, tmp_path):
    config = runtime_config.load()
    run_repl(config, input_stream=StringIO("exit\n"), output_stream=StringIO())
    sid = call_log.current_session_id()
    target = Path(call_log.detail_path())
    if unsafe == "symlink":
        other = tmp_path / "other"
        other.write_text("intact")
        target.symlink_to(other)
    else:
        target.write_text("\n")
        target.chmod(0o644)
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    with pytest.raises(call_log.AuditError):
        run_repl(config, resumed=(sid, *call_log.load_conversation(sid)), input_stream=StringIO("/clear\n"), output_stream=StringIO())
    if unsafe == "symlink":
        assert other.read_text() == "intact"


def test_shell_observation_in_companion_is_bounded_and_distinguishes_outcomes(
    route_env, monkeypatch, tmp_path, install_fake_urlopen
):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    workspace.configure_workspace(tmp_path)
    shell_tool.configure_shell(None, "50", 50)
    tools_registry.enable_shell_tool()
    calls = [
        {"tool_calls": [{"id": "a", "name": "shell", "arguments": {"command": "printf '%0100d' 0; exit 7"}}]},
        "first", {"tool_calls": [{"id": "b", "name": "shell", "arguments": {"command": "touch rejected.txt"}}]},
        "second", {"tool_calls": [{"id": "c", "name": "shell", "arguments": {"command": "invalid;"}}]},
        "third",
    ]
    install_fake_urlopen(calls)
    run_repl(runtime_config.load(), input_stream=StringIO("run first\ny\nrun second\nn\nrun third\ny\nexit\n"),
             output_stream=StringIO())
    main = [row for row in lines(call_log.session_log_path()) if row["type"] == "tool_execution"]
    assert main[0]["result"]["exit_code"] == 7
    assert main[0]["result"]["stdout"].endswith("[...truncated]")
    assert len(main[0]["result"]["stdout"].encode()) <= 50 + len("[...truncated]")
    assert main[1]["ok"] is False and not (tmp_path / "rejected.txt").exists()
    assert main[2]["result"]["exit_code"] != 0
    assert len([row for row in lines(call_log.detail_path()) if row["type"] == "action_start" and row["action"] == "tool"]) == 3


def test_tool_effect_may_precede_missing_companion_outcome(route_env, monkeypatch, tmp_path, install_fake_urlopen):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    install_fake_urlopen([{"tool_calls": [{"id": "c", "name": "shell", "arguments": {"command": "touch marker.txt"}}]},
                          "should not call"])
    original = call_log.write_detail
    tool_ids = set()

    def fail(kind, **fields):
        if kind == "action_start" and fields.get("action") == "tool":
            tool_ids.add(fields["action_id"])
        if kind == "action_end" and fields.get("action_id") in tool_ids:
            raise call_log.AuditError("injected tool result write failure")
        original(kind, **fields)

    monkeypatch.setattr(call_log, "write_detail", fail)
    with pytest.raises(call_log.AuditError, match="tool result"):
        run_repl(runtime_config.load(), input_stream=StringIO("/mode auto\nrun\nnext\n"), output_stream=StringIO())
    assert (tmp_path / "marker.txt").exists()
    main = lines(call_log.session_log_path())
    assert not any(row["type"] in {"turn_end", "audit_coverage_end"} for row in main)
    audit = lines(call_log.detail_path())
    assert any(row["type"] == "action_start" and row["action_id"] in tool_ids for row in audit)
    assert not any(row["type"] == "action_end" and row["action_id"] in tool_ids for row in audit)


def test_replaced_key_and_remember_text_redacted_without_config_secret_detail(route_env, monkeypatch):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    box = _ScriptedInputBox(["/config", "/remember test-key and new-secret", "hello", "exit"],
                            ["key", "openrouter", "done"], ["new-secret"])

    class Provider:
        prepare_input = staticmethod(router.get_provider("openrouter").prepare_input)

        def call(self, model, system, messages, **kwargs):
            return AssistantMessage("test-key and new-secret"), {}

        def is_retryable(self, exc):
            return False

    monkeypatch.setattr(router, "get_provider", lambda name: Provider())
    run_repl(runtime_config.load(), input_box=box, input_stream=StringIO(""), output_stream=StringIO())
    audit = lines(call_log.detail_path())
    assert "test-key" not in json.dumps(audit)
    assert "new-secret" not in json.dumps(audit)
    detail = [row for row in audit if row["type"] == "command_detail"]
    assert detail[0]["text"] == "[redacted] and [redacted]"
    assert not any(row["type"] == "command_detail" and row["name"] == "/config" for row in audit)
    assert [row for row in audit if row["type"] == "attempt_end"][0]["answer"] == "[redacted] and [redacted]"
