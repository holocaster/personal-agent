import json
import re
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from personal_agent import call_log, memory
from personal_agent.providers import http, openrouter
from personal_agent.routing import router, runtime_config
from personal_agent.terminal import repl
from personal_agent.terminal.repl import render_footer, render_usage, run_repl
from tests.fakes import FakeOpenRouterResponse, Repeat


def _http_error(code):
    return HTTPError("https://openrouter.ai", code, "err", None, None)


def test_two_repl_runs_in_one_process_write_two_distinct_session_files(route_env, install_fake_urlopen):
    install_fake_urlopen(["first answer", "second answer"])
    config = runtime_config.load()

    run_repl(config, input_stream=StringIO("summarize this line\nexit\n"), output_stream=StringIO())
    first_path = Path(call_log.session_log_path())
    first_session_id = call_log.current_session_id()

    run_repl(config, input_stream=StringIO("summarize this other line\nexit\n"), output_stream=StringIO())
    second_path = Path(call_log.session_log_path())
    second_session_id = call_log.current_session_id()

    assert first_session_id != second_session_id
    assert first_path != second_path
    assert len(first_path.read_text().splitlines()) == 7
    assert len(second_path.read_text().splitlines()) == 7


def test_repl_prints_routing_line_and_answer_per_task(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["first answer", "second answer"])
    input_stream = StringIO("summarize this line\nplease refactor this module\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert len(calls) == 2
    assert output.count("[openrouter] vendor/test-model\n") == 2
    assert "llm> first answer\n" in output
    assert "llm> second answer\n" in output


def test_repl_diagnostics_logs_provider_after_answer_without_waiting(route_env, monkeypatch):
    monkeypatch.setenv(openrouter.PROVIDER_DIAGNOSTICS_ENV_VAR, "1")
    responses = [
        {
            "id": "gen-first",
            "choices": [{"message": {"content": None, "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "todo", "arguments": json.dumps({"todos": [
                        {"content": "first", "status": "in_progress"},
                        {"content": "second", "status": "pending"},
                        {"content": "third", "status": "pending"},
                    ]}),
                },
            }]}}],
        },
        {"id": "gen-last", "choices": [{"message": {"content": "done"}}]},
    ]
    monkeypatch.setattr(http, "urlopen", lambda request, timeout:
                        FakeOpenRouterResponse(responses.pop(0)).stream())
    lookup_ids = []

    def fake_urlopen(request, timeout):
        lookup_ids.append(request.full_url.rsplit("=", 1)[-1])
        return FakeOpenRouterResponse({"data": {"provider_name": {
            "gen-first": "CoreWeave", "gen-last": "GMICloud"
        }[lookup_ids[-1]]}})

    monkeypatch.setattr(openrouter, "urlopen", fake_urlopen)
    pending = []

    class DeferredThread:
        def __init__(self, *, target, args, daemon):
            assert daemon is True
            self.target = target
            self.args = args

        def start(self):
            pending.append((self.target, self.args))

    monkeypatch.setattr(router, "Thread", DeferredThread, raising=False)
    output = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO("plan three steps\nexit\n"), output_stream=output)

    assert lookup_ids == []
    assert "[openrouter] vendor/test-model\n" in output.getvalue()
    assert "llm> done\n" in output.getvalue()
    attempts = [line for line in _session_lines() if line["type"] == "attempt"]
    assert len(pending) == 2
    assert [entry["upstream_provider"] for entry in attempts] == [None, None]

    for work, args in reversed(pending):
        work(*args)

    assert lookup_ids == ["gen-last", "gen-first"]
    provider_events = [line for line in _session_lines() if line["type"] == "upstream_provider"]
    assert [(event["attempt_timestamp"], event["upstream_provider"]) for event in provider_events] == [
        (attempts[1]["timestamp"], "GMICloud"), (attempts[0]["timestamp"], "CoreWeave")
    ]


def test_repl_sends_prior_completed_turn_as_history_on_a_follow_up(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["first answer", "second answer"])
    input_stream = StringIO("summarize this line\nsummarize this other line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 2
    second_body = json.loads(calls[1]["request"].data)
    sent_contents = [m["content"] for m in second_body["messages"] if m["role"] != "system"]
    assert sent_contents == ["summarize this line", "first answer", "summarize this other line"]


def test_repl_does_not_carry_a_failed_tasks_turn_into_the_next_request(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([ValueError("bad request"), "second answer"])
    input_stream = StringIO("summarize this line\nsummarize this other line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 2
    second_body = json.loads(calls[1]["request"].data)
    sent_contents = [m["content"] for m in second_body["messages"] if m["role"] != "system"]
    assert sent_contents == ["summarize this other line"]


def test_follow_up_receives_recorded_progress_and_failure_without_reexecuting_tools(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([{"tool_calls": [{"id": "calc-1", "name": "calculator",
                                                  "arguments": {"expression": "2+2"}}]},
                                 ValueError("connection lost"), "The calculation already returned 4."])
    run_repl(runtime_config.load(), input_stream=StringIO("calculate\nporque parou?\nexit\n"), output_stream=StringIO())
    body = json.loads(calls[-1]["request"].data)
    system = body["messages"][0]["content"]
    assert "Recorded context from the previous unfinished task" in system
    assert "connection lost" in system and "calculator" in system and '"result": 4' in system
    assert [m["content"] for m in body["messages"] if m["role"] == "user"] == ["porque parou?"]
    assert len(calls) == 3


def test_unfinished_context_redacts_secrets_before_bounding_the_record():
    secret = "fixture-secret-" * 50
    state = {"ok": False, "task": "a" * 15950 + secret, "error": "failed", "continuation": {
        "messages": [{"role": "tool_result", "name": "calculator", "is_error": False, "content": {"result": 4}}]}}
    context = repl._unfinished_context(state, (secret,))
    assert "fixture-secret" not in context and "[redacted]" in context and "[record truncated]" in context
    assert repl._unfinished_context(None) == "" and repl._unfinished_context({"ok": True}) == ""


def test_repl_skips_blank_lines_without_calling(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["only answer"])
    input_stream = StringIO("\n   \nsummarize this line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 1


def test_repl_ends_on_eof(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["only answer"])
    input_stream = StringIO("summarize this line\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 1
    assert "only answer" in output_stream.getvalue()


def test_repl_ends_on_quit(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([])
    input_stream = StringIO("quit\nsummarize this line\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 0


def test_repl_prints_error_and_continues_to_next_task_on_provider_failure(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([ValueError("bad request"), "second answer"])
    input_stream = StringIO("summarize this line\nplease refactor this module\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert len(calls) == 2
    assert "bad request" in output
    assert "second answer" in output


class _RaisingOnIdleReadStream:
    def __iter__(self):
        return self

    def __next__(self):
        raise KeyboardInterrupt


def test_repl_ends_cleanly_on_keyboard_interrupt_at_idle_prompt(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([])

    run_repl(config=runtime_config.load(), input_stream=_RaisingOnIdleReadStream(), output_stream=StringIO())

    assert len(calls) == 0


class _RaisingOnIdleReadStreamWithUnexpectedError:
    def __iter__(self):
        return self

    def __next__(self):
        raise ValueError("boom")


def _session_lines():
    return [entry for line in Path(call_log.session_log_path()).read_text().splitlines()
            if (entry := json.loads(line))["type"] not in {
                "audit_event", "audit_coverage_start", "audit_coverage_end", "routed_task_submitted"}]


def test_session_start_is_first_line_naming_the_configured_pair_without_secrets(route_env, install_fake_urlopen):
    install_fake_urlopen(["the answer"])
    input_stream = StringIO("summarize this line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    lines = _session_lines()
    start = lines[0]
    assert start["type"] == "session_start"
    assert sum(1 for entry in lines if entry["type"] == "session_start") == 1
    assert start["session_id"] == call_log.current_session_id()
    assert set(start) == {"timestamp", "session_id", "type", "log_version", "provider", "model", "workspace_root", "project_id", "run_id",
                          "access_method"}
    assert start["log_version"] == 3
    assert (start["provider"], start["model"]) == ("openrouter", "vendor/test-model")
    assert "test-key" not in json.dumps(start)


def test_session_end_is_last_line_and_has_exit_command_reason_for_bare_exit(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    input_stream = StringIO("exit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    lines = _session_lines()
    end = lines[-1]
    assert end["type"] == "session_end"
    assert sum(1 for entry in lines if entry["type"] == "session_end") == 1
    assert end["session_id"] == call_log.current_session_id()
    assert set(end) == {"timestamp", "session_id", "type", "reason", "total_cost"}
    assert end["reason"] == "exit_command"


def test_session_end_reason_is_exit_command_for_slash_exit(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    input_stream = StringIO("/exit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert _session_lines()[-1]["reason"] == "exit_command"


def test_session_end_reason_is_eof_when_input_stream_is_exhausted(route_env, install_fake_urlopen):
    install_fake_urlopen(["only answer"])
    input_stream = StringIO("summarize this line\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert _session_lines()[-1]["reason"] == "eof"


def test_session_end_reason_is_interrupt_on_idle_keyboard_interrupt(route_env, install_fake_urlopen):
    install_fake_urlopen([])

    run_repl(config=runtime_config.load(), input_stream=_RaisingOnIdleReadStream(), output_stream=StringIO())

    assert _session_lines()[-1]["reason"] == "interrupt"


def test_session_end_reason_is_error_and_exception_still_propagates_on_unexpected_input_stream_failure(
    route_env, install_fake_urlopen
):
    install_fake_urlopen([])

    with pytest.raises(ValueError, match="boom"):
        run_repl(
            config=runtime_config.load(),
            input_stream=_RaisingOnIdleReadStreamWithUnexpectedError(),
            output_stream=StringIO(),
        )

    assert _session_lines()[-1]["reason"] == "error"


def test_ctrl_c_during_a_request_does_not_end_the_session(route_env, install_fake_urlopen):
    install_fake_urlopen([KeyboardInterrupt(), "second answer"])
    input_stream = StringIO("summarize this line\nsummarize this other line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    lines = _session_lines()
    session_ends = [entry for entry in lines if entry["type"] == "session_end"]
    assert len(session_ends) == 1
    assert session_ends[0]["reason"] == "exit_command"


# --- turn_end / conversation_cleared (log_version 2) -----------------------


def test_successful_turn_writes_turn_end_ok_with_the_turns_messages(route_env, install_fake_urlopen):
    install_fake_urlopen(["the answer"])
    input_stream = StringIO("summarize this line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    lines = _session_lines()
    turn_ends = [entry for entry in lines if entry["type"] == "turn_end"]
    assert len(turn_ends) == 1
    entry = turn_ends[0]
    assert set(entry) == {"timestamp", "session_id", "type", "status", "messages"}
    assert entry["status"] == "ok"
    assert entry["session_id"] == call_log.current_session_id()
    assert entry["messages"] == [
        {"role": "user", "content": "summarize this line"},
        {"role": "assistant", "content": "the answer"},
    ]
    # Written after that turn's Attempt entry, before session_end.
    assert [entry["type"] for entry in lines] == ["session_start", "attempt", "turn_end", "session_end"]


def test_failed_turn_writes_turn_end_error_with_the_routers_error_text(route_env, install_fake_urlopen):
    install_fake_urlopen([ValueError("bad request")])
    input_stream = StringIO("summarize this line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    turn_ends = [entry for entry in _session_lines() if entry["type"] == "turn_end"]
    assert len(turn_ends) == 1
    entry = turn_ends[0]
    assert set(entry) == {"timestamp", "session_id", "type", "status", "error", "continuation", "ordinal", "task_digest"}
    assert entry["status"] == "error"
    assert "bad request" in entry["error"]
    assert entry["ordinal"] == 1
    assert entry["task_digest"] == call_log.submission_digest("summarize this line")
    assert entry["continuation"]["messages"] == [{"role": "user", "content": "summarize this line"}]


def test_retry_exhausted_turn_writes_turn_end_error(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    install_fake_urlopen([_http_error(503), _http_error(503), _http_error(503)])
    input_stream = StringIO("summarize this line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    turn_ends = [entry for entry in _session_lines() if entry["type"] == "turn_end"]
    assert len(turn_ends) == 1
    assert turn_ends[0]["status"] == "error"
    assert "HTTPError" in turn_ends[0]["error"]


def test_interrupted_turn_writes_turn_end_interrupted_with_continuation(route_env, install_fake_urlopen):
    install_fake_urlopen([KeyboardInterrupt(), "second answer"])
    input_stream = StringIO("summarize this line\nsummarize this other line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    turn_ends = [entry for entry in _session_lines() if entry["type"] == "turn_end"]
    assert [entry["status"] for entry in turn_ends] == ["interrupted", "ok"]
    interrupted_entry = turn_ends[0]
    assert set(interrupted_entry) == {"timestamp", "session_id", "type", "status", "continuation", "ordinal", "task_digest"}
    assert interrupted_entry["ordinal"] == 1
    assert interrupted_entry["task_digest"] == call_log.submission_digest("summarize this line")
    assert interrupted_entry["continuation"]["messages"] == [{"role": "user", "content": "summarize this line"}]


def test_tool_using_ok_turn_writes_turn_end_messages_with_tool_calls_and_results(route_env, install_fake_urlopen):
    install_fake_urlopen(
        [
            {"tool_calls": [{"id": "call_1", "name": "calculator", "arguments": {"expression": "2+2"}}]},
            "It is 4.",
        ]
    )
    input_stream = StringIO("what is 2+2?\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    turn_ends = [entry for entry in _session_lines() if entry["type"] == "turn_end"]
    assert len(turn_ends) == 1
    messages = turn_ends[0]["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "tool_result", "assistant"]
    assert messages[1]["tool_calls"][0]["name"] == "calculator"
    assert messages[2]["name"] == "calculator"
    assert messages[3]["content"] == "It is 4."


def test_repl_commands_exit_words_and_blank_lines_write_no_turn_end(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    input_stream = StringIO("/help\n\n   \n/history\n/models\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert [entry["type"] for entry in _session_lines()] == ["session_start", "session_end"]


def test_clear_writes_conversation_cleared_after_emptying_the_conversation(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    input_stream = StringIO("/clear\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    lines = _session_lines()
    assert [entry["type"] for entry in lines] == ["session_start", "conversation_cleared", "session_end"]
    cleared = lines[1]
    assert set(cleared) == {"timestamp", "session_id", "type"}
    assert cleared["session_id"] == call_log.current_session_id()


def test_mixed_run_line_order_covers_ok_error_interrupted_and_clear(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    install_fake_urlopen(
        [
            "first answer",
            ValueError("bad request"),
            KeyboardInterrupt(),
        ]
    )
    input_stream = StringIO(
        "summarize this line\n"
        "summarize this other line\n"
        "summarize a third line\n"
        "/clear\n"
        "exit\n"
    )
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert [entry["type"] for entry in _session_lines()] == [
        "session_start",
        "attempt",
        "turn_end",
        "attempt",
        "turn_end",
        "attempt",
        "turn_end",
        "conversation_cleared",
        "session_end",
    ]


def test_total_cost_sums_attempt_costs_across_tasks_with_no_budget_env_set(route_env, install_fake_urlopen):
    install_fake_urlopen(
        [{"content": "first answer", "usage": {"cost": 0.6}}, {"content": "second answer", "usage": {"cost": 0.5}}]
    )
    input_stream = StringIO("summarize this line\nsummarize this other line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert _session_lines()[-1]["total_cost"] == pytest.approx(1.1)


def test_total_cost_includes_retried_attempt_costs(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    install_fake_urlopen(
        [
            _http_error(503),
            _http_error(503),
            {"content": "recovered answer", "usage": {"cost": 0.3}},
        ]
    )
    input_stream = StringIO("summarize this line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert _session_lines()[-1]["total_cost"] == pytest.approx(0.3)


def test_repl_lets_user_retry_after_exhaustion_on_the_same_route(
    route_env, install_fake_urlopen, monkeypatch
):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    calls = install_fake_urlopen(
        [_http_error(503), _http_error(503), _http_error(503), "manual retry answer"]
        + [_http_error(503), _http_error(503), _http_error(503)]
    )
    input_stream = StringIO("summarize this line\n/retry\nplease refactor this module\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert len(calls) == 7
    assert "manual retry answer" in output
    error_lines = [line for line in output.splitlines() if line.startswith("Error:")]
    assert error_lines == [f"Error: HTTPError: {_http_error(503)}"] * 2
    assert "Use /retry to try again; to use another model, select it first with /model <provider> <model-id>." in output
    assert [json.loads(call["request"].data)["model"] for call in calls] == ["vendor/test-model"] * 7


def test_repl_prints_original_failure_and_manual_retry_guidance(
    route_env, install_fake_urlopen, monkeypatch
):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    calls = install_fake_urlopen([_http_error(503), _http_error(503), _http_error(503)])
    input_stream = StringIO("summarize this line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 3
    output = output_stream.getvalue()
    assert f"Error: HTTPError: {_http_error(503)}" in output
    assert "Use /retry to try again; to use another model, select it first with /model <provider> <model-id>." in output


def test_repl_accumulates_spend_across_tasks_in_one_session(
    route_env, install_fake_urlopen, monkeypatch
):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    calls = install_fake_urlopen(
        [
            {"content": "first task answer", "usage": {"cost": 0.6}},
            {"content": "second task answer", "usage": {"cost": 0.5}},
        ]
        + [_http_error(503), _http_error(503), _http_error(503)]
    )
    input_stream = StringIO("summarize this line\nsummarize this other line\nsummarize a third line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 5
    output = output_stream.getvalue()
    assert f"Error: HTTPError: {_http_error(503)}" in output
    assert call_log.total_cost() == pytest.approx(1.1)


def test_repl_aborts_call_and_continues_on_keyboard_interrupt_during_call(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([KeyboardInterrupt(), "second answer"])
    input_stream = StringIO("summarize this line\nplease refactor this module\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert len(calls) == 2
    assert "Interrupted." in output
    assert "second answer" in output


def test_help_command_lists_all_commands_and_calls_nothing(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([])
    input_stream = StringIO("/help\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    for command in (
        "/help", "/clear", "/history", "/model", "/undo", "/retry", "/compress",
        "/config", "/remember", "/memory", "/forget", "/usage", "/jobs", "/exit",
    ):
        assert command in output
    assert len(calls) == 0
    # A command-only Session still writes its session_start/session_end
    # bracket; "commands are free" now means zero attempt lines, not a
    # missing file.
    lines = _session_lines()
    assert [entry["type"] for entry in lines] == ["session_start", "session_end"]
    assert lines[-1]["total_cost"] == 0.0


def test_history_command_reports_empty_state_before_any_turn(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([])
    input_stream = StringIO("/history\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 0
    assert "No completed turns yet." in output_stream.getvalue()


def test_history_command_renders_completed_turns_in_order(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["first answer", "second answer"])
    input_stream = StringIO("summarize this line\nsummarize this other line\n/history\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 2
    output = output_stream.getvalue()
    history_section = output.split("/history")[-1]
    assert "user: summarize this line" in history_section
    assert "assistant: first answer" in history_section
    assert "user: summarize this other line" in history_section
    assert "assistant: second answer" in history_section
    assert history_section.index("first answer") < history_section.index("summarize this other line")


def test_model_command_shows_the_configured_pair_without_secrets_or_records(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO("/model\nexit\n"), output_stream=output_stream)

    assert calls == []
    lines = output_stream.getvalue().splitlines()
    assert lines[2:] == [
        "Provider/model: openrouter vendor/test-model",
        "Models.dev offering: context 128000, output 16000",
        lines[4],
        "Change with /model <provider> <model-id>; search with /models [provider] [query]."]
    assert "Catalog metadata does not prove account access" in lines[4]
    assert "test-key" not in output_stream.getvalue()
    assert [entry["type"] for entry in _session_lines()] == ["session_start", "session_end"]


@pytest.mark.parametrize("arguments", ["easy", "auto", "openrouter vendor/other extra"])
def test_model_command_rejects_other_shapes_and_keeps_the_pair(route_env, install_fake_urlopen, arguments):
    calls = install_fake_urlopen(["the answer"])
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO(f"/model {arguments}\ntask\nexit\n"),
             output_stream=output_stream)

    assert "Error: usage: /model [<provider> <model-id>]\n" in output_stream.getvalue()
    assert [json.loads(call["request"].data)["model"] for call in calls] == ["vendor/test-model"]


# --- /undo and /retry -------------------------------------------------


def test_undo_removes_the_last_turn_and_writes_turn_undone(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["first answer", "second answer"])
    input_stream = StringIO("summarize this line\n/undo\nsummarize this other line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert "Turn undone.\n" in output_stream.getvalue()
    lines = _session_lines()
    assert [entry["type"] for entry in lines] == [
        "session_start",
        "attempt",
        "turn_end",
        "turn_undone",
        "attempt",
        "turn_end",
        "session_end",
    ]
    undone = lines[3]
    assert set(undone) == {"timestamp", "session_id", "type"}
    assert undone["session_id"] == call_log.current_session_id()
    assert lines[2]["status"] == "ok"
    second_body = json.loads(calls[1]["request"].data)
    sent_contents = [m["content"] for m in second_body["messages"] if m["role"] != "system"]
    assert sent_contents == ["summarize this other line"]


def test_undo_removes_the_turn_from_history(route_env, install_fake_urlopen):
    install_fake_urlopen(["first answer"])
    input_stream = StringIO("summarize this line\n/undo\n/history\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "No completed turns yet." in output
    assert "assistant: first answer" not in output


def test_repeated_undo_removes_one_turn_each_time_then_errors_with_none_left(route_env, install_fake_urlopen):
    install_fake_urlopen(["first answer", "second answer"])
    input_stream = StringIO("summarize this line\nsummarize this other line\n/undo\n/undo\n/undo\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert output.count("Turn undone.\n") == 2
    assert "Error: no turn to undo.\n" in output
    lines = _session_lines()
    assert [entry["type"] for entry in lines].count("turn_undone") == 2


def test_retry_with_no_routed_task_yet_reports_error_and_sends_nothing(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([])
    input_stream = StringIO("/retry\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 0
    assert "Error: no task to retry.\n" in output_stream.getvalue()


def test_retry_right_after_a_resume_reports_error_and_sends_nothing(route_env, install_fake_urlopen):
    session_id, turns = _build_resumable_session(
        "summarize this line", "first answer", route_env, install_fake_urlopen
    )
    calls = install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/retry\nexit\n"),
        output_stream=output_stream,
        resumed=(session_id, turns, None, [], call_log.load_conversation(session_id)[3]),
    )

    assert len(calls) == 0
    assert "Error: no task to retry.\n" in output_stream.getvalue()


def test_retry_after_an_ok_turn_undoes_it_once_then_resends_holding_the_task_once(
    route_env, install_fake_urlopen
):
    calls = install_fake_urlopen(["first answer", "second answer"])
    input_stream = StringIO("summarize this line\n/retry\n/history\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 2
    lines = _session_lines()
    assert [entry["type"] for entry in lines] == [
        "session_start",
        "attempt",
        "turn_end",
        "turn_undone",
        "routed_task_retried",
        "attempt",
        "turn_end",
        "session_end",
    ]
    output = output_stream.getvalue()
    history_section = output.split("/history")[-1]
    assert history_section.count("user: summarize this line") == 1
    assert "second answer" in history_section
    assert output.count("llm> ") == 2


def test_retry_after_an_error_turn_resends_without_undoing_anything(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([ValueError("bad request"), "second answer"])
    input_stream = StringIO("summarize this line\n/retry\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 2
    lines = _session_lines()
    assert [entry["type"] for entry in lines] == [
        "session_start",
        "attempt",
        "turn_end",
        "routed_task_retried",
        "attempt",
        "turn_end",
        "session_end",
    ]
    output = output_stream.getvalue()
    assert "bad request" in output
    assert "second answer" in output


def test_retry_after_an_interrupted_turn_resends_without_undoing_anything(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([KeyboardInterrupt(), "second answer"])
    input_stream = StringIO("summarize this line\n/retry\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 2
    lines = _session_lines()
    assert [entry["type"] for entry in lines] == [
        "session_start",
        "attempt",
        "turn_end",
        "routed_task_retried",
        "attempt",
        "turn_end",
        "session_end",
    ]
    assert not lines[1]["ok"]
    assert lines[1]["error"] == "KeyboardInterrupt: interrupted"
    assert lines[1]["cost"] is None
    assert lines[2]["status"] == "interrupted"
    assert lines[5]["status"] == "ok"
    assert "second answer" in output_stream.getvalue()


def test_retry_after_an_undone_ok_turn_resends_without_undoing_again(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["first answer", "second answer"])
    input_stream = StringIO("summarize this line\n/undo\n/retry\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 2
    lines = _session_lines()
    assert [entry["type"] for entry in lines] == [
        "session_start",
        "attempt",
        "turn_end",
        "turn_undone",
        "routed_task_retried",
        "attempt",
        "turn_end",
        "session_end",
    ]


def test_retry_after_a_cleared_ok_turn_resends_without_undoing_anything(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["first answer", "second answer"])
    input_stream = StringIO("summarize this line\n/clear\n/retry\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 2
    lines = _session_lines()
    assert [entry["type"] for entry in lines] == [
        "session_start",
        "attempt",
        "turn_end",
        "conversation_cleared",
        "routed_task_retried",
        "attempt",
        "turn_end",
        "session_end",
    ]


def test_retry_that_fails_leaves_the_undone_turn_undone(route_env, install_fake_urlopen):
    install_fake_urlopen(["first answer", ValueError("bad request")])
    input_stream = StringIO("summarize this line\n/retry\n/history\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "bad request" in output
    history_section = output.split("/history")[-1]
    assert "No completed turns yet." in history_section
    lines = _session_lines()
    assert [entry["type"] for entry in lines].count("turn_undone") == 1


def test_resumed_conversation_drops_the_turn_removed_by_undo(route_env, install_fake_urlopen):
    install_fake_urlopen(["first answer", "second answer"])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("summarize this line\nsummarize this other line\n/undo\nexit\n"),
        output_stream=StringIO(),
    )
    session_id = call_log.current_session_id()
    call_log.reset_session()
    turns, _, _, _ = call_log.load_conversation(session_id)
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/history\nexit\n"),
        output_stream=output_stream,
        resumed=(session_id, turns, None, [], call_log.load_conversation(session_id)[3]),
    )

    output = output_stream.getvalue()
    assert output.startswith(f"Resumed session {session_id}: 1 turns.\n")
    history_section = output.split("/history")[-1]
    assert "summarize this line" in history_section
    assert "first answer" in history_section
    assert "summarize this other line" not in history_section
    assert "second answer" not in history_section


def test_exit_command_leaves_the_repl_like_bare_exit(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([])
    input_stream = StringIO("/exit\nsummarize this line\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 0


def test_unknown_slash_command_reports_a_local_error_and_calls_nothing(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([])
    input_stream = StringIO("/nope\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 0
    assert "Error:" in output_stream.getvalue()


def test_argument_free_command_with_arguments_reports_a_local_error_and_calls_nothing(
    route_env, install_fake_urlopen
):
    calls = install_fake_urlopen([])
    input_stream = StringIO("/history now\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 0
    assert "Error:" in output_stream.getvalue()


def test_clear_command_empties_history_but_keeps_config_log_and_spending(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([{"content": "first answer", "usage": {"cost": 0.4}}, "second answer"])
    input_stream = StringIO("summarize this line\n/clear\n/history\nsummarize this other line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert len(calls) == 2
    assert "Conversation cleared." in output
    assert "No completed turns yet." in output
    assert call_log.total_cost() == 0.4
    lines = _session_lines()
    assert len(lines) == 7
    assert [entry["type"] for entry in lines] == [
        "session_start",
        "attempt",
        "turn_end",
        "conversation_cleared",
        "attempt",
        "turn_end",
        "session_end",
    ]
    session_id = call_log.current_session_id()
    assert all(entry["session_id"] == session_id for entry in lines)
    assert lines[-1]["total_cost"] == 0.4
    second_body = json.loads(calls[1]["request"].data)
    sent_contents = [m["content"] for m in second_body["messages"] if m["role"] != "system"]
    assert sent_contents == ["summarize this other line"]


def test_repl_sends_exactly_twenty_completed_turns_at_the_boundary(route_env, install_fake_urlopen):
    answers = [f"answer {n}" for n in range(1, 21)]
    calls = install_fake_urlopen(answers)
    lines = [f"task {n}" for n in range(1, 21)] + ["exit"]
    input_stream = StringIO("\n".join(lines) + "\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 20
    last_body = json.loads(calls[19]["request"].data)
    sent_contents = [m["content"] for m in last_body["messages"] if m["role"] != "system"]
    assert sent_contents[0] == "task 1"
    assert sent_contents[-1] == "task 20"
    assert len(sent_contents) == 19 * 2 + 1


def test_repl_sends_every_completed_turn_past_twenty_prior_turns(route_env, install_fake_urlopen):
    answers = [f"answer {n}" for n in range(1, 23)]
    calls = install_fake_urlopen(answers)
    lines = [f"task {n}" for n in range(1, 23)] + ["exit"]
    input_stream = StringIO("\n".join(lines) + "\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 22
    last_body = json.loads(calls[21]["request"].data)
    sent_contents = [m["content"] for m in last_body["messages"] if m["role"] != "system"]
    assert sent_contents[0] == "task 1"
    assert sent_contents[-1] == "task 22"
    assert len(sent_contents) == 21 * 2 + 1


def test_repl_carries_history_into_a_follow_up_that_selects_a_different_provider(
    route_env, install_fake_urlopen, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    calls = install_fake_urlopen(["first answer", "second answer"])
    run_repl(runtime_config.load(), input_stream=StringIO("summarize this line\nexit\n"), output_stream=StringIO())
    session_id = call_log.current_session_id()
    call_log.reset_session()
    monkeypatch.setenv("PA_PROVIDER", "anthropic")
    monkeypatch.setenv("PA_MODEL", "claude-3-haiku-20240307")

    run_repl(runtime_config.load(), input_stream=StringIO("please refactor this module\nexit\n"),
             output_stream=StringIO(), resumed=(session_id, *call_log.load_conversation(session_id)))

    assert len(calls) == 2
    assert calls[0]["request"].full_url == "https://openrouter.ai/api/v1/chat/completions"
    assert calls[1]["request"].full_url == "https://api.anthropic.com/v1/messages"
    second_body = json.loads(calls[1]["request"].data)
    sent_contents = [m["content"] for m in second_body["messages"]]
    assert sent_contents == ["summarize this line", "first answer", "please refactor this module"]


def test_render_footer_shows_the_configured_pair_mode_and_spend():
    assert render_footer("openrouter", "minimax/minimax-m3", 0.0009, mode="plan") == (
        " mode: plan · openrouter minimax/minimax-m3 · API key · ctx unknown · $0.0009 · /help")


def test_render_usage_before_any_completed_turn():
    assert render_usage(None, None, 0.0, False, None, None, 0, 0) == "No completed turns yet this Run.\n"


def test_render_usage_after_a_successful_turn():
    result = render_usage("openrouter", "minimax/minimax-m3", 0.0009, False, 12, 5, 3, 3)

    assert result == (
        "route: openrouter minimax/minimax-m3\n"
        "spend: $0.0009\n"
        "tokens: 12 prompt, 5 completion\n"
        "turns: 3 retained, 3 sent\n"
    )


def test_render_usage_marks_estimated_spend():
    result = render_usage("anthropic", "claude", 0.05, True, 100, 40, 25, 20)

    assert "spend: $0.0500 (estimated)\n" in result
    assert "turns: 25 retained, 20 sent\n" in result


def test_render_usage_shows_unknown_when_the_last_attempt_carried_no_usage():
    result = render_usage("openrouter", "minimax/minimax-m3", 0.0, False, None, None, 1, 1)

    assert "tokens: unknown prompt, unknown completion\n" in result


class _TTYInputStream:
    def __init__(self, lines):
        self._lines = iter(lines)

    def isatty(self):
        return True

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._lines)


def test_repl_prints_and_flushes_prompt_on_an_interactive_terminal(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["the answer"])
    input_stream = _TTYInputStream(["summarize this line\n", "exit\n"])
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 1
    assert output_stream.getvalue().count("user> ") == 2


def test_repl_does_not_print_prompt_for_piped_input(route_env, install_fake_urlopen):
    install_fake_urlopen(["the answer"])
    input_stream = StringIO("summarize this line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert "user> " not in output_stream.getvalue()


def test_history_command_renders_tool_calls_and_results_without_opaque_metadata(route_env, install_fake_urlopen):
    install_fake_urlopen(
        [
            {"tool_calls": [{"id": "call_1", "name": "calculator", "arguments": {"expression": "2+2"}}]},
            "It is 4.",
        ]
    )
    input_stream = StringIO("what is 2+2?\n/history\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    history_section = output_stream.getvalue().split("/history")[-1]
    assert "user: what is 2+2?" in history_section
    assert "tool_call: calculator({'expression': '2+2'}) id=call_1" in history_section
    assert "tool_result: calculator [ok] {'result': 4} id=call_1" in history_section
    assert "assistant: It is 4." in history_section
    assert "replay" not in history_section
    assert "thoughtSignature" not in history_section


def test_repl_stays_usable_after_a_tool_round_limit_error(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setenv("PA_MAX_TOOL_ROUNDS", "8")
    tool_call_response = {"tool_calls": [{"id": "call", "name": "calculator", "arguments": {"expression": "1+1"}}]}
    calls = install_fake_urlopen([tool_call_response] * 9 + ["second answer"])
    input_stream = StringIO("keep calculating\nsummarize this line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert len(calls) == 10
    assert "Error:" in output
    assert "8-round limit" in output
    assert "second answer" in output


# --- Tool Confirmation for write (R21-R35, ticket 0016-01) -----------------


def _write_tool_call(path, content):
    return {"tool_calls": [{"id": "call_1", "name": "write", "arguments": {"path": path, "content": content}}]}


def test_repl_shows_full_content_preview_for_a_new_file_and_applies_it_on_yes(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([_write_tool_call("note.txt", "hello there"), "wrote it"])
    input_stream = StringIO("create a note\ny\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "write: note.txt" in output
    assert "hello there" in output
    assert "Apply this change? [y/N] " in output
    assert 'tool> write(path="note.txt", content="hello there") -> ' in output
    assert "llm> wrote it\n" in output
    assert (tmp_path / "note.txt").read_text() == "hello there"


def test_piped_large_confirmation_keeps_full_preview_and_original_prompt(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    content = "\n".join(f"line {number}" for number in range(200))
    install_fake_urlopen([_write_tool_call("note.txt", content), "rejected"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("create a note\nn\nexit\n"), output_stream=output)

    assert content in output.getvalue()
    assert "Apply this change? [y/N] " in output.getvalue()
    assert "Hidden content" not in output.getvalue()
    assert not (tmp_path / "note.txt").exists()


def test_repl_shows_a_unified_diff_preview_for_an_overwrite_and_applies_it_on_yes(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    (tmp_path / "existing.txt").write_text("old\n")
    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([_write_tool_call("existing.txt", "new\n"), "overwritten"])
    input_stream = StringIO("overwrite the file\nyes\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "--- existing.txt" in output
    assert "-old" in output
    assert "+new" in output
    assert (tmp_path / "existing.txt").read_text() == "new\n"


def test_repl_rejects_a_write_on_a_non_yes_answer_tells_the_model_and_continues_the_turn(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([_write_tool_call("note.txt", "hello"), "understood, not writing"])
    input_stream = StringIO("create a note\nnope\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "error: change rejected by the user" in output
    assert "llm> understood, not writing\n" in output
    assert not (tmp_path / "note.txt").exists()


def test_repl_rejects_a_write_on_end_of_piped_input_and_then_exits_at_the_next_read(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([_write_tool_call("note.txt", "hello"), "no problem"])
    input_stream = StringIO("create a note\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "error: change rejected by the user" in output
    assert not (tmp_path / "note.txt").exists()


def test_repl_sanitizes_control_characters_in_the_confirmation_header_and_preview(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([_write_tool_call("note.txt", "forged\x1b[2K\rcontent"), "done"])
    input_stream = StringIO("create a note\ny\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "\x1b[2K" not in output
    assert "\\x1b" in output


def test_repl_writes_the_call_log_entry_and_live_tool_line_for_an_applied_rejected_and_failed_write(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    install_fake_urlopen(
        [
            _write_tool_call("ok.txt", "content"),
            "applied",
            _write_tool_call("rejected.txt", "content"),
            "rejected",
            {"tool_calls": [{"id": "call_1", "name": "write", "arguments": {"path": "../escape.txt", "content": "x"}}]},
            "failed",
        ]
    )
    input_stream = StringIO("write one\ny\nwrite two\nn\nwrite three\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    entries = _session_lines()
    tool_entries = [entry for entry in entries if entry["type"] == "tool_execution"]
    assert [entry["name"] for entry in tool_entries] == ["write", "write", "write"]
    assert tool_entries[0]["ok"] is True
    assert tool_entries[0]["result"] == {"path": "ok.txt", "bytes_written": 7, "created": True}
    assert tool_entries[1]["ok"] is False
    assert tool_entries[1]["error"] == "change rejected by the user"
    assert tool_entries[2]["ok"] is False
    assert "traversal" in tool_entries[2]["error"]


class _LinesThenInterrupt:
    """Yields the given lines, then raises KeyboardInterrupt on every read after."""

    def __init__(self, lines):
        self._lines = list(lines)

    def __iter__(self):
        return self

    def __next__(self):
        if not self._lines:
            raise KeyboardInterrupt
        return self._lines.pop(0)


def test_repl_logs_and_prints_an_already_applied_write_before_a_mid_batch_interrupt(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    install_fake_urlopen(
        [
            {
                "tool_calls": [
                    {"id": "call_1", "name": "write", "arguments": {"path": "a.txt", "content": "a"}},
                    {"id": "call_2", "name": "write", "arguments": {"path": "b.txt", "content": "b"}},
                ]
            }
        ]
    )
    input_stream = _LinesThenInterrupt(["write two files\n", "y\n"])
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert 'tool> write(path="a.txt", content="a") -> ' in output
    assert "Interrupted.\n" in output
    assert (tmp_path / "a.txt").read_text() == "a"
    assert not (tmp_path / "b.txt").exists()

    entries = _session_lines()
    tool_entries = [entry for entry in entries if entry["type"] == "tool_execution"]
    assert [entry["name"] for entry in tool_entries] == ["write"]
    assert tool_entries[0]["ok"] is True
    assert tool_entries[0]["result"] == {"path": "a.txt", "bytes_written": 1, "created": True}
    assert [entry["status"] for entry in entries if entry["type"] == "turn_end"] == ["interrupted"]


# --- Tool Confirmation for edit (R21-R35, ticket 0016-02) ------------------


def _edit_tool_call(path, old_string, new_string, replace_all=False):
    return {
        "tool_calls": [
            {
                "id": "call_1",
                "name": "edit",
                "arguments": {"path": path, "old_string": old_string, "new_string": new_string, "replace_all": replace_all},
            }
        ]
    }


def test_repl_shows_a_unified_diff_preview_for_an_edit_and_applies_it_on_yes(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    (tmp_path / "existing.txt").write_text("old line\nkept line\n")
    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([_edit_tool_call("existing.txt", "old line", "new line"), "edited"])
    input_stream = StringIO("fix the file\ny\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "edit: existing.txt" in output
    assert "--- existing.txt" in output
    assert "-old line" in output
    assert "+new line" in output
    assert "Apply this change? [y/N] " in output
    assert (tmp_path / "existing.txt").read_text() == "new line\nkept line\n"
    assert "llm> edited\n" in output


def test_repl_rejects_an_edit_on_a_non_yes_answer_tells_the_model_and_continues_the_turn(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    (tmp_path / "a.txt").write_text("old\n")
    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([_edit_tool_call("a.txt", "old", "new"), "understood, not editing"])
    input_stream = StringIO("fix the file\nnope\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "error: change rejected by the user" in output
    assert "llm> understood, not editing\n" in output
    assert (tmp_path / "a.txt").read_text() == "old\n"


def test_repl_writes_the_call_log_entry_and_live_tool_line_for_an_applied_rejected_and_failed_edit(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    (tmp_path / "ok.txt").write_text("old\n")
    (tmp_path / "rejected.txt").write_text("old\n")
    workspace.configure_workspace(tmp_path)
    install_fake_urlopen(
        [
            _edit_tool_call("ok.txt", "old", "new"),
            "applied",
            _edit_tool_call("rejected.txt", "old", "new"),
            "rejected",
            _edit_tool_call("missing.txt", "old", "new"),
            "failed",
        ]
    )
    input_stream = StringIO("edit one\ny\nedit two\nn\nedit three\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert 'tool> edit(path="ok.txt", old_string="old", new_string="new", replace_all=false) -> ' in output

    entries = _session_lines()
    tool_entries = [entry for entry in entries if entry["type"] == "tool_execution"]
    assert [entry["name"] for entry in tool_entries] == ["edit", "edit", "edit"]
    assert tool_entries[0]["ok"] is True
    assert tool_entries[0]["result"] == {"path": "ok.txt", "replacements": 1}
    assert tool_entries[1]["ok"] is False
    assert tool_entries[1]["error"] == "change rejected by the user"
    assert tool_entries[2]["ok"] is False


# --- Tool Confirmation for shell (R01-R39, ticket 0018-01) -----------------


def _shell_tool_call(command):
    return {"tool_calls": [{"id": "call_1", "name": "shell", "arguments": {"command": command}}]}


def test_repl_shows_the_command_and_asks_run_this_command_and_runs_it_on_yes(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import registry as tools_registry, workspace

    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    install_fake_urlopen([_shell_tool_call("echo hi > marker.txt"), "ran it"])
    input_stream = StringIO("run a command\ny\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert f"shell: {tmp_path.resolve()}" in output
    assert "echo hi > marker.txt" in output
    assert "Run this command? [y/N] " in output
    assert "llm> ran it\n" in output
    assert (tmp_path / "marker.txt").read_text() == "hi\n"


def test_repl_rejects_a_shell_command_on_a_non_yes_answer_and_runs_nothing(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import registry as tools_registry, workspace

    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    install_fake_urlopen([_shell_tool_call("touch marker.txt"), "not running it"])
    input_stream = StringIO("run a command\nn\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "error: change rejected by the user" in output
    assert not (tmp_path / "marker.txt").exists()


def test_repl_rejects_a_shell_command_on_end_of_piped_input(route_env, install_fake_urlopen, tmp_path):
    from personal_agent.tools import registry as tools_registry, workspace

    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    install_fake_urlopen([_shell_tool_call("touch marker.txt"), "no problem"])
    input_stream = StringIO("run a command\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "error: change rejected by the user" in output
    assert not (tmp_path / "marker.txt").exists()


def test_repl_writes_the_call_log_entry_and_live_tool_line_for_a_run_and_rejected_shell_call(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import registry as tools_registry, workspace

    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    install_fake_urlopen(
        [
            _shell_tool_call("echo ok"),
            "ran it",
            _shell_tool_call("echo no"),
            "rejected",
        ]
    )
    input_stream = StringIO("run one\ny\nrun two\nn\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert 'tool> shell(command="echo ok") -> ' in output

    entries = _session_lines()
    tool_entries = [entry for entry in entries if entry["type"] == "tool_execution"]
    assert [entry["name"] for entry in tool_entries] == ["shell", "shell"]
    assert tool_entries[0]["ok"] is True
    assert tool_entries[0]["result"] == {"stdout": "ok\n", "stderr": "", "exit_code": 0}
    assert tool_entries[1]["ok"] is False
    assert tool_entries[1]["error"] == "change rejected by the user"


# --- Dangerous Command and Strong Confirmation (R4-R5, ticket 0023-01) -----


def test_repl_rejects_a_dangerous_command_on_a_reflexive_y_and_runs_nothing(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import registry as tools_registry, workspace

    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    install_fake_urlopen([_shell_tool_call("eval touch marker.txt"), "not running it"])
    input_stream = StringIO("run a dangerous command\ny\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "Dangerous command: eval" in output
    assert "Type 'yes' to run this dangerous command: " in output
    assert "error: change rejected by the user" in output
    assert not (tmp_path / "marker.txt").exists()


def test_repl_approves_a_dangerous_command_on_yes_case_and_whitespace_insensitively(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import registry as tools_registry, workspace

    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    install_fake_urlopen([_shell_tool_call("eval touch marker.txt"), "ran it"])
    input_stream = StringIO("run a dangerous command\nYES \nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "llm> ran it\n" in output
    assert (tmp_path / "marker.txt").exists()


def test_repl_rejects_a_dangerous_command_on_end_of_piped_input(route_env, install_fake_urlopen, tmp_path):
    from personal_agent.tools import registry as tools_registry, workspace

    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    install_fake_urlopen([_shell_tool_call("eval touch marker.txt"), "no problem"])
    input_stream = StringIO("run a dangerous command\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "error: change rejected by the user" in output
    assert not (tmp_path / "marker.txt").exists()


def test_repl_colors_the_dangerous_command_line_red_on_an_interactive_terminal(
    route_env, install_fake_urlopen, monkeypatch, tmp_path
):
    from personal_agent.tools import registry as tools_registry, workspace

    monkeypatch.delenv("NO_COLOR", raising=False)
    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    install_fake_urlopen([_shell_tool_call("eval touch marker.txt"), "not running it"])
    input_stream = StringIO("run a dangerous command\ny\nexit\n")
    output_stream = _TTYOutputStream()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "\033[31mDangerous command: eval\033[0m\n" in output


def test_repl_normal_shell_command_is_still_approved_by_y_unchanged(route_env, install_fake_urlopen, tmp_path):
    from personal_agent.tools import registry as tools_registry, workspace

    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    install_fake_urlopen([_shell_tool_call("echo hi"), "ran it"])
    input_stream = StringIO("run a command\ny\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "Run this command? [y/N] " in output
    assert "Dangerous command:" not in output
    assert "llm> ran it\n" in output


def test_repl_logs_dangerous_rules_for_approved_and_rejected_flagged_calls_and_omits_the_key_for_a_normal_call(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import registry as tools_registry, workspace

    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    install_fake_urlopen(
        [
            _shell_tool_call("eval touch a.txt"),
            "ran it",
            _shell_tool_call("eval touch b.txt"),
            "rejected",
            _shell_tool_call("echo hi"),
            "ran plain",
        ]
    )
    input_stream = StringIO("run one\nyes\nrun two\ny\nrun three\ny\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    entries = _session_lines()
    tool_entries = [entry for entry in entries if entry["type"] == "tool_execution"]
    assert [entry["name"] for entry in tool_entries] == ["shell", "shell", "shell"]
    assert tool_entries[0]["dangerous_rules"] == ["eval"]
    assert tool_entries[1]["dangerous_rules"] == ["eval"]
    assert "dangerous_rules" not in tool_entries[2]


# --- Tool Confirmation for webfetch (R7-R12, ticket 0022-02) ---------------


def _webfetch_tool_call(url):
    return {"tool_calls": [{"id": "call_1", "name": "webfetch", "arguments": {"url": url}}]}


def _run_one_route_server():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            self.server.requests.append(self.path)
            body = b"fetched content"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.requests = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def test_repl_shows_the_url_and_asks_fetch_this_url_and_fetches_it_on_yes(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    httpd, thread = _run_one_route_server()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/page"
        install_fake_urlopen([_webfetch_tool_call(url), "fetched it"])
        input_stream = StringIO("fetch a page\ny\nexit\n")
        output_stream = StringIO()
        config = runtime_config.load()

        run_repl(config, input_stream=input_stream, output_stream=output_stream)

        output = output_stream.getvalue()
        assert f"webfetch: {url}" in output
        assert "Fetch this URL? [y/N] " in output
        assert "llm> fetched it\n" in output
        assert httpd.requests == ["/page"]
    finally:
        httpd.shutdown()
        thread.join()


def test_repl_rejects_a_webfetch_on_end_of_piped_input_and_makes_no_request(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    httpd, thread = _run_one_route_server()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/page"
        install_fake_urlopen([_webfetch_tool_call(url), "no problem"])
        input_stream = StringIO("fetch a page\n")
        output_stream = StringIO()
        config = runtime_config.load()

        run_repl(config, input_stream=input_stream, output_stream=output_stream)

        output = output_stream.getvalue()
        assert "error: change rejected by the user" in output
        assert httpd.requests == []
    finally:
        httpd.shutdown()
        thread.join()


# --- Fetched-Content Warning (R3, R7, R8, ticket 0023-02) ------------------


def test_repl_shows_the_fetched_content_warning_on_a_write_after_a_webfetch_in_the_same_turn(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    httpd, thread = _run_one_route_server()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/page"
        install_fake_urlopen([_webfetch_tool_call(url), _write_tool_call("note.txt", "hello"), "wrote it"])
        input_stream = StringIO("fetch then write\ny\ny\nexit\n")
        output_stream = StringIO()
        config = runtime_config.load()

        run_repl(config, input_stream=input_stream, output_stream=output_stream)

        output = output_stream.getvalue()
        assert (
            f"Warning: this turn fetched {url}. Web content may have steered this change; review it carefully.\n"
            in output
        )
        assert (tmp_path / "note.txt").read_text() == "hello"
    finally:
        httpd.shutdown()
        thread.join()


def _apply_patch_tool_call(patch):
    return {"tool_calls": [{"id": "call_1", "name": "apply_patch", "arguments": {"patch": patch}}]}


def test_repl_shows_the_fetched_content_warning_on_apply_patch_after_a_webfetch_in_the_same_turn(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    (tmp_path / "note.txt").write_text("before\n")
    workspace.configure_workspace(tmp_path)
    httpd, thread = _run_one_route_server()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/page"
        patch = "*** Begin Patch\n*** Update File: note.txt\n-before\n+after\n*** End Patch"
        install_fake_urlopen([_webfetch_tool_call(url), _apply_patch_tool_call(patch), "patched it"])
        input_stream = StringIO("fetch then patch\ny\ny\nexit\n")
        output_stream = StringIO()
        config = runtime_config.load()

        run_repl(config, input_stream=input_stream, output_stream=output_stream)

        output = output_stream.getvalue()
        assert (
            f"Warning: this turn fetched {url}. Web content may have steered this change; review it carefully.\n"
            in output
        )
        assert (tmp_path / "note.txt").read_text() == "after\n"
    finally:
        httpd.shutdown()
        thread.join()


def test_repl_shows_no_warning_on_the_webfetch_confirmation_itself(route_env, install_fake_urlopen, tmp_path):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    httpd, thread = _run_one_route_server()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/page"
        install_fake_urlopen([_webfetch_tool_call(url), "fetched it"])
        input_stream = StringIO("fetch a page\ny\nexit\n")
        output_stream = StringIO()
        config = runtime_config.load()

        run_repl(config, input_stream=input_stream, output_stream=output_stream)

        assert "Warning: this turn fetched" not in output_stream.getvalue()
    finally:
        httpd.shutdown()
        thread.join()


def test_repl_next_user_task_does_not_carry_a_previous_turns_warning(route_env, install_fake_urlopen, tmp_path):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    httpd, thread = _run_one_route_server()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/page"
        install_fake_urlopen(
            [
                _webfetch_tool_call(url),
                "fetched it",
                _write_tool_call("note.txt", "hello"),
                "wrote it",
            ]
        )
        input_stream = StringIO("fetch a page\ny\nwrite a note\ny\nexit\n")
        output_stream = StringIO()
        config = runtime_config.load()

        run_repl(config, input_stream=input_stream, output_stream=output_stream)

        write_section = output_stream.getvalue().split("write: note.txt")[-1]
        assert "Warning: this turn fetched" not in write_section
    finally:
        httpd.shutdown()
        thread.join()


def test_repl_retry_starts_without_the_warning_even_after_an_earlier_turns_webfetch(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    httpd, thread = _run_one_route_server()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/page"
        install_fake_urlopen(
            [
                _webfetch_tool_call(url),
                "fetched it",
                _write_tool_call("note.txt", "hello"),
                "wrote it",
            ]
        )
        input_stream = StringIO("fetch a page\ny\n/retry\ny\nexit\n")
        output_stream = StringIO()
        config = runtime_config.load()

        run_repl(config, input_stream=input_stream, output_stream=output_stream)

        retry_section = output_stream.getvalue().split("write: note.txt")[-1]
        assert "Warning: this turn fetched" not in retry_section
    finally:
        httpd.shutdown()
        thread.join()


def test_repl_shows_both_the_dangerous_command_and_fetched_content_lines_after_a_webfetch(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import registry as tools_registry, workspace

    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    httpd, thread = _run_one_route_server()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/page"
        install_fake_urlopen([_webfetch_tool_call(url), _shell_tool_call("eval touch marker.txt"), "not running it"])
        input_stream = StringIO("fetch then run\ny\ny\nexit\n")
        output_stream = StringIO()
        config = runtime_config.load()

        run_repl(config, input_stream=input_stream, output_stream=output_stream)

        output = output_stream.getvalue()
        assert "Dangerous command: eval" in output
        assert f"Warning: this turn fetched {url}." in output
        assert "error: change rejected by the user" in output
        assert not (tmp_path / "marker.txt").exists()
    finally:
        httpd.shutdown()
        thread.join()


def test_repl_approves_a_dangerous_command_with_yes_after_a_webfetch_warning(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import registry as tools_registry, workspace

    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    httpd, thread = _run_one_route_server()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/page"
        install_fake_urlopen([_webfetch_tool_call(url), _shell_tool_call("eval touch marker.txt"), "ran it"])
        input_stream = StringIO("fetch then run\ny\nyes\nexit\n")
        output_stream = StringIO()
        config = runtime_config.load()

        run_repl(config, input_stream=input_stream, output_stream=output_stream)

        assert (tmp_path / "marker.txt").exists()
    finally:
        httpd.shutdown()
        thread.join()


# --- shell timeout and output cap (ticket 0018-02) --------------------------


def test_repl_writes_the_call_log_entry_and_live_tool_line_for_a_timed_out_shell_call(
    route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import registry as tools_registry, shell as shell_tool, workspace

    workspace.configure_workspace(tmp_path)
    tools_registry.enable_shell_tool()
    shell_tool.configure_shell("1", None, 1024)
    install_fake_urlopen([_shell_tool_call("sleep 5"), "gave up"])
    input_stream = StringIO("run a slow command\ny\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert 'tool> shell(command="sleep 5") -> error: command timed out after 1 seconds' in output
    assert "llm> gave up\n" in output

    entries = _session_lines()
    tool_entries = [entry for entry in entries if entry["type"] == "tool_execution"]
    assert [entry["name"] for entry in tool_entries] == ["shell"]
    assert tool_entries[0]["ok"] is False
    assert "command timed out after 1 seconds" in tool_entries[0]["error"]
    assert "background: true" in tool_entries[0]["error"]


class _TTYOutputStream(StringIO):
    def isatty(self):
        return True


def test_repl_colors_error_line_on_an_interactive_terminal(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    install_fake_urlopen([ValueError("bad request")])
    input_stream = StringIO("summarize this line\nexit\n")
    output_stream = _TTYOutputStream()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "\033[31mError: ValueError: bad request\033[0m\n" in output


def test_repl_colors_routing_line_and_llm_prefix_on_success_on_an_interactive_terminal(
    route_env, install_fake_urlopen, monkeypatch
):
    monkeypatch.delenv("NO_COLOR", raising=False)
    install_fake_urlopen(["# Title\n\nthe **answer** at [docs](https://example.com)"])
    input_stream = StringIO("summarize this line\nexit\n")
    output_stream = _TTYOutputStream()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "\033[36m[openrouter] vendor/test-model\033[0m\n" in output
    assert "llm>\n" in output
    assert "Title" in output and "answer" in output
    assert "**answer**" not in output and "# Title" not in output
    assert "\033[1manswer\033[0m" in output
    assert "https://example.com" in output and "\033]8;" not in output


def test_repl_history_colors_tool_call_and_tool_result_lines_on_an_interactive_terminal(
    route_env, install_fake_urlopen, monkeypatch
):
    monkeypatch.delenv("NO_COLOR", raising=False)
    install_fake_urlopen(
        [
            {"tool_calls": [{"id": "call_1", "name": "calculator", "arguments": {"expression": "2+2"}}]},
            "It is 4.",
        ]
    )
    input_stream = StringIO("what is 2+2?\n/history\nexit\n")
    output_stream = _TTYOutputStream()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "\033[33mtool_call: calculator({'expression': '2+2'}) id=call_1\033[0m" in output
    assert "\033[33mtool_result: calculator [ok] {'result': 4} id=call_1\033[0m" in output


def test_repl_no_color_disables_color_even_when_output_stream_is_a_tty(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    install_fake_urlopen(["the answer"])
    input_stream = StringIO("summarize this line\nexit\n")
    output_stream = _TTYOutputStream()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "\033[" not in output
    assert "[openrouter] vendor/test-model\n" in output
    assert "llm> the answer\n" in output


def test_repl_no_ansi_codes_when_output_stream_is_not_a_tty(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    install_fake_urlopen(["the answer"])
    input_stream = StringIO("summarize this line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "\033[" not in output
    assert "[openrouter] vendor/test-model\n" in output
    assert "llm> the answer\n" in output


def test_repl_prints_tool_line_before_the_answer_uncolored_in_piped_mode(route_env, install_fake_urlopen):
    install_fake_urlopen(
        [
            {
                "content": "Let me compute that.",
                "tool_calls": [{"id": "call_1", "name": "calculator", "arguments": {"expression": "2+2"}}],
            },
            "It is 4.",
        ]
    )
    input_stream = StringIO("what is 2+2?\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert 'tool> calculator(expression="2+2") -> 4\n' in output
    assert "\033[" not in output
    assert output.count("llm> Let me compute that.\n") == 1
    assert output.index("llm> Let me compute that.") < output.index("tool> calculator")
    assert output.index("tool> calculator") < output.index("llm> It is 4.")


def test_repl_colors_the_tool_line_yellow_on_success_and_red_on_error_on_an_interactive_terminal(
    route_env, install_fake_urlopen, monkeypatch
):
    monkeypatch.delenv("NO_COLOR", raising=False)
    install_fake_urlopen(
        [
            {
                "tool_calls": [
                    {"id": "call_1", "name": "calculator", "arguments": {"expression": "2+2"}},
                    {"id": "call_2", "name": "not_a_tool", "arguments": {}},
                ]
            },
            "It is 4.",
        ]
    )
    input_stream = StringIO("what is 2+2?\nexit\n")
    output_stream = _TTYOutputStream()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert '\033[33mtool> calculator(expression="2+2") -> 4\033[0m' in output
    assert "\033[31mtool> not_a_tool(" in output
    assert "Let me compute" not in output


def test_repl_history_retains_intermediate_streamed_text(route_env, install_fake_urlopen):
    answers = [
        {
            "content": "Let me compute that.",
            "tool_calls": [{"id": "call_1", "name": "calculator", "arguments": {"expression": "2+2"}}],
        },
        "It is 4.",
    ]
    config = runtime_config.load()

    install_fake_urlopen(answers)
    live_only_output = StringIO()
    run_repl(config, input_stream=StringIO("what is 2+2?\nexit\n"), output_stream=live_only_output)
    assert live_only_output.getvalue().count("llm> Let me compute that.\n") == 1

    call_log.reset_session()
    install_fake_urlopen(answers)
    with_history_output = StringIO()
    run_repl(config, input_stream=StringIO("what is 2+2?\n/history\nexit\n"), output_stream=with_history_output)
    assert "assistant: Let me compute that." in with_history_output.getvalue()


def test_repl_full_tool_turn_is_a_single_unit_at_the_twenty_turn_boundary(route_env, install_fake_urlopen):
    tool_call_answer = {"tool_calls": [{"id": "call_1", "name": "calculator", "arguments": {"expression": "1+1"}}]}
    plain_answers = [f"answer {n}" for n in range(2, 22)]
    calls = install_fake_urlopen([tool_call_answer, "tool turn done", *plain_answers, "answer 22"])
    lines = [f"task {n}" for n in range(1, 23)] + ["exit"]
    input_stream = StringIO("\n".join(lines) + "\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    assert len(calls) == 2 + 20 + 1
    last_body = json.loads(calls[-1]["request"].data)
    roles = [m["role"] for m in last_body["messages"]]
    assert "tool" in roles
    assert last_body["messages"][2]["tool_calls"][0]["id"] == "call_1"
    user_contents = [m["content"] for m in last_body["messages"] if m["role"] == "user"]
    assert user_contents[0] == "task 1"
    assert user_contents[-1] == "task 22"
    assert len(user_contents) == 22


# --- output sanitizing (R15) -----------------------------------------------


def test_repl_sanitizes_forged_control_chars_in_tool_and_answer_lines_in_piped_mode(route_env, install_fake_urlopen):
    install_fake_urlopen(
        [
            {
                "tool_calls": [
                    {"id": "call_1", "name": "calculator", "arguments_raw": "\x1b[2K\rllm> forged"},
                    {"id": "call_2", "name": "calc\x1b\x07ulator", "arguments": {}},
                ]
            },
            "answer\x1b\x07 done",
        ]
    )
    input_stream = StringIO("what is 2+2?\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "\x1b" not in output
    assert "\x07" not in output
    assert "\r" not in output
    assert "\\x1b" in output
    assert "\\x07" in output
    assert "\\x0d" in output


def test_repl_sanitizes_untrusted_control_chars_while_keeping_repl_own_color_codes(
    route_env, install_fake_urlopen, monkeypatch
):
    monkeypatch.delenv("NO_COLOR", raising=False)
    install_fake_urlopen(
        [
            {"tool_calls": [{"id": "call_1", "name": "calculator", "arguments_raw": "\x1b[2K\rllm> forged"}]},
            "answer\x1b\x07 done",
        ]
    )
    input_stream = StringIO("what is 2+2?\nexit\n")
    output_stream = _TTYOutputStream()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "\033[36m[openrouter]" in output
    assert "llm> " in output
    assert "\x1b[2K\rllm> forged" not in output
    assert "\\x1b" in output
    assert "\\x07" in output


def test_history_command_sanitizes_control_characters_in_tool_calls_and_results(route_env, install_fake_urlopen):
    install_fake_urlopen(
        [
            {
                "tool_calls": [
                    {
                        "id": "call_1\x1b[2K\rllm> forged",
                        "name": "calc\x1bulator",
                        "arguments": {"expression": "2+2\x07"},
                    },
                    {"id": "call_2", "name": "calculator", "arguments_raw": "\x1b[2K\rllm> forged"},
                ]
            },
            "answer\x1b done",
        ]
    )
    input_stream = StringIO("what is 2+2?\n/history\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    history_section = output.split("llm> answer\\x1b done\n", 1)[-1]
    assert "\x1b" not in history_section
    assert "\x07" not in history_section
    assert "\r" not in history_section
    assert "\\x1b" in history_section
    assert "\\x07" in history_section
    assert "\\x0d" in history_section


def test_repl_sanitizes_a_control_character_in_the_error_line_in_piped_mode(route_env, install_fake_urlopen):
    install_fake_urlopen([ValueError("bad\x1brequest")])
    input_stream = StringIO("summarize this line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "\x1b" not in output
    assert "\\x1b" in output
    assert "Error:" in output


# --- resume (log_version 2) -------------------------------------------


def test_resumed_repl_prints_resumed_line_before_first_input_with_restored_turn_count(
    route_env, install_fake_urlopen
):
    install_fake_urlopen(["first answer"])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("summarize this line\nexit\n"),
        output_stream=StringIO(),
    )
    session_id = call_log.current_session_id()

    call_log.reset_session()
    resumed = (session_id, *call_log.load_conversation(session_id))
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("exit\n"),
        output_stream=output_stream,
        resumed=resumed,
    )

    output = output_stream.getvalue()
    assert output.startswith(f"Resumed session {session_id}: 1 turns.\n")


def _build_resumable_session(input_line, answer, route_env, install_fake_urlopen):
    install_fake_urlopen([answer])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO(f"{input_line}\nexit\n"),
        output_stream=StringIO(),
    )
    session_id = call_log.current_session_id()
    call_log.reset_session()
    return session_id, call_log.load_conversation(session_id)[0]


def test_resumed_repl_history_shows_the_restored_turns(route_env, install_fake_urlopen):
    session_id, turns = _build_resumable_session(
        "summarize this line", "first answer", route_env, install_fake_urlopen
    )
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/history\nexit\n"),
        output_stream=output_stream,
        resumed=(session_id, turns, None, [], call_log.load_conversation(session_id)[3]),
    )

    history_section = output_stream.getvalue().split("/history")[-1]
    assert "user: summarize this line" in history_section
    assert "assistant: first answer" in history_section


def test_resumed_repl_writes_session_resumed_then_appends_this_runs_entries_and_session_end(
    route_env, install_fake_urlopen
):
    session_id, turns = _build_resumable_session(
        "summarize this line", "first answer", route_env, install_fake_urlopen
    )
    first_run_line_count = len(Path(call_log.session_log_path(session_id)).read_text().splitlines())
    install_fake_urlopen([])
    config = runtime_config.load()

    run_repl(config, input_stream=StringIO("exit\n"), output_stream=StringIO(),
             resumed=(session_id, turns, None, [], call_log.load_conversation(session_id)[3]))

    lines = [json.loads(line) for line in Path(call_log.session_log_path(session_id)).read_text().splitlines()]
    assert len(lines) == first_run_line_count + 4
    resumed_entry = lines[first_run_line_count]
    assert resumed_entry["type"] == "session_resumed"
    assert resumed_entry["session_id"] == session_id
    assert set(resumed_entry) == {"timestamp", "session_id", "type", "provider", "model", "log_version", "workspace_root", "project_id", "run_id",
                                  "access_method"}
    assert (resumed_entry["log_version"], resumed_entry["provider"], resumed_entry["model"]) == (
        3, "openrouter", "vendor/test-model")
    assert lines[-1]["type"] == "session_end"
    assert lines[-1]["session_id"] == session_id
    assert call_log.session_log_path() == call_log.session_log_path(session_id)


def test_resumed_repl_spend_resets_to_zero_for_the_new_run(route_env, install_fake_urlopen):
    install_fake_urlopen([{"content": "first answer", "usage": {"cost": 0.6}}])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("summarize this line\nexit\n"),
        output_stream=StringIO(),
    )
    session_id = call_log.current_session_id()
    call_log.reset_session()
    turns, _, _, _ = call_log.load_conversation(session_id)
    install_fake_urlopen([])

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("exit\n"),
        output_stream=StringIO(),
        resumed=(session_id, turns, None, [], call_log.load_conversation(session_id)[3]),
    )

    lines = [json.loads(line) for line in Path(call_log.session_log_path(session_id)).read_text().splitlines()]
    assert lines[-1]["total_cost"] == 0.0


def test_resumed_repl_sends_restored_turns_to_the_provider_on_the_next_task(route_env, install_fake_urlopen):
    session_id, turns = _build_resumable_session(
        "summarize this line", "first answer", route_env, install_fake_urlopen
    )
    calls = install_fake_urlopen(["second answer"])

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("summarize this other line\nexit\n"),
        output_stream=StringIO(),
        resumed=(session_id, turns, None, [], call_log.load_conversation(session_id)[3]),
    )

    assert len(calls) == 1
    body = json.loads(calls[0]["request"].data)
    sent_contents = [m["content"] for m in body["messages"] if m["role"] != "system"]
    assert sent_contents == ["summarize this line", "first answer", "summarize this other line"]


def test_resumed_conversation_excludes_error_and_interrupted_turns(route_env, install_fake_urlopen):
    install_fake_urlopen(["first answer", ValueError("bad request"), KeyboardInterrupt()])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO(
            "summarize this line\nsummarize this other line\nsummarize a third line\nexit\n"
        ),
        output_stream=StringIO(),
    )
    session_id = call_log.current_session_id()
    call_log.reset_session()
    turns, _, _, _ = call_log.load_conversation(session_id)
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/history\nexit\n"),
        output_stream=output_stream,
        resumed=(session_id, turns, None, [], call_log.load_conversation(session_id)[3]),
    )

    output = output_stream.getvalue()
    assert output.startswith(f"Resumed session {session_id}: 1 turns.\n")
    history_section = output.split("/history")[-1]
    assert "first answer" in history_section
    assert "bad request" not in history_section
    assert "summarize this other line" not in history_section
    assert "summarize a third line" not in history_section


def test_resumed_conversation_drops_turns_before_the_last_clear(route_env, install_fake_urlopen):
    install_fake_urlopen(["first answer", "second answer"])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("summarize this line\n/clear\nsummarize this other line\nexit\n"),
        output_stream=StringIO(),
    )
    session_id = call_log.current_session_id()
    call_log.reset_session()
    turns, _, _, _ = call_log.load_conversation(session_id)
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/history\nexit\n"),
        output_stream=output_stream,
        resumed=(session_id, turns, None, [], call_log.load_conversation(session_id)[3]),
    )

    output = output_stream.getvalue()
    assert output.startswith(f"Resumed session {session_id}: 1 turns.\n")
    history_section = output.split("/history")[-1]
    assert "summarize this other line" in history_section
    assert "second answer" in history_section
    assert "summarize this line" not in history_section
    assert "first answer" not in history_section


def test_a_resumed_session_can_be_resumed_again_with_the_newer_turns(route_env, install_fake_urlopen):
    session_id, turns = _build_resumable_session(
        "summarize this line", "first answer", route_env, install_fake_urlopen
    )
    install_fake_urlopen(["second answer"])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("summarize this other line\nexit\n"),
        output_stream=StringIO(),
        resumed=(session_id, turns, None, [], call_log.load_conversation(session_id)[3]),
    )
    call_log.reset_session()

    second_turns, _, _, _ = call_log.load_conversation(session_id)

    assert len(second_turns) == 2
    assert second_turns[0] == (
        {"role": "user", "content": "summarize this line"},
        {"role": "assistant", "content": "first answer"},
    )
    assert second_turns[1] == (
        {"role": "user", "content": "summarize this other line"},
        {"role": "assistant", "content": "second answer"},
    )


def test_repl_skips_textless_stream_and_continues(route_env, install_fake_urlopen):
    install_fake_urlopen([{"content": None}, "second answer"])
    input_stream = StringIO("summarize this line\nsummarize this other line\nexit\n")
    output_stream = StringIO()
    config = runtime_config.load()

    run_repl(config, input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "llm> None\n" not in output
    assert "llm> second answer\n" in output


# --- /compress ---------------------------------------------------------------

THREE_TURNS = "refactor task one\nrefactor task two\nrefactor task three\n"


def _body(call):
    return json.loads(call["request"].data)


def _system_prompt(call):
    return _body(call)["messages"][0]["content"]


def _non_system_messages(call):
    return _body(call)["messages"][1:]


def test_compress_with_two_or_fewer_turns_reports_error_and_calls_nothing(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/compress\nrefactor task one\nrefactor task two\n/compress\nexit\n"),
        output_stream=output_stream,
    )

    assert len(calls) == 2
    assert output_stream.getvalue().count("Error: nothing to compress") == 2
    assert "conversation_compressed" not in [entry["type"] for entry in _session_lines()]


def test_compress_summarizes_older_turns_with_the_configured_pair_and_keeps_the_two_most_recent(
    route_env, install_fake_urlopen
):
    calls = install_fake_urlopen(
        [
            {"tool_calls": [{"id": "call_1", "name": "calculator", "arguments": {"expression": "2+2"}}]},
            "a1",
            "a2",
            "a3",
            {"content": "THE SUMMARY", "usage": {"cost": 0.25}},
        ]
    )
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\n/history\nexit\n"),
        output_stream=output_stream,
    )

    assert len(calls) == 5
    summary_call = calls[4]
    body = _body(summary_call)
    assert body["model"] == "vendor/test-model"
    assert "tools" not in body
    messages = _non_system_messages(summary_call)
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    text = messages[0]["content"]
    assert "refactor task one" in text
    assert "calculator" in text
    assert "a1" in text
    assert "refactor task two" not in text
    assert "refactor task three" not in text
    assert "Conversation Summary" not in _system_prompt(summary_call)

    output = output_stream.getvalue()
    assert "Compressed 1 turn.\n" in output
    history = output.split("Compressed 1 turn.\n")[-1]
    assert history.index("summary: THE SUMMARY") < history.index("user: refactor task two")
    assert "refactor task one" not in history
    assert "user: refactor task three" in history

    lines = _session_lines()
    types = [entry["type"] for entry in lines]
    assert types[-3:] == ["attempt", "conversation_compressed", "session_end"]
    attempt = lines[-3]
    assert attempt["task"] == "/compress"
    assert "tier" not in attempt
    assert attempt["model"] == "vendor/test-model"
    compressed = lines[-2]
    assert set(compressed) == {"timestamp", "session_id", "type", "summary"}
    assert compressed["summary"] == "THE SUMMARY"
    assert types.count("turn_end") == 3
    assert lines[-1]["total_cost"] == pytest.approx(0.25)


def test_compress_summary_call_system_prompt_omits_tool_rules(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", "THE SUMMARY"])

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\nexit\n"),
        output_stream=StringIO(),
    )

    system_content = _system_prompt(calls[3])
    assert "calculator" not in system_content
    assert "Tool" not in system_content
    assert "helpful assistant" in system_content
    assert "language" in system_content


def test_compress_includes_turns_beyond_the_context_window(route_env, install_fake_urlopen, monkeypatch):
    calls = install_fake_urlopen(["a1", "a2", "a3", "a4", "S"])

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "refactor task four\n/compress\nexit\n"),
        output_stream=StringIO(),
    )

    text = _non_system_messages(calls[4])[0]["content"]
    assert "refactor task one" in text
    assert "refactor task two" in text


def test_later_exchanges_carry_the_summary_in_the_system_prompt_never_as_a_message(
    route_env, install_fake_urlopen, monkeypatch
):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    calls = install_fake_urlopen(
        [
            "a1",
            "a2",
            "a3",
            "THE SUMMARY",
            {"tool_calls": [{"id": "call_1", "name": "calculator", "arguments": {"expression": "2+2"}}]},
            "It is 4.",
            _http_error(503),
            _http_error(503),
            _http_error(503),
        ]
    )

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\nwhat is 2+2?\nsummarize this line\nexit\n"),
        output_stream=StringIO(),
    )

    assert len(calls) == 9
    for call in calls[:4]:
        assert "THE SUMMARY" not in _system_prompt(call)
    for call in calls[4:]:
        assert "THE SUMMARY" in _system_prompt(call)
        assert all("THE SUMMARY" not in json.dumps(m) for m in _non_system_messages(call))
    assert _body(calls[8])["model"] == "vendor/test-model"
    user_messages = [m["content"] for m in _non_system_messages(calls[4]) if m["role"] == "user"]
    assert user_messages == ["refactor task two", "refactor task three", "what is 2+2?"]


def test_compress_failure_leaves_conversation_unchanged_and_writes_no_entry(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", ValueError("bad request"), "a4"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\n/history\nrefactor task four\nexit\n"),
        output_stream=output_stream,
    )

    output = output_stream.getvalue()
    assert "Error: ValueError: bad request" in output
    history = output.split("bad request")[-1]
    assert "summary:" not in history
    assert "user: refactor task one" in history
    types = [entry["type"] for entry in _session_lines()]
    assert "conversation_compressed" not in types
    assert types.count("turn_end") == 4
    assert "Conversation Summary" not in _system_prompt(calls[4])
    assert len([m for m in _non_system_messages(calls[4]) if m["role"] == "user"]) == 4


def test_compress_empty_answer_is_an_error(route_env, install_fake_urlopen):
    install_fake_urlopen(["a1", "a2", "a3", "  "])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\nexit\n"),
        output_stream=output_stream,
    )

    assert "Error: " in output_stream.getvalue()
    assert "Compressed" not in output_stream.getvalue()
    assert "conversation_compressed" not in [entry["type"] for entry in _session_lines()]


def test_compress_retries_locally_and_never_escalates(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    calls = install_fake_urlopen(["a1", "a2", "a3", _http_error(503), "S"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\nexit\n"),
        output_stream=output_stream,
    )

    assert "Compressed 1 turn.\n" in output_stream.getvalue()
    attempts = [entry for entry in _session_lines() if entry.get("task") == "/compress"]
    assert [entry["attempt"] for entry in attempts] == [1, 2]
    assert [entry["ok"] for entry in attempts] == [False, True]


def test_compress_exhausted_retries_do_not_escalate(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    calls = install_fake_urlopen(["a1", "a2", "a3", Repeat(_http_error(503))])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\nexit\n"),
        output_stream=output_stream,
    )

    assert len(calls) == 6
    assert all(_body(call)["model"] == "vendor/test-model" for call in calls[3:])
    assert "Error: " in output_stream.getvalue()
    types = [entry["type"] for entry in _session_lines()]
    assert types.count("turn_end") == 3


def test_compress_cost_counts_toward_run_spend(route_env, install_fake_urlopen):
    install_fake_urlopen(["a1", "a2", "a3", {"content": "S", "usage": {"cost": 0.4}}])

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\nexit\n"),
        output_stream=StringIO(),
    )

    assert call_log.total_cost() == pytest.approx(0.4)


def test_second_compress_folds_in_and_replaces_the_previous_summary(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", "FIRST SUMMARY", "a4", "SECOND SUMMARY", "a5"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(
            THREE_TURNS + "/compress\nrefactor task four\n/compress\n/history\nrefactor task five\nexit\n"
        ),
        output_stream=output_stream,
    )

    text = _non_system_messages(calls[5])[0]["content"]
    assert "FIRST SUMMARY" in text
    assert "refactor task two" in text
    assert "refactor task three" not in text
    history = output_stream.getvalue().split("Compressed 1 turn.\n")[-1]
    assert "summary: SECOND SUMMARY" in history
    assert "FIRST SUMMARY" not in history
    assert "SECOND SUMMARY" in _system_prompt(calls[6])
    assert "FIRST SUMMARY" not in _system_prompt(calls[6])


def test_history_with_only_a_summary_prints_only_the_summary_line(route_env, install_fake_urlopen):
    install_fake_urlopen(["a1", "a2", "a3", "S\x1b[31mX"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\n/undo\n/undo\n/undo\n/history\nexit\n"),
        output_stream=output_stream,
    )

    output = output_stream.getvalue()
    assert output.count("Turn undone.\n") == 2
    assert "Error: no turn to undo.\n" in output
    history = output.split("Error: no turn to undo.\n")[-1]
    assert history.startswith("summary: S")
    assert "\x1b" not in history
    assert "user:" not in history
    assert "No completed turns yet." not in history


def test_undo_after_compress_removes_the_newest_kept_turn_not_the_summary(route_env, install_fake_urlopen):
    install_fake_urlopen(["a1", "a2", "a3", "S"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\n/undo\n/history\nexit\n"),
        output_stream=output_stream,
    )

    history = output_stream.getvalue().split("Turn undone.\n")[-1]
    assert "summary: S" in history
    assert "user: refactor task two" in history
    assert "refactor task three" not in history


def test_clear_drops_the_summary_too(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", "THE SUMMARY", "a4"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\n/clear\n/history\nrefactor task four\nexit\n"),
        output_stream=output_stream,
    )

    history = output_stream.getvalue().split("Conversation cleared.\n")[-1]
    assert "No completed turns yet." in history
    assert "THE SUMMARY" not in _system_prompt(calls[4])


def test_retry_after_compress_still_undoes_the_kept_last_turn(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", "S", "a3 again"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\n/retry\n/history\nexit\n"),
        output_stream=output_stream,
    )

    types = [entry["type"] for entry in _session_lines()]
    assert types[-6:] == ["conversation_compressed", "turn_undone", "routed_task_retried", "attempt", "turn_end", "session_end"]
    user_messages = [m["content"] for m in _non_system_messages(calls[4]) if m["role"] == "user"]
    assert user_messages == ["refactor task two", "refactor task three"]
    history = output_stream.getvalue().split("llm> a3 again\n")[-1]
    assert history.count("user: refactor task three") == 1
    assert "summary: S" in history


def test_resume_replays_compression_and_carries_the_summary(route_env, install_fake_urlopen):
    install_fake_urlopen(["a1", "a2", "a3", "THE SUMMARY", "a4"])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\nrefactor task four\nexit\n"),
        output_stream=StringIO(),
    )
    session_id = call_log.current_session_id()
    call_log.reset_session()
    turns, summary, _, _ = call_log.load_conversation(session_id)
    calls = install_fake_urlopen(["a5"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/history\nrefactor task five\nexit\n"),
        output_stream=output_stream,
        resumed=(session_id, turns, summary, [], call_log.load_conversation(session_id)[3]),
    )

    output = output_stream.getvalue()
    assert output.startswith(f"Resumed session {session_id}: 3 turns.\n")
    history = output.split("3 turns.\n")[-1]
    assert history.index("summary: THE SUMMARY") < history.index("user: refactor task two")
    assert "refactor task one" not in history
    assert "THE SUMMARY" in _system_prompt(calls[0])
    user_messages = [m["content"] for m in _non_system_messages(calls[0]) if m["role"] == "user"]
    assert user_messages == ["refactor task two", "refactor task three", "refactor task four", "refactor task five"]


def test_resume_replays_undo_after_compress_and_clear_after_compress(route_env, install_fake_urlopen):
    install_fake_urlopen(["a1", "a2", "a3", "S1"])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\n/undo\nexit\n"),
        output_stream=StringIO(),
    )
    session_id = call_log.current_session_id()
    call_log.reset_session()

    turns, summary, _, _ = call_log.load_conversation(session_id)

    assert summary == "S1"
    assert [turn[0]["content"] for turn in turns] == ["refactor task two"]

    install_fake_urlopen([])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/clear\nexit\n"),
        output_stream=StringIO(),
        resumed=(session_id, turns, summary, [], call_log.load_conversation(session_id)[3]),
    )
    call_log.reset_session()

    assert call_log.load_conversation(session_id)[:3] == ((), None, [])


def test_ctrl_c_during_compress_keeps_the_conversation_and_the_session(route_env, install_fake_urlopen):
    install_fake_urlopen(["a1", "a2", "a3", KeyboardInterrupt(), "a4"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/compress\nrefactor task four\nexit\n"),
        output_stream=output_stream,
    )

    assert "Error: Interrupted." in output_stream.getvalue()
    assert "llm> a4\n" in output_stream.getvalue()
    lines = _session_lines()
    assert "conversation_compressed" not in [entry["type"] for entry in lines]
    assert lines[-1]["reason"] == "exit_command"


# --- Auto-Compress -------------------------------------------------------

# The `cost` module's fallback Context Limit for a model litellm does not
# recognise (128_000, see cost.DEFAULT_CONTEXT_LIMIT); "vendor/*-model" is
# unknown under any lookup name, so every model in these tests uses it.
# AUTO_COMPRESS_THRESHOLD (0.8) makes 102400 the crossing point.
CROSSING_USAGE = {"prompt_tokens": 102401, "completion_tokens": 1}
CONTINUATION_TEXT = (
    "Continue with the task if there are next steps. If anything is unclear, ask me instead of guessing."
)



def test_reported_usage_never_triggers_post_success_compression_or_continuation(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", {"content": "a4", "usage": CROSSING_USAGE}])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(THREE_TURNS + "refactor task four\n/history\nexit\n"),
             output_stream=output)
    assert len(calls) == 4
    assert "Compressed" not in output.getvalue() and "Continue with the task" not in output.getvalue()
    assert "user: refactor task one" in output.getvalue()
    assert [entry["type"] for entry in _session_lines()].count("turn_end") == 4


def test_auto_compress_does_not_fire_at_or_below_the_threshold(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(
        ["a1", "a2", "a3", {"content": "a4", "usage": {"prompt_tokens": 102400, "completion_tokens": 1}}]
    )
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "refactor task four\nexit\n"),
        output_stream=output_stream,
    )

    assert len(calls) == 4
    assert "Compressed" not in output_stream.getvalue()
    assert "conversation_compressed" not in [entry["type"] for entry in _session_lines()]


def test_auto_compress_never_fires_when_prompt_tokens_is_none(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", "a4"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "refactor task four\nexit\n"),
        output_stream=output_stream,
    )

    assert len(calls) == 4
    assert "Compressed" not in output_stream.getvalue()
    assert "conversation_compressed" not in [entry["type"] for entry in _session_lines()]


def test_auto_compress_with_two_or_fewer_turns_is_a_silent_skip(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", {"content": "a2", "usage": CROSSING_USAGE}])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("refactor task one\nrefactor task two\nexit\n"),
        output_stream=output_stream,
    )

    assert len(calls) == 2
    assert "Compressed" not in output_stream.getvalue()
    assert "Error" not in output_stream.getvalue()
    assert "conversation_compressed" not in [entry["type"] for entry in _session_lines()]



def test_manual_compression_failure_after_high_usage_keeps_history_and_sends_no_continuation(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", {"content": "a4", "usage": CROSSING_USAGE}, ValueError("bad request")])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(THREE_TURNS + "refactor task four\n/compress\n/history\nexit\n"),
             output_stream=output)
    assert len(calls) == 5
    assert "Error: ValueError: bad request" in output.getvalue()
    assert "continuing automatically" not in output.getvalue()
    assert "user: refactor task one" in output.getvalue()
    entries = _session_lines()
    assert not any(entry["type"] == "conversation_compressed" for entry in entries)
    assert [entry["type"] for entry in entries].count("turn_end") == 4



def test_retry_does_not_start_post_success_compression(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", {"content": "a3 retried", "usage": CROSSING_USAGE}])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(THREE_TURNS + "/retry\nexit\n"), output_stream=output)
    assert len(calls) == 4
    assert _non_system_messages(calls[-1])[-1]["content"] == "refactor task three"
    assert "Compressed" not in output.getvalue()



def test_high_usage_after_retry_does_not_invent_a_pinned_continuation(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    calls = install_fake_urlopen(["a1", "a2", _http_error(503), _http_error(503),
                                 {"content": "retried crossing answer", "usage": CROSSING_USAGE}])
    run_repl(runtime_config.load(), input_stream=StringIO(
        "summarize task alpha\nsummarize task beta\nplease refactor this module\nexit\n"),
        output_stream=StringIO())
    assert len(calls) == 5
    assert _body(calls[-1])["model"] == "vendor/test-model"



def test_manual_compression_after_high_usage_never_routes_a_continuation(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", {"content": "a4", "usage": CROSSING_USAGE},
                                 {"content": "THE SUMMARY", "usage": CROSSING_USAGE}])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(THREE_TURNS + "refactor task four\n/compress\nexit\n"),
             output_stream=output)
    assert len(calls) == 5
    assert "Compressed 2 turns." in output.getvalue()
    assert "continuing automatically" not in output.getvalue()
    assert [entry["type"] for entry in _session_lines()].count("turn_end") == 4



def test_undo_after_high_usage_removes_the_ordinary_turn(route_env, install_fake_urlopen):
    install_fake_urlopen(["a1", "a2", "a3", {"content": "a4", "usage": CROSSING_USAGE}])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(THREE_TURNS + "refactor task four\n/undo\n/history\nexit\n"),
             output_stream=output)
    history = output.getvalue().split("Turn undone.\n")[-1]
    assert "Continue with the task" not in history
    assert "user: refactor task four" not in history
    assert "user: refactor task three" in history



def test_high_usage_keeps_the_ordinary_task_as_retry_target(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", {"content": "a4", "usage": CROSSING_USAGE}, "retried answer"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(THREE_TURNS + "refactor task four\n/usage\n/retry\nexit\n"),
             output_stream=output)
    assert len(calls) == 5
    assert _non_system_messages(calls[-1])[-1]["content"] == "refactor task four"
    assert "route: openrouter vendor/test-model" in output.getvalue()



def test_resume_after_high_usage_replays_all_ordinary_turns(route_env, install_fake_urlopen):
    install_fake_urlopen(["a1", "a2", "a3", {"content": "a4", "usage": CROSSING_USAGE}])
    run_repl(runtime_config.load(), input_stream=StringIO(THREE_TURNS + "refactor task four\nexit\n"), output_stream=StringIO())
    session_id = call_log.current_session_id()
    call_log.reset_session()
    turns, summary, todos, _ = call_log.load_conversation(session_id)
    assert summary is None
    assert [turn[0]["content"] for turn in turns] == [f"refactor task {name}" for name in ("one", "two", "three", "four")]
    calls = install_fake_urlopen(["a5"])
    run_repl(runtime_config.load(), input_stream=StringIO("summarize this line\nexit\n"), output_stream=StringIO(),
             resumed=(session_id, turns, summary, todos, call_log.load_conversation(session_id)[3]))
    users = [m["content"] for m in _non_system_messages(calls[0]) if m["role"] == "user"]
    assert users[-2] == "refactor task four" and len(users) == 5


def _memory_lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def test_remember_confirms_appends_the_file_and_injects_the_next_system_prompt(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["the answer"])
    output_stream = StringIO()
    memory_path = memory.resolve_path()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember always answer in metric units\nsummarize this line\nexit\n"),
        output_stream=output_stream,
    )

    output = output_stream.getvalue()
    assert "Remembered.\n" in output
    notes = _memory_lines(memory_path)
    assert len(notes) == 1
    assert notes[0]["text"] == "always answer in metric units"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", notes[0]["added"])
    system_content = json.loads(calls[0]["request"].data)["messages"][0]["content"]
    assert "Facts the user asked to be remembered:\n- always answer in metric units" in system_content
    assert system_content.startswith("You are a helpful assistant.")
    assert system_content.index("Answer in the language") < system_content.index("always answer in metric units")


def test_remember_with_no_text_is_a_local_error_and_writes_nothing(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()
    memory_path = memory.resolve_path()

    run_repl(runtime_config.load(), input_stream=StringIO("/remember\nexit\n"), output_stream=output_stream)

    assert "Error: /remember needs text" in output_stream.getvalue()
    assert not Path(memory_path).exists()


def test_remember_with_only_whitespace_is_a_local_error_and_writes_nothing(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()
    memory_path = memory.resolve_path()

    run_repl(runtime_config.load(), input_stream=StringIO("/remember    \nexit\n"), output_stream=output_stream)

    assert "Error: /remember needs text" in output_stream.getvalue()
    assert not Path(memory_path).exists()


def test_remember_collapses_line_breaks_but_keeps_other_internal_spacing(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()
    memory_path = memory.resolve_path()

    run_repl(
        runtime_config.load(),
        input_stream=["/remember first  line\nsecond line\n\nthird line", "exit"],
        output_stream=output_stream,
    )

    notes = _memory_lines(memory_path)
    assert notes[0]["text"] == "first  line second line third line"


def test_remember_takes_the_whole_line_not_whitespace_split_args(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()
    memory_path = memory.resolve_path()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember   my  main project is X  \nexit\n"),
        output_stream=output_stream,
    )

    notes = _memory_lines(memory_path)
    assert notes[0]["text"] == "my  main project is X"


def test_remember_write_failure_is_a_local_error_and_leaves_memory_unchanged(route_env, install_fake_urlopen, monkeypatch):
    install_fake_urlopen(["the answer"])
    output_stream = StringIO()

    def _raise(text, path=None):
        raise OSError("permission denied")

    monkeypatch.setattr(memory, "remember", _raise)

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember a fact\nsummarize this line\nexit\n"),
        output_stream=output_stream,
    )

    assert "Error: could not save to memory" in output_stream.getvalue()
    assert not Path(memory.resolve_path()).exists()


def test_remember_prints_one_warning_when_crossing_2000_characters_and_not_again(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()
    first_note = "x" * 1990
    second_note = "y" * 20
    third_note = "z" * 20

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(f"/remember {first_note}\n/remember {second_note}\n/remember {third_note}\nexit\n"),
        output_stream=output_stream,
    )

    output = output_stream.getvalue()
    assert output.count("Warning: Memory is now past about 2000 characters") == 1
    lines = output.splitlines()
    remembered_indexes = [i for i, line in enumerate(lines) if line == "Remembered."]
    warning_indexes = [i for i, line in enumerate(lines) if line.startswith("Warning: Memory")]
    assert warning_indexes == [remembered_indexes[1] + 1]


def test_remember_at_or_below_threshold_prints_no_warning(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(f"/remember {'x' * 2000}\nexit\n"),
        output_stream=output_stream,
    )

    assert "Warning" not in output_stream.getvalue()


def test_remember_warning_is_never_logged_and_startup_never_warns(route_env, install_fake_urlopen):
    memory.remember("x" * 2500)
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("exit\n"),
        output_stream=output_stream,
        memory_notes=memory.load(),
    )

    assert "Warning" not in output_stream.getvalue()
    types = [entry["type"] for entry in _session_lines()]
    assert types == ["session_start", "session_end"]


def test_remember_writes_no_call_log_entry(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember a fact worth keeping\nexit\n"),
        output_stream=output_stream,
    )

    types = [entry["type"] for entry in _session_lines()]
    assert types == ["session_start", "session_end"]


def test_clear_undo_and_compress_leave_memory_unchanged(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", "a4", "THE SUMMARY"])
    output_stream = StringIO()
    memory_path = memory.resolve_path()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(
            "/remember keep this fact\n"
            "refactor task one\nrefactor task two\nrefactor task three\n"
            "/clear\n"
            "refactor task one\nrefactor task two\nrefactor task three\n"
            "/undo\n"
            "/compress\n"
            "exit\n"
        ),
        output_stream=output_stream,
    )

    notes = _memory_lines(memory_path)
    assert notes == [{"text": "keep this fact", "added": notes[0]["added"]}]
    assert len(calls) >= 1
    last_system = json.loads(calls[-1]["request"].data)["messages"][0]["content"]
    assert "keep this fact" in last_system


def test_a_note_added_mid_run_reaches_the_next_turns_system_prompt(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("first task\n/remember a new fact\nsecond task\nexit\n"),
        output_stream=output_stream,
    )

    first_system = json.loads(calls[0]["request"].data)["messages"][0]["content"]
    second_system = json.loads(calls[1]["request"].data)["messages"][0]["content"]
    assert "a new fact" not in first_system
    assert "a new fact" in second_system


def test_note_added_mid_run_reaches_the_compress_system_prompt(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", "THE SUMMARY"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(THREE_TURNS + "/remember a compress-time fact\n/compress\nexit\n"),
        output_stream=output_stream,
    )

    compress_system = json.loads(calls[-1]["request"].data)["messages"][0]["content"]
    assert "a compress-time fact" in compress_system


def test_second_run_repl_against_the_same_memory_file_sees_the_notes(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember shared fact\nexit\n"),
        output_stream=StringIO(),
    )
    call_log.reset_session()

    calls = install_fake_urlopen(["fresh answer"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("summarize this line\nexit\n"),
        output_stream=output_stream,
        memory_notes=memory.load(),
    )

    system_content = json.loads(calls[0]["request"].data)["messages"][0]["content"]
    assert "shared fact" in system_content


def test_resumed_run_repl_against_the_same_memory_file_sees_the_notes(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember resumed fact\nexit\n"),
        output_stream=StringIO(),
    )
    session_id = call_log.current_session_id()
    call_log.reset_session()

    calls = install_fake_urlopen(["fresh answer"])
    output_stream = StringIO()
    resumed = (session_id, *call_log.load_conversation(session_id))

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("summarize this line\nexit\n"),
        output_stream=output_stream,
        resumed=resumed,
        memory_notes=memory.load(),
    )

    system_content = json.loads(calls[0]["request"].data)["messages"][0]["content"]
    assert "resumed fact" in system_content


# --- /memory and /forget --------------------------------------------------


def test_memory_with_no_notes_reports_none(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO("/memory\nexit\n"), output_stream=output_stream)

    assert "No Memory Notes.\n" in output_stream.getvalue()


def test_memory_lists_notes_with_1_based_index_in_stored_order(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember first fact\n/remember second fact\n/memory\nexit\n"),
        output_stream=output_stream,
    )

    output = output_stream.getvalue()
    assert "1. first fact\n" in output
    assert "2. second fact\n" in output


def test_memory_sanitizes_control_characters(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=["/remember a fact with a\x07bell", "/memory", "exit"],
        output_stream=output_stream,
    )

    assert "1. a fact with a\\x07bell\n" in output_stream.getvalue()


def test_memory_with_arguments_is_a_local_error(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO("/memory extra\nexit\n"), output_stream=output_stream)

    assert "Error: /memory takes no arguments.\n" in output_stream.getvalue()


def test_forget_removes_the_note_confirms_and_updates_the_file(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()
    memory_path = memory.resolve_path()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember first fact\n/remember second fact\n/forget 1\nexit\n"),
        output_stream=output_stream,
    )

    output = output_stream.getvalue()
    assert "Forgot: first fact\n" in output
    notes = _memory_lines(memory_path)
    assert [note["text"] for note in notes] == ["second fact"]


def test_forget_renumbers_the_memory_list(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(
            "/remember first fact\n/remember second fact\n/forget 1\n/memory\nexit\n"
        ),
        output_stream=output_stream,
    )

    assert "1. second fact\n" in output_stream.getvalue()


def test_forget_removed_note_is_gone_from_the_next_system_prompt(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["the answer"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember first fact\n/forget 1\nsummarize this line\nexit\n"),
        output_stream=output_stream,
    )

    system_content = json.loads(calls[0]["request"].data)["messages"][0]["content"]
    assert "first fact" not in system_content
    assert "Facts the user asked to be remembered" not in system_content


@pytest.mark.parametrize(
    "command",
    ["/forget", "/forget abc", "/forget 0", "/forget -1", "/forget 1 2", "/forget 1.5"],
)
def test_forget_with_an_invalid_argument_is_a_local_error_and_changes_nothing(
    route_env, install_fake_urlopen, command
):
    install_fake_urlopen([])
    output_stream = StringIO()
    memory_path = memory.resolve_path()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(f"/remember only fact\n{command}\nexit\n"),
        output_stream=output_stream,
    )

    assert "Error: /forget needs" in output_stream.getvalue()
    notes = _memory_lines(memory_path)
    assert [note["text"] for note in notes] == ["only fact"]


def test_forget_out_of_range_is_a_local_error_and_changes_nothing(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()
    memory_path = memory.resolve_path()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember only fact\n/forget 2\nexit\n"),
        output_stream=output_stream,
    )

    assert "Error: /forget needs one index from 1 to 1.\n" in output_stream.getvalue()
    notes = _memory_lines(memory_path)
    assert [note["text"] for note in notes] == ["only fact"]


def test_forget_with_no_notes_is_a_local_error(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO("/forget 1\nexit\n"), output_stream=output_stream)

    assert "Error: /forget needs an index, but there are no Memory Notes.\n" in output_stream.getvalue()


def test_forget_write_failure_is_a_local_error_and_leaves_memory_unchanged(
    route_env, install_fake_urlopen, monkeypatch
):
    install_fake_urlopen([])
    output_stream = StringIO()
    memory_path = memory.resolve_path()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember only fact\nexit\n"),
        output_stream=StringIO(),
    )

    def _raise(index, notes, path=None):
        raise OSError("permission denied")

    monkeypatch.setattr(memory, "forget", _raise)

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/forget 1\nexit\n"),
        output_stream=output_stream,
        memory_notes=memory.load(),
    )

    assert "Error: could not update memory" in output_stream.getvalue()
    notes = _memory_lines(memory_path)
    assert [note["text"] for note in notes] == ["only fact"]


def test_forget_uses_the_repls_view_even_if_the_file_changed_since_startup(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    memory_path = memory.resolve_path()
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember first fact\n/remember second fact\nexit\n"),
        output_stream=StringIO(),
    )
    call_log.reset_session()
    notes = memory.load()

    with open(memory_path, "w", encoding="utf-8") as memory_file:
        memory_file.write("not json at all\n")

    output_stream = StringIO()
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/forget 1\n/memory\nexit\n"),
        output_stream=output_stream,
        memory_notes=notes,
    )

    output = output_stream.getvalue()
    assert "Forgot: first fact\n" in output
    assert "1. second fact\n" in output
    remaining = _memory_lines(memory_path)
    assert [note["text"] for note in remaining] == ["second fact"]


def test_memory_and_forget_write_no_call_log_entry(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember a fact\n/memory\n/forget 1\nexit\n"),
        output_stream=output_stream,
    )

    types = [entry["type"] for entry in _session_lines()]
    assert types == ["session_start", "session_end"]


def test_forget_persists_to_a_later_run_repl_against_the_same_memory_file(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/remember first fact\n/remember second fact\n/forget 1\nexit\n"),
        output_stream=StringIO(),
    )
    call_log.reset_session()

    calls = install_fake_urlopen(["fresh answer"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("summarize this line\nexit\n"),
        output_stream=output_stream,
        memory_notes=memory.load(),
    )

    system_content = json.loads(calls[0]["request"].data)["messages"][0]["content"]
    assert "second fact" in system_content
    assert "first fact" not in system_content


# --- /usage -----------------------------------------------------------


def test_usage_before_any_completed_turn_is_a_local_message_and_makes_no_call(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO("/usage\nexit\n"), output_stream=output_stream)

    assert len(calls) == 0
    assert "No ordinary exchange assessed yet this Run.\n" in output_stream.getvalue()


def test_usage_after_a_successful_turn_reports_route_spend_tokens_and_turns(route_env, install_fake_urlopen):
    install_fake_urlopen([{"content": "the answer", "usage": {"prompt_tokens": 12, "completion_tokens": 5}}])
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO("summarize this line\n/usage\nexit\n"), output_stream=output_stream)

    output = output_stream.getvalue()
    assert "route: openrouter vendor/test-model\n" in output
    assert "tokens: 12 prompt, 5 completion\n" in output
    assert "turns: 1 retained, 0 sent\n" in output


def test_usage_reports_the_latest_turns_tokens_not_an_earlier_one(route_env, install_fake_urlopen):
    install_fake_urlopen(
        [
            {"content": "first answer", "usage": {"prompt_tokens": 12, "completion_tokens": 5}},
            {"content": "second answer", "usage": {"prompt_tokens": 30, "completion_tokens": 9}},
        ]
    )
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("summarize this line\nsummarize this other line\n/usage\nexit\n"),
        output_stream=output_stream,
    )

    output = output_stream.getvalue()
    assert "tokens: 30 prompt, 9 completion\n" in output
    assert "turns: 2 retained, 1 sent\n" in output


def test_usage_marks_spend_estimated_when_the_last_answer_used_an_estimating_provider(
    route_env, install_fake_urlopen, monkeypatch
):
    monkeypatch.setenv("PA_PROVIDER", "anthropic")
    monkeypatch.setenv("PA_MODEL", "claude-3-haiku-20240307")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    install_fake_urlopen([{"content": "the answer", "usage": {"prompt_tokens": 8, "completion_tokens": 3}}])
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO("summarize this line\n/usage\nexit\n"), output_stream=output_stream)

    assert "(estimated)" in output_stream.getvalue()


def test_usage_with_arguments_is_a_local_error(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO("/usage extra\nexit\n"), output_stream=output_stream)

    assert "Error: /usage takes no arguments.\n" in output_stream.getvalue()


# --- Todo List (R13-R18, ticket 0022-03) ------------------------------------


def _todo_call(todos, call_id="call_1"):
    return {"tool_calls": [{"id": call_id, "name": "todo", "arguments": {"todos": todos}}]}


def test_repl_prints_the_checklist_after_a_successful_todo_call(route_env, install_fake_urlopen):
    todos = [
        {"content": "step one", "status": "completed"},
        {"content": "step two", "status": "in_progress"},
        {"content": "step three", "status": "pending"},
        {"content": "step four", "status": "cancelled"},
    ]
    install_fake_urlopen([_todo_call(todos), "planned it"])
    input_stream = StringIO("plan the task\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    output = output_stream.getvalue()
    assert "tool> todo\n" in output
    assert "  [x] step one\n" in output
    assert "  [~] step two\n" in output
    assert "  [ ] step three\n" in output
    assert "  [-] step four\n" in output
    assert "llm> planned it\n" in output


def test_repl_prints_todo_empty_for_an_empty_list(route_env, install_fake_urlopen):
    install_fake_urlopen([_todo_call([]), "cleared"])
    input_stream = StringIO("clear the plan\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    assert "tool> todo (empty)\n" in output_stream.getvalue()


def test_repl_carries_the_todo_list_into_the_next_tasks_system_prompt(route_env, install_fake_urlopen):
    todos = [{"content": "step one", "status": "in_progress"}]
    calls = install_fake_urlopen([_todo_call(todos), "working", "continuing"])
    input_stream = StringIO("start the task\ncontinue please\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    second_task_system = _system_prompt(calls[2])
    assert "Todo List:\n- [in_progress] step one" in second_task_system


def test_repl_omits_the_todo_list_from_the_next_tasks_system_prompt_once_all_finished(
    route_env, install_fake_urlopen
):
    todos = [{"content": "step one", "status": "completed"}]
    calls = install_fake_urlopen([_todo_call(todos), "done", "ok"])
    input_stream = StringIO("finish the task\ncontinue please\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    assert "Todo List:" not in _system_prompt(calls[2])


def test_undo_restores_the_todo_list_to_before_the_undone_turn(route_env, install_fake_urlopen):
    first_todos = [{"content": "step one", "status": "in_progress"}]
    second_todos = [
        {"content": "step one", "status": "completed"},
        {"content": "step two", "status": "in_progress"},
    ]
    calls = install_fake_urlopen(
        [_todo_call(first_todos), "started", _todo_call(second_todos), "advanced", "resumed"]
    )
    input_stream = StringIO("start the task\nadvance the task\n/undo\ncontinue please\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    third_task_system = _system_prompt(calls[4])
    assert "Todo List:\n- [in_progress] step one" in third_task_system
    assert "step two" not in third_task_system


def test_retry_restores_the_todo_list_to_before_the_retried_turn(route_env, install_fake_urlopen):
    first_todos = [{"content": "step one", "status": "in_progress"}]
    second_todos = [
        {"content": "step one", "status": "completed"},
        {"content": "step two", "status": "in_progress"},
    ]
    calls = install_fake_urlopen(
        [_todo_call(first_todos), "started", _todo_call(second_todos), "advanced", "retried"]
    )
    input_stream = StringIO("start the task\nadvance the task\n/retry\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    retried_system = _system_prompt(calls[4])
    assert "Todo List:\n- [in_progress] step one" in retried_system
    assert "step two" not in retried_system


def test_clear_empties_the_todo_list(route_env, install_fake_urlopen):
    todos = [{"content": "step one", "status": "in_progress"}]
    calls = install_fake_urlopen([_todo_call(todos), "started", "fresh"])
    input_stream = StringIO("start the task\n/clear\ncontinue please\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    assert "Todo List:" not in _system_prompt(calls[2])


def test_a_failed_turn_leaves_the_todo_list_unchanged(route_env, install_fake_urlopen):
    todos = [{"content": "step one", "status": "in_progress"}]
    calls = install_fake_urlopen([_todo_call(todos), "started", ValueError("boom"), "still going"])
    input_stream = StringIO("start the task\nbad task\ncontinue please\nexit\n")
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    third_task_system = _system_prompt(calls[3])
    assert "Todo List:\n- [in_progress] step one" in third_task_system


def test_undo_after_compress_restores_the_todo_list_from_before_the_kept_turn(route_env, install_fake_urlopen):
    list_a = [{"content": "step one", "status": "in_progress"}]
    list_b = [
        {"content": "step one", "status": "completed"},
        {"content": "step two", "status": "in_progress"},
    ]
    calls = install_fake_urlopen(
        [
            _todo_call(list_a),
            "a1",
            "a2",
            _todo_call(list_b),
            "a3",
            {"content": "SUMMARY", "usage": {"cost": 0.0}},
            "after undo",
        ]
    )
    input_stream = StringIO(
        "refactor task one\nrefactor task two\nrefactor task three\n/compress\n/undo\ncontinue please\nexit\n"
    )
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=input_stream, output_stream=output_stream)

    final_system = _system_prompt(calls[-1])
    assert "Todo List:\n- [in_progress] step one" in final_system
    assert "step two" not in final_system



def test_manual_compression_keeps_todo_list_for_the_next_ordinary_turn(route_env, install_fake_urlopen):
    todos = [{"content": "step one", "status": "in_progress"}]
    calls = install_fake_urlopen([_todo_call(todos), "a1", "a2", "a3", {"content": "a4", "usage": CROSSING_USAGE},
                                 "THE SUMMARY", "next answer"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(
        THREE_TURNS + "refactor task four\n/compress\nnext task\nexit\n"), output_stream=output)
    assert len(calls) == 7
    assert "Compressed 2 turns." in output.getvalue()
    assert "Todo List:\n- [in_progress] step one" in _system_prompt(calls[-1])


def test_resume_rebuilds_the_todo_list_including_across_a_compression(route_env, install_fake_urlopen):
    list_a = [{"content": "step one", "status": "in_progress"}]
    list_b = [
        {"content": "step one", "status": "completed"},
        {"content": "step two", "status": "in_progress"},
    ]
    install_fake_urlopen(
        [
            _todo_call(list_a),
            "a1",
            "a2",
            _todo_call(list_b),
            "a3",
            {"content": "SUMMARY", "usage": {"cost": 0.0}},
        ]
    )
    run_repl(
        runtime_config.load(),
        input_stream=StringIO(
            "refactor task one\nrefactor task two\nrefactor task three\n/compress\nexit\n"
        ),
        output_stream=StringIO(),
    )
    session_id = call_log.current_session_id()
    call_log.reset_session()
    turns, summary, todo_baseline, _ = call_log.load_conversation(session_id)
    resumed = (session_id, turns, summary, todo_baseline, call_log.load_conversation(session_id)[3])
    calls = install_fake_urlopen(["resumed answer"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("continue please\nexit\n"),
        output_stream=output_stream,
        resumed=resumed,
    )

    system_content = _system_prompt(calls[0])
    assert "Todo List:\n- [completed] step one\n- [in_progress] step two" in system_content
