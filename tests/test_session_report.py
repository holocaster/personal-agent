import io
import json
from pathlib import Path

import pytest

from personal_agent import call_log, session_logs, session_report
from personal_agent.routing import router, runtime_config
from personal_agent.routing.router import route
from personal_agent.terminal import repl


def test_report_is_local_audited_and_keeps_empty_session_state(route_env, install_fake_urlopen):
    calls = install_fake_urlopen("unexpected")
    output = io.StringIO()
    repl.run_repl(runtime_config.load(), input_stream=["/report", "/report old", "/help", "/usage", "/exit"],
                  output_stream=output)
    text = output.getvalue()
    assert "Recorded Session report" in text
    assert "inspected Runs: 1" in text
    assert "Session subtotal: Attempts 0" in text
    assert "duration: sum 0 ms; mean unavailable; known 0/0" in text
    assert "cost: recorded $0" in text
    assert "Error: /report takes no arguments." in text
    assert "/report -" in text and "/report" in repl.COMMANDS
    assert "No ordinary exchange assessed yet this Run." in text
    assert calls == [] and call_log.total_cost() == 0
    rows = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    assert [row["outcome"] for row in rows if row["type"] == "audit_event" and row.get("name") == "/report"] == ["ok", "error"]
    assert not any(row["type"] in ("attempt", "turn_end", "routed_task_submitted") for row in rows)


def append(path, sid, **fields):
    with path.open("a") as file:
        file.write(json.dumps({"session_id": sid, **fields}) + "\n")


def test_report_counts_mixed_physical_attempts_across_runs_with_independent_coverage(route_env):
    config = runtime_config.load()
    sid = call_log.start_session(config)
    path = Path(call_log.session_log_path())
    append(path, sid, type="routed_task_submitted", ordinal=1, task="task", provider="openrouter", model="vendor/test-model")
    attempts = [
        dict(purpose="execution", outcome="ok", retry_kind="initial", latency_ms=100, cost=1,
             cost_estimated=False, prompt_tokens=100, completion_tokens=10, cached_tokens=0,
             cache_write_tokens=0, streamed=True, first_text_latency_ms=0),
        dict(purpose="execution", outcome="ok", retry_kind="initial", latency_ms=200, cost=.5,
             cost_estimated=True, prompt_tokens=50, completion_tokens=5, cached_tokens=20,
             cache_write_tokens=5, streamed=False),
        dict(purpose="execution", outcome="error", retry_kind="transient", latency_ms=50, cost=.25,
             prompt_tokens=20, completion_tokens=0, streamed=True, first_text_latency_ms=None),
        dict(purpose="execution", outcome="interrupted", retry_kind="context_overflow", latency_ms=150,
             cost=0, cost_estimated=False, prompt_tokens=30, completion_tokens=2, cached_tokens=5,
             cache_write_tokens=0, streamed=True, first_text_latency_ms=25),
        dict(purpose="tier_selection", ok=True, latency_ms=1000, cost=2, cost_estimated=True,
             prompt_tokens=40, completion_tokens=3),
        dict(purpose="compression", outcome="ok", retry_kind="initial", latency_ms=500, cost=1,
             cost_estimated=False, prompt_tokens=60, completion_tokens=4, cached_tokens=10,
             cache_write_tokens=2, streamed=False),
        dict(task="/compress", ok=False, latency_ms=0, prompt_tokens=0, completion_tokens=0,
             cached_tokens=0, cache_write_tokens=0),
        dict(purpose="future", outcome="error", retry_kind="future", latency_ms=True, cost=True,
             prompt_tokens=7, completion_tokens=-1, streamed=True, first_text_latency_ms=float("inf")),
    ]
    for attempt in attempts[:4]:
        append(path, sid, type="attempt", **attempt)
    append(path, sid, type="turn_end", messages=[attempts[0]])
    append(path, sid, type="audit_event", event={"type": "attempt", **attempts[0]})
    call_log.end_session("eof")
    call_log.resume_session(sid, config)
    for attempt in attempts[4:]:
        append(path, sid, type="attempt", **attempt)
    for kind in ("conversation_cleared", "conversation_undone", "upstream_provider", "tool_execution",
                 "routed_task_retried", "turn_end", "routed_task_retried", "turn_end"):
        append(path, sid, type=kind, ordinal=1)
    text = session_report.render()
    assert "inspected Runs: 2" in text
    assert "execution: Attempts 4; ok 2; error 1; interrupted 1" in text
    assert "tier evaluation" not in text
    assert "Compression: Attempts 2; ok 1; error 0; interrupted 0; failed-or-interrupted 1" in text
    assert "unknown purpose: Attempts 2; ok 1; error 1" in text
    total = text.split("Session subtotal:", 1)[1]
    assert "Attempts 8; ok 4; error 2; interrupted 1; failed-or-interrupted 1; unknown outcome 0" in total
    assert "technical retries 2 (transient 1, context-overflow 1); initial 3; unknown 3/8" in total
    assert "Explicit user Retry: 2" in text
    assert "duration: sum 2000 ms; mean 285.714 ms; known 7/8, missing 0, invalid 1" in total
    assert "first text: mean 12.5 ms; known 2/8; textless/undelivered 1; unmeasured 2; unknown 2; invalid 1" in total
    assert "prompt 307 [8/8 known, 0 missing, 0 invalid]" in total
    assert "completion 24 [7/8 known, 0 missing, 1 invalid]" in total
    assert "cache-read 35 [5/8 known, 3 missing, 0 invalid]" in total
    assert "cache-write 7 [5/8 known, 3 missing, 0 invalid]" in total
    assert "cost: recorded $4.75; reported $2 (3); estimated $2.5 (2); unknown provenance $0.25 (1); known 6/8, missing 1, invalid 1" in total
    assert "invalid latency_ms, cost, completion_tokens, first_text_latency_ms" in text
    assert "partial inspection" not in text.lower()
    assert call_log.total_cost() == 0


@pytest.mark.parametrize("invalid", [True, -1, float("inf"), float("nan"), "3", [], {}])
def test_invalid_samples_are_independent_of_valid_zero_tokens(route_env, invalid):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path())
    append(path, sid, type="attempt", latency_ms=invalid, cost=invalid, prompt_tokens=0,
           completion_tokens=invalid, cached_tokens=0, cache_write_tokens=0)
    text = session_report.render()
    assert "duration: sum 0 ms; mean unavailable; known 0/1, missing 0, invalid 1" in text
    assert "prompt 0 [1/1 known, 0 missing, 0 invalid]" in text
    assert "completion unavailable [0/1 known, 0 missing, 1 invalid]" in text
    assert "cost: recorded unavailable" in text


def test_legacy_attribution_and_missing_samples_are_not_guessed(route_env):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path())
    append(path, sid, type="attempt", ok=False, attempt=20, cost=0, completion_tokens=1.5)
    append(path, sid, type="attempt", purpose=None, outcome="failed-or-interrupted", retry_kind="future")
    text = session_report.render()
    assert "execution: Attempts 1; ok 0; error 0; interrupted 0; failed-or-interrupted 1" in text
    assert "unknown purpose: Attempts 1; ok 0; error 0; interrupted 0; failed-or-interrupted 0; unknown outcome 1" in text
    assert "unknown 2/2" in text
    assert "first text: mean unavailable; known 0/2; textless/undelivered 0; unmeasured 0; unknown 2" in text
    assert "unknown provenance $0 (1); known 1/2, missing 1, invalid 0" in text
    assert "completion unavailable [0/2 known, 1 missing, 1 invalid]" in text


def test_damaged_rows_are_partial_and_untrusted_metrics_never_count(route_env):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path())
    append(path, sid, type="routed_task_submitted", ordinal=1)
    append(path, sid, type="attempt", cost=1, prompt_tokens=3)
    with path.open("ab") as file:
        file.write(b"bad-json\n[]\n")
    append(path, "wrong", type="attempt", cost=999)
    append(path, sid, type="attempt", project_id="wrong", cost=999)
    append(path, sid, type="attempt", cost=999, answer="x" * (session_logs.MAX_RECORD_BYTES + 1))
    append(path, sid, type="attempt", cost=2, prompt_tokens=4)
    with path.open("ab") as file:
        file.write(b'{"type":"attempt"}')
    text = session_report.render()
    assert "PARTIAL INSPECTION" in text
    assert "Session subtotal: Attempts 2" in text
    assert "cost: recorded $3" in text
    for notice in ("invalid JSON", "non-object", "wrong Session identity", "wrong project identity",
                   "oversized record", "incomplete record", "submission unresolved: missing Turn End"):
        assert notice in text
    assert f"{path.name}:4" in text


@pytest.mark.parametrize("damage", ["missing", "unsafe", "initial", "empty", "records", "bytes"])
def test_unavailable_and_bounded_inspection_are_visible(route_env, tmp_path, monkeypatch, damage):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path())
    if damage in ("missing", "unsafe"):
        path.unlink()
        if damage == "unsafe":
            target = tmp_path / "outside"
            target.write_text("private")
            path.symlink_to(target)
    elif damage == "initial":
        entry = json.loads(path.read_text())
        entry["workspace_root"] = "/wrong"
        path.write_text(json.dumps(entry) + "\n")
    elif damage == "empty":
        path.write_text("")
    else:
        append(path, sid, type="attempt", cost=1)
        monkeypatch.setattr(session_logs, "MAX_RECORDS" if damage == "records" else "MAX_BYTES",
                            1 if damage == "records" else path.stat().st_size - 1)
    text = session_report.render()
    assert "PARTIAL INSPECTION" in text and "Session subtotal: Attempts 0" in text
    assert path.name in text
    if damage in ("records", "bytes"):
        assert "scan budget exhausted" in text


def test_unclosed_prior_run_and_submission_are_unresolved_but_active_run_is_normal(route_env):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path())
    assert "unresolved" not in session_report.render()
    append(path, sid, type="routed_task_submitted", ordinal=1)
    initial = json.loads(path.read_text().splitlines()[0])
    append(path, sid, **{key: value for key, value in {**initial, "type": "session_resumed", "run_id": "a" * 32}.items()
                        if key != "session_id"})
    text = session_report.render()
    assert "inspected Runs: 2" in text
    assert "prior Run unresolved: missing Run close" in text
    assert "submission unresolved: missing Turn End" in text


def test_report_diagnostics_and_output_are_bounded_and_sanitized(route_env, monkeypatch):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path())
    for _ in range(20):
        append(path, sid, type="attempt", latency_ms=-1, prompt_tokens=10 ** 4000)
    text = session_report.render(("invalid",))
    assert len(text.encode()) <= session_report.MAX_SUMMARY_BYTES
    assert "[subtotal exceeds rendering bound]" in text
    assert "Session subtotal: Attempts 20" in text
    assert "invalid" not in text
    path.write_text("bad\n" * 20)
    text = session_report.render()
    assert "invalid initial Run metadata" in text
    def inaccessible(*args, **kwargs):
        raise PermissionError("known-secret\x1b[31m")
    monkeypatch.setattr(call_log, "open_session_file", inaccessible)
    text = session_report.render(("known-secret",))
    assert "known-secret" not in text and "\x1b" not in text
    assert "[redacted]" in text and "PARTIAL INSPECTION" in text


def test_attempt_duration_excludes_busy_setup_and_retains_interrupted_usage(route_env, monkeypatch):
    from personal_agent.providers import openrouter
    clock = [0.0]
    monkeypatch.setattr(router.time, "monotonic", lambda: clock[0])
    def busy(operation):
        clock[0] += 10
        try:
            return operation()
        finally:
            clock[0] += 20
    def interrupt(*args, **kwargs):
        clock[0] += .125
        error = KeyboardInterrupt()
        error.usage = {"cost": .3, "prompt_tokens": 11, "completion_tokens": 2}
        raise error
    monkeypatch.setattr(openrouter, "call", interrupt)
    with pytest.raises(KeyboardInterrupt):
        route("request", runtime_config.load(), run_busy=busy)
    entry = json.loads(Path(call_log.session_log_path()).read_text().splitlines()[-1])
    assert entry["latency_ms"] == 125
    assert entry["outcome"] == "interrupted"
    assert entry["cost"] == .3 and entry["prompt_tokens"] == 11 and entry["completion_tokens"] == 2
    assert call_log.total_cost() == .3


def test_report_after_resume_keeps_pending_tool_prefix_and_clear_undo_activity(route_env, install_fake_urlopen):
    config = runtime_config.load()
    first_calls = install_fake_urlopen([
        {"tool_calls": [{"id": "once", "name": "calculator", "arguments": {"expression": "2+2"}}],
         "usage": {"cost": .1}}, RuntimeError("failed follow-up"),
    ])
    repl.run_repl(config, input_stream=["calculate", "/exit"], output_stream=io.StringIO())
    assert len(first_calls) == 2
    sid = call_log.current_session_id()
    restored = call_log.load_conversation(sid)
    pending = call_log.load_pending_turn(sid)
    calls = install_fake_urlopen([{"content": "done", "usage": {"cost": .2}}])
    output = io.StringIO()
    repl.run_repl(config, input_stream=["/report", "/usage", "/retry", "/undo", "/clear", "/report", "/exit"],
                  output_stream=output, resumed=(sid, *restored))
    text = output.getvalue()
    assert text.count("inspected Runs: 2") == 2
    assert "Session subtotal: Attempts 2" in text and "Session subtotal: Attempts 3" in text
    assert "Explicit user Retry: 0" in text and "Explicit user Retry: 1" in text
    assert "spend: $0.0000" in text
    assert "cost: recorded $0.3" in text
    assert len(calls) == 1
    body = json.loads(calls[0]["request"].data)
    assert body["messages"][-1]["role"] == "tool" and body["messages"][-1]["tool_call_id"] == "once"
    assert pending[1]["task"] == "calculate"
    assert call_log.total_cost() == .2
    rows = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    assert len([row for row in rows if row["type"] == "tool_execution"]) == 1
    assert [row["retry_kind"] for row in rows if row["type"] == "attempt"] == ["initial"] * 3
    assert call_log.load_conversation(sid)[0] == ()


def test_report_correlates_routes_by_explicit_openings_and_not_text(route_env):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path())
    append(path, sid, type="attempt", task="same", model="legacy", prompt_tokens=99)
    append(path, sid, type="routed_task_submitted", ordinal=1, task="same")
    append(path, sid, type="attempt", purpose="compression", provider="openai", model="judge")
    append(path, sid, type="attempt", task="same", provider="openai", model="first",
           prompt_tokens=100, cached_tokens=20, cache_write_tokens=0, latency_ms=10,
           completion_tokens=3, cost=.1, cost_estimated=True, retry_kind="initial")
    append(path, sid, type="turn_end", status="error")
    append(path, sid, type="attempt", purpose="compression", model="outside")
    append(path, sid, type="routed_task_retried", ordinal=1, task="same")
    append(path, sid, type="attempt", provider="openai", model="second",
           prompt_tokens=100, cached_tokens=0, cache_write_tokens=0, latency_ms=20,
           completion_tokens=2, cost=.2, cost_estimated=False, retry_kind="transient")
    text = session_report.render()
    detail = text.split("Latest opened executions", 1)[1]
    assert "ordinal 1; submitted; outcome error" in detail
    assert "ordinal 1; Retry; outcome unresolved" in detail
    assert "Run " in detail and "opening line 3" in detail and "opening line 8" in detail
    assert "execution openai/first" in detail and "execution openai/second" in detail
    assert "observed Provider/model change" in detail
    assert "cache-read 20" in detail and "cache-read 0" in detail
    assert "Compression openai/judge" in detail and "tier" not in detail
    assert "outside" not in detail and "legacy" not in detail
    assert "Unattributed Attempts: 2" in text


def test_cache_fraction_uses_only_compatible_same_samples(route_env):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path())
    for values in [dict(prompt_tokens=100, cached_tokens=20, cache_write_tokens=0),
                   dict(prompt_tokens=100, cached_tokens=0),
                   dict(prompt_tokens=10, cached_tokens=11, cache_write_tokens=0),
                   dict(prompt_tokens=10, cached_tokens=8, cache_write_tokens=3),
                   dict(prompt_tokens=0, cached_tokens=0, cache_write_tokens=0),
                   dict(cached_tokens=3, cache_write_tokens=0),
                   dict(prompt_tokens=100, cached_tokens=True, cache_write_tokens=0)]:
        append(path, sid, type="attempt", **values)
    text = session_report.render()
    assert "cache-read fraction 10% [2/7 compatible samples]" in text
    assert "prompt 320 [6/7 known, 1 missing, 0 invalid]" in text
    assert "cache-read 42 [6/7 known, 0 missing, 1 invalid]" in text


def test_report_bounds_latest_executions_routes_and_bytes_without_losing_aggregates(route_env):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path())
    for ordinal in range(1, 24):
        append(path, sid, type="routed_task_submitted", ordinal=ordinal)
        for group in range(18):
            append(path, sid, type="attempt", provider="openai", model=f"route-{group}", tier="easy",
                   prompt_tokens=100, completion_tokens=3, cached_tokens=0, cache_write_tokens=0,
                   latency_ms=10, retry_kind="initial", cost=0, cost_estimated=True,
                   streamed=True, first_text_latency_ms=1)
        append(path, sid, type="turn_end", status="ok")
    text = session_report.render()
    assert len(text.encode()) <= 16 * 1024
    assert "Session subtotal: Attempts 414" in text
    assert "prompt 41400 [414/414 known, 0 missing, 0 invalid]" in text
    assert "Latest opened executions: 20/23; older executions omitted 3" in text
    detail = text.split("Latest opened executions", 1)[1]
    assert "ordinal 3;" not in detail
    assert all(f"ordinal {ordinal};" in detail for ordinal in range(4, 24))
    assert "2 Attempts beyond 16 route groups" in detail
    assert "Details omitted" in detail


def test_record_damage_breaks_attribution_until_next_opening(route_env):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path())
    append(path, sid, type="routed_task_submitted", ordinal=1)
    with path.open("a") as file:
        file.write("invalid-json\n")
    append(path, sid, type="attempt", provider="openai", model="unattributed")
    append(path, sid, type="routed_task_submitted", ordinal=2)
    append(path, sid, type="attempt", provider="openai", model="attributed")
    text = session_report.render()
    detail = text.split("Latest opened executions", 1)[1]
    assert "unattributed" not in detail and "attributed" in detail
    assert "Unattributed Attempts: 1" in text and "PARTIAL INSPECTION" in text


def test_route_labels_are_bounded_redacted_and_sanitized_before_display(route_env):
    sid = call_log.start_session(runtime_config.load())
    path = Path(call_log.session_log_path())
    append(path, sid, type="routed_task_submitted", ordinal=1)
    append(path, sid, type="attempt", tier="easy", provider="openai",
           model="a" * 90 + "secret-value" + "\x1b[31m\nforged")
    text = session_report.render(("secret-value",))
    assert "secret" not in text and "value" not in text and "\x1b" not in text
    assert "\nforged" not in text and "truncated" in text


def test_report_preserves_pending_routing_input_usage_spend_and_configuration(
        route_env, install_fake_urlopen, monkeypatch):
    from copy import deepcopy
    from personal_agent import token_estimate
    from personal_agent.providers import http

    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "once", "name": "calculator", "arguments": {"expression": "2+2"}}],
         "usage": {"cost": .1}}, RuntimeError("failed follow-up"),
    ])
    output = io.StringIO()
    config = runtime_config.load()
    def commands():
        yield "calculate"
        sid = call_log.current_session_id()
        before = deepcopy((call_log.load_conversation(sid), call_log.load_pending_turn(sid), call_log.total_cost(), config))
        path = Path(call_log.session_log_path())
        records = [json.loads(line) for line in path.read_text().splitlines()]
        position = output.tell()
        yield "/usage"
        usage = output.getvalue()[position:]
        def forbidden(*args, **kwargs):
            raise AssertionError("report attempted remote, metadata or tokenizer access")
        monkeypatch.setattr(http, "urlopen", forbidden)
        monkeypatch.setattr(token_estimate, "local_library", forbidden)
        yield "/report"
        assert (call_log.load_conversation(sid), call_log.load_pending_turn(sid), call_log.total_cost(), config) == before
        after = [json.loads(line) for line in path.read_text().splitlines()]
        assert [row for row in after[len(records):] if row["type"] != "audit_event"] == []
        assert [row["name"] for row in after[len(records):] if row["type"] == "audit_event"] == ["/usage", "/report"]
        position = output.tell()
        yield "/usage"
        assert output.getvalue()[position:] == usage
        assert len(calls) == 2
        yield "/exit"
    repl.run_repl(config, input_stream=commands(), output_stream=output)
