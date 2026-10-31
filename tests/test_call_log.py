import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError

import pytest

from personal_agent import call_log
from personal_agent.routing import router, runtime_config
from personal_agent.routing.router import route
from tests.fakes import Repeat

EXPECTED_KEYS = {
    "timestamp",
    "session_id",
    "type",
    "task",
    "model",
    "provider",
    "latency_ms",
    "cost",
    "prompt_tokens",
    "completion_tokens",
    "cached_tokens",
    "cache_write_tokens",
    "ok",
    "error",
    "attempt",
    "cost_estimated",
    "upstream_provider",
    "answer",
    "tool_calls",
    "purpose",
    "outcome",
    "retry_kind",
    "streamed",
    "first_text_latency_ms",
    "access_method",
}

EXPECTED_TOOL_EXECUTION_KEYS = {
    "timestamp",
    "session_id",
    "type",
    "tool_call_id",
    "name",
    "arguments",
    "ok",
    "result",
    "error",
}

SESSION_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z-[a-z0-9]{6}$")


def _log_lines(log_path):
    return Path(log_path).read_text().splitlines()


def test_successful_call_appends_line_with_expected_fields(tmp_path, monkeypatch, route_env, install_fake_urlopen):
    install_fake_urlopen("the answer")
    config = runtime_config.load()

    result = route("summarize this line", config)

    lines = _log_lines(call_log.session_log_path())
    assert len(lines) == 1
    entry = json.loads(lines[-1])
    assert set(entry) == EXPECTED_KEYS
    assert entry["type"] == "attempt"
    assert entry["session_id"] == call_log.current_session_id()
    assert entry["task"] == "summarize this line"
    assert "tier" not in entry
    assert entry["model"] == result.model
    assert entry["provider"] == "openrouter"
    assert entry["cost_estimated"] is False
    assert isinstance(entry["latency_ms"], int)
    assert entry["ok"] is True
    assert entry["error"] is None
    assert entry["attempt"] == 1
    assert entry["answer"] == "the answer"
    assert entry["tool_calls"] == []
    assert entry["purpose"] == "execution"
    assert entry["outcome"] == "ok"
    assert entry["retry_kind"] == "initial"


def test_response_missing_usage_yields_null_cost_and_tokens_but_still_succeeds(
    tmp_path, monkeypatch, route_env, install_fake_urlopen
):
    install_fake_urlopen("the answer")
    config = runtime_config.load()

    route("summarize this line", config)

    entry = json.loads(_log_lines(call_log.session_log_path())[-1])
    assert entry["cost"] is None
    assert entry["prompt_tokens"] is None
    assert entry["completion_tokens"] is None
    assert entry["cached_tokens"] is None
    assert entry["cache_write_tokens"] is None
    assert entry["ok"] is True


def test_openrouter_cache_usage_is_logged_when_reported(tmp_path, monkeypatch, route_env, install_fake_urlopen):
    install_fake_urlopen([{
        "content": "the answer",
        "usage": {
            "cost": 0.001, "prompt_tokens": 2000, "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 1500, "cache_write_tokens": 500},
        },
    }])

    route("summarize this line", runtime_config.load())

    entry = json.loads(_log_lines(call_log.session_log_path())[-1])
    assert (entry["cached_tokens"], entry["cache_write_tokens"]) == (1500, 500)
    assert entry["prompt_tokens"] == 2000
    assert entry["cost"] == 0.001


def test_unpriceable_anthropic_model_logs_null_estimated_cost(
    tmp_path, monkeypatch, route_env, install_fake_urlopen
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    monkeypatch.setenv("PA_PROVIDER", "anthropic")
    monkeypatch.setenv("PA_MODEL", "not-a-real-model")
    install_fake_urlopen(
        [{"content": "the answer", "usage": {"prompt_tokens": 10, "completion_tokens": 5}}]
    )

    route("summarize this line", runtime_config.load())

    entry = json.loads(_log_lines(call_log.session_log_path())[-1])
    assert entry["provider"] == "anthropic"
    assert entry["model"] == "not-a-real-model"
    assert entry["cost"] is None
    assert entry["cost_estimated"] is True


@pytest.mark.parametrize(
    ("provider", "key_name", "model"),
    [("openai", "OPENAI_API_KEY", "gpt-5.4"), ("gemini", "GEMINI_API_KEY", "gemini-2.5-flash")],
)
def test_new_estimating_providers_log_derived_estimated_cost(
    tmp_path, monkeypatch, route_env, install_fake_urlopen, provider, key_name, model
):
    monkeypatch.setenv(key_name, "test-key")
    monkeypatch.setenv("PA_PROVIDER", provider)
    monkeypatch.setenv("PA_MODEL", model)
    install_fake_urlopen([{"content": "the answer", "usage": {"prompt_tokens": 10, "completion_tokens": 5,
        "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}}}])

    route("summarize this line", runtime_config.load())

    entry = json.loads(_log_lines(call_log.session_log_path())[-1])
    assert entry["provider"] == provider
    assert entry["cost_estimated"] is True
    assert isinstance(entry["cost"], float)
    assert entry["cost"] > 0


def test_failed_call_appends_line_with_ok_false_and_error(tmp_path, monkeypatch, route_env, install_fake_urlopen):
    install_fake_urlopen([ValueError("bad request")])
    config = runtime_config.load()

    result = route("summarize this line", config)

    entry = json.loads(_log_lines(call_log.session_log_path())[-1])
    assert set(entry) == EXPECTED_KEYS
    assert entry["ok"] is False
    assert entry["error"]
    assert entry["cost"] is None
    assert entry["prompt_tokens"] is None
    assert entry["completion_tokens"] is None
    assert "tier" not in entry
    assert entry["model"] == result.model
    assert entry["attempt"] == 1
    assert entry["answer"] is None
    assert entry["tool_calls"] is None
    assert result.ok is False
    assert result.error


def test_two_calls_append_two_lines_rather_than_truncating(tmp_path, monkeypatch, route_env, install_fake_urlopen):
    install_fake_urlopen(["first", "second"])
    config = runtime_config.load()

    route("summarize this line", config)
    route("summarize this other line", config)

    assert len(_log_lines(call_log.session_log_path())) == 2


def test_exhausted_route_logs_one_line_per_attempt_with_attempt_running_1_2_3(
    tmp_path, monkeypatch, route_env, install_fake_urlopen
):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    install_fake_urlopen([Repeat(HTTPError("https://openrouter.ai", 503, "err", None, None))])
    config = runtime_config.load()

    route("please refactor this module", config)

    lines = [json.loads(line) for line in _log_lines(call_log.session_log_path())]
    assert len(lines) == 3
    assert [entry["attempt"] for entry in lines] == [1, 2, 3]
    for entry in lines:
        assert set(entry) == EXPECTED_KEYS
        assert entry["task"] == "please refactor this module"
        assert entry["ok"] is False
        assert entry["error"]


def test_exhausted_route_logs_one_line_per_attempt_in_order(
    tmp_path, monkeypatch, route_env, install_fake_urlopen
):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    install_fake_urlopen(
        [
            HTTPError("https://openrouter.ai", 503, "err", None, None),
            HTTPError("https://openrouter.ai", 503, "err", None, None),
            HTTPError("https://openrouter.ai", 503, "err", None, None),
        ]
    )
    config = runtime_config.load()

    route("summarize this line", config)

    lines = [json.loads(line) for line in _log_lines(call_log.session_log_path())]
    assert len(lines) == 3
    assert [(entry["model"], entry["attempt"], entry["ok"]) for entry in lines] == [
        ("vendor/test-model", 1, False),
        ("vendor/test-model", 2, False),
        ("vendor/test-model", 3, False),
    ]
    for entry in lines[:3]:
        assert entry["error"]
    for entry in lines:
        assert set(entry) == EXPECTED_KEYS
        assert entry["task"] == "summarize this line"
        assert entry["provider"] == "openrouter"
        assert entry["cost_estimated"] is False


def test_default_path_creates_project_folder_under_home(tmp_path, route_env, install_fake_urlopen):
    install_fake_urlopen("the answer")
    route("summarize this line", runtime_config.load())
    path = Path(call_log.session_log_path())
    assert path.parent.parent == tmp_path / ".personal_agent" / "logs"
    assert path.name == f"pa_log-{call_log.current_session_id()}.jsonl"
    assert path.exists()


def test_two_sessions_write_two_distinct_files_without_appending_to_each_other(
    tmp_path, monkeypatch, route_env, install_fake_urlopen
):
    install_fake_urlopen(["first", "second"])
    config = runtime_config.load()

    call_log.start_session(config)
    route("summarize this line", config)
    first_path = call_log.session_log_path()

    call_log.start_session(config)
    route("summarize this other line", config)
    second_path = call_log.session_log_path()

    assert first_path != second_path
    assert len(_log_lines(first_path)) == 2
    assert len(_log_lines(second_path)) == 2


def test_session_id_matches_the_documented_pattern_and_sorts_chronologically(route_env):
    config = runtime_config.load()
    call_log.reset_session()
    first = call_log.start_session(config)
    # The timestamp component has 1-second resolution; sleep past a second
    # boundary so the two ids are guaranteed to differ there rather than
    # only in their random suffix, keeping the ordering assertion below
    # deterministic without an injected clock (Testing Decisions).
    time.sleep(1.1)
    second = call_log.start_session(config)

    assert SESSION_ID_PATTERN.match(first)
    assert SESSION_ID_PATTERN.match(second)
    assert ":" not in first
    assert "/" not in first
    assert first < second

    call_log.reset_session()


# --- total_cost (R12) -----------------------------------------------------


def test_total_cost_starts_at_zero_for_a_fresh_session(route_env):
    call_log.start_session(runtime_config.load())

    assert call_log.total_cost() == 0.0


def test_total_cost_matches_the_running_total_session_end_reports(route_env, install_fake_urlopen):
    install_fake_urlopen(
        [{"content": "first answer", "usage": {"cost": 0.6}}, {"content": "second answer", "usage": {"cost": 0.5}}]
    )
    config = runtime_config.load()

    route("summarize this line", config)
    route("summarize this other line", config)

    assert call_log.total_cost() == pytest.approx(1.1)
    call_log.end_session("exit_command")
    entry = json.loads(_log_lines(call_log.session_log_path())[-1])
    assert entry["total_cost"] == call_log.total_cost()


# --- attempt.tool_calls (R06) -------------------------------------------


def test_attempt_line_records_the_requested_tool_call_and_unparsable_arguments_raw(
    route_env, install_fake_urlopen
):
    install_fake_urlopen(
        [
            {
                "tool_calls": [
                    {"id": "call_1", "name": "calculator", "arguments": None, "arguments_raw": "not json"}
                ]
            },
            "handled it",
        ]
    )

    route("what is 2+2?", runtime_config.load())

    entries = [json.loads(line) for line in _log_lines(call_log.session_log_path())]
    requesting = entries[0]
    assert requesting["type"] == "attempt"
    assert requesting["tool_calls"] == [
        {"id": "call_1", "name": "calculator", "arguments": None, "arguments_raw": "not json"}
    ]


def test_attempt_line_records_null_arguments_raw_for_successfully_parsed_tool_call(
    route_env, install_fake_urlopen
):
    install_fake_urlopen(
        [
            {
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "calculator",
                        "arguments": {"expression": "2+2"},
                        "arguments_raw": '{"expression": "2+2"}',
                    }
                ]
            },
            "The answer is 4.",
        ]
    )

    route("what is 2+2?", runtime_config.load())

    entries = [json.loads(line) for line in _log_lines(call_log.session_log_path())]
    requesting = entries[0]
    assert requesting["type"] == "attempt"
    assert requesting["tool_calls"] == [
        {"id": "call_1", "name": "calculator", "arguments": {"expression": "2+2"}, "arguments_raw": None}
    ]


# --- tool_execution (R07, R10) ------------------------------------------


def test_calculator_round_writes_a_correlated_tool_execution_line_end_to_end(route_env, install_fake_urlopen):
    install_fake_urlopen(
        [
            {"tool_calls": [{"id": "call_1", "name": "calculator", "arguments": {"expression": "2+2"}}]},
            "The answer is 4.",
        ]
    )

    route("what is 2+2?", runtime_config.load())

    entries = [json.loads(line) for line in _log_lines(call_log.session_log_path())]
    tool_lines = [entry for entry in entries if entry["type"] == "tool_execution"]
    assert len(tool_lines) == 1
    line = tool_lines[0]
    assert set(line) == EXPECTED_TOOL_EXECUTION_KEYS
    assert line["session_id"] == call_log.current_session_id()
    assert line["tool_call_id"] == "call_1"
    assert line["name"] == "calculator"
    assert line["arguments"] == {"expression": "2+2"}
    assert line["ok"] is True
    assert line["result"] == {"result": 4}
    assert line["error"] is None


def test_clock_round_writes_a_correlated_tool_execution_line_end_to_end(route_env, install_fake_urlopen):
    install_fake_urlopen(
        [
            {"tool_calls": [{"id": "call_1", "name": "current_time", "arguments": {}}]},
            "That's the time.",
        ]
    )

    route("what time is it?", runtime_config.load())

    entries = [json.loads(line) for line in _log_lines(call_log.session_log_path())]
    tool_lines = [entry for entry in entries if entry["type"] == "tool_execution"]
    assert len(tool_lines) == 1
    line = tool_lines[0]
    assert set(line) == EXPECTED_TOOL_EXECUTION_KEYS
    assert line["tool_call_id"] == "call_1"
    assert line["name"] == "current_time"
    assert line["arguments"] == {}
    assert line["ok"] is True
    assert "utc_time" in line["result"]
    assert line["error"] is None


def test_multi_call_batch_logs_one_tool_execution_line_per_call_in_execution_order(
    route_env, install_fake_urlopen
):
    install_fake_urlopen(
        [
            {
                "tool_calls": [
                    {"id": "call_1", "name": "calculator", "arguments": {"expression": "1+1"}},
                    {"id": "call_2", "name": "calculator", "arguments": {"expression": "2+2"}},
                ]
            },
            "They are 2 and 4.",
        ]
    )

    route("compute 1+1 and 2+2", runtime_config.load())

    entries = [json.loads(line) for line in _log_lines(call_log.session_log_path())]
    tool_lines = [entry for entry in entries if entry["type"] == "tool_execution"]
    assert [(line["tool_call_id"], line["result"]) for line in tool_lines] == [
        ("call_1", {"result": 2}),
        ("call_2", {"result": 4}),
    ]


def test_rejected_unknown_tool_and_invalid_arguments_log_ok_false_tool_execution_lines(
    route_env, install_fake_urlopen
):
    install_fake_urlopen(
        [
            {
                "tool_calls": [
                    {"id": "1", "name": "not_a_tool", "arguments": {}},
                    {"id": "2", "name": "calculator", "arguments": None, "arguments_raw": "not json"},
                ]
            },
            "handled both",
        ]
    )

    route("try some bad tools", runtime_config.load())

    entries = [json.loads(line) for line in _log_lines(call_log.session_log_path())]
    tool_lines = [entry for entry in entries if entry["type"] == "tool_execution"]
    assert len(tool_lines) == 2
    assert tool_lines[0]["ok"] is False
    assert tool_lines[0]["arguments"] is None
    assert tool_lines[0]["result"] is None
    assert "unknown tool" in tool_lines[0]["error"]
    assert tool_lines[1]["ok"] is False
    assert tool_lines[1]["arguments"] is None
    assert "invalid arguments" in tool_lines[1]["error"]


def test_malformed_correlation_batch_writes_no_tool_execution_line(route_env, install_fake_urlopen):
    install_fake_urlopen(
        [
            {
                "tool_calls": [
                    {"id": "dup", "name": "calculator", "arguments": {"expression": "1+1"}},
                    {"id": "dup", "name": "calculator", "arguments": {"expression": "2+2"}},
                ]
            }
        ]
    )

    result = route("compute two things", runtime_config.load())

    assert result.ok is False
    entries = [json.loads(line) for line in _log_lines(call_log.session_log_path())]
    assert [entry["type"] for entry in entries] == ["attempt"]


def test_tool_round_line_order_is_requesting_attempt_then_tool_lines_then_follow_up_attempt(
    route_env, install_fake_urlopen
):
    install_fake_urlopen(
        [
            {
                "tool_calls": [
                    {"id": "call_1", "name": "calculator", "arguments": {"expression": "1+1"}},
                    {"id": "call_2", "name": "calculator", "arguments": {"expression": "2+2"}},
                ]
            },
            "They are 2 and 4.",
        ]
    )

    route("compute 1+1 and 2+2", runtime_config.load())

    entries = [json.loads(line) for line in _log_lines(call_log.session_log_path())]
    assert [entry["type"] for entry in entries] == [
        "attempt",
        "tool_execution",
        "tool_execution",
        "attempt",
    ]
    assert [entry["tool_call_id"] for entry in entries[1:3]] == ["call_1", "call_2"]


def test_consecutive_tool_rounds_correlate_each_tool_execution_to_its_requesting_attempt(
    route_env, install_fake_urlopen
):
    install_fake_urlopen(
        [
            {"tool_calls": [{"id": "call_1", "name": "calculator", "arguments": {"expression": "1+1"}}]},
            {"tool_calls": [{"id": "call_2", "name": "calculator", "arguments": {"expression": "2+2"}}]},
            "2 then 4.",
        ]
    )

    route("compute step by step", runtime_config.load())

    entries = [json.loads(line) for line in _log_lines(call_log.session_log_path())]
    assert [entry["type"] for entry in entries] == [
        "attempt",
        "tool_execution",
        "attempt",
        "tool_execution",
        "attempt",
    ]
    first_attempt_ids = {call["id"] for call in entries[0]["tool_calls"]}
    second_attempt_ids = {call["id"] for call in entries[2]["tool_calls"]}
    assert entries[1]["tool_call_id"] in first_attempt_ids
    assert entries[3]["tool_call_id"] in second_attempt_ids


def test_tool_execution_does_not_advance_the_attempt_counter_or_write_an_attempt_line(
    route_env, install_fake_urlopen
):
    install_fake_urlopen(
        [
            {"tool_calls": [{"id": "call_1", "name": "calculator", "arguments": {"expression": "2+2"}}]},
            "The answer is 4.",
        ]
    )

    route("what is 2+2?", runtime_config.load())

    entries = [json.loads(line) for line in _log_lines(call_log.session_log_path())]
    attempt_entries = [entry for entry in entries if entry["type"] == "attempt"]
    assert [entry["attempt"] for entry in attempt_entries] == [1, 2]
