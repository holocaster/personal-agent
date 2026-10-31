import json
from dataclasses import replace
from io import StringIO

import pytest

from personal_agent import call_log, context_budget, token_estimate
from personal_agent.routing import router, runtime_config
from personal_agent.terminal.repl import run_repl
from tests.fakes import Repeat
from tests.test_compression import entries, fixture_estimate, inject_append_failure, seed


@pytest.fixture
def config(route_env, monkeypatch):
    for provider in ("openai", "anthropic", "gemini"):
        monkeypatch.setenv(runtime_config.API_KEY_ENV_VARS[provider], f"synthetic-{provider}-key")
    monkeypatch.setattr(context_budget, "model_info", lambda *_: {})
    return replace(runtime_config.load(), capacity_overrides=(
        {"provider": "openrouter", "model": "vendor/test-model", "total_tokens": 250000},))


def scripted_estimate(monkeypatch, original, reduced=150000, protected=100000):
    def estimate(model, prepared):
        if "tools" not in prepared:
            return fixture_estimate(model, prepared)
        text = json.dumps(prepared)
        tokens = original if "old-context" in text else reduced if "short summary" in text else protected
        return token_estimate.TokenEstimate(tokens, "supplied boundary", True)
    monkeypatch.setattr(token_estimate, "estimate", estimate)


@pytest.mark.parametrize("count,prevented", [(174000, False), (199999, False), (200000, True), (200001, True)])
def test_input_only_soft_boundaries_continue_only_pending_task(config, monkeypatch, install_fake_urlopen,
                                                              count, prevented):
    scripted_estimate(monkeypatch, count)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    calls = install_fake_urlopen((["short summary"] if prevented else []) + ["pending answer"])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending task\n/usage\nexit\n"), output_stream=output, resumed=resumed)
    assert len(calls) == 1 + prevented
    bodies = [json.loads(call["request"].data) for call in calls]
    assert [body["session_id"] for body in bodies] == ([f"{resumed[0]}:compression"] if prevented else []) + [resumed[0]]
    assert bodies[-1]["messages"][-1] == {"role": "user", "content": "pending task"}
    assert bodies[-1]["max_tokens"] == 16000
    assert "224000" in output.getvalue()
    log = entries()
    assert sum(e["type"] == "conversation_compressed" for e in log) == prevented
    assert [e["task"] for e in log if e["type"] == "attempt"] == (["/compress"] if prevented else []) + ["pending task"]
    turns, summary, _, _ = call_log.load_conversation(resumed[0])
    assert len(turns) == (3 if prevented else 4)
    assert summary == ("short summary" if prevented else None)
    if prevented:
        assert "Automatic Compression" in output.getvalue()
        assert "150000" in output.getvalue()
        assert next(i for i, e in enumerate(log) if e["type"] == "conversation_compressed") < len(log) - 2


@pytest.mark.parametrize("total,input_limit,count,reduced,expected_target,prevented", [
    (250003, None, 200001, 150001, 150001, False),
    (250003, None, 200002, 150001, 150001, True),
    (250000, 130000, 120000, 120000, 120000, False),
    (250000, 130000, 120001, 120000, 120000, True),
])
def test_integer_floors_and_independent_input_ceiling(config, monkeypatch, install_fake_urlopen,
                                                    total, input_limit, count, reduced, expected_target, prevented):
    record = {"provider": "openrouter", "model": "vendor/test-model", "total_tokens": total}
    if input_limit:
        record["input_tokens"] = input_limit
    config = replace(config, context_budget_tokens=total, capacity_overrides=(record,))
    scripted_estimate(monkeypatch, count, reduced)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    calls = install_fake_urlopen((["short summary"] if prevented else []) + ["answer"])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\nexit\n"), output_stream=output, resumed=resumed)
    assert len(calls) == 1 + prevented
    assert sum(e["type"] == "conversation_compressed" for e in entries()) == prevented
    if prevented:
        assert f"target {expected_target}" in output.getvalue()


def test_protected_heavy_target_miss_does_not_repeat_on_transient_retry(config, monkeypatch, install_fake_urlopen):
    from urllib.error import HTTPError
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    scripted_estimate(monkeypatch, 220000, reduced=210000, protected=205000)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    calls = install_fake_urlopen([{"content": "short summary", "usage": {"cost": 0.1}},
                                 HTTPError("https://example.invalid", 503, "retry", None, None), "answer"])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/usage\nexit\n"), output_stream=output, resumed=resumed)
    assert len(calls) == 3
    assert [json.loads(call["request"].data)["session_id"] for call in calls] == [
        f"{resumed[0]}:compression", resumed[0], resumed[0]]
    assert json.loads(calls[0]["request"].data)["max_tokens"] == 16000
    assert calls[1]["request"].data == calls[2]["request"].data
    assert "best effort: preserved context" in output.getvalue()
    assert "210000" in output.getvalue() and "unknown" in output.getvalue()
    assert sum(e["type"] == "conversation_compressed" for e in entries()) == 1
    assert call_log.total_cost() == 0.1


@pytest.mark.parametrize("count,blocked", [(200000, False), (224000, False), (224001, True)])
def test_no_eligible_context_proceeds_or_stops_without_synthetic_exchange(config, monkeypatch, install_fake_urlopen,
                                                                       count, blocked):
    scripted_estimate(monkeypatch, count, protected=count)
    calls = install_fake_urlopen("answer")
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/usage\nexit\n"), output_stream=output)
    assert len(calls) == int(not blocked)
    assert "Automatic Compression" not in output.getvalue()
    assert ("locally blocked" in output.getvalue()) == blocked
    assert not any(e["type"] == "conversation_compressed" for e in entries())


def test_older_context_over_twenty_turns_uses_bounded_route_and_complete_source(config, monkeypatch,
                                                                           install_fake_urlopen):
    bounded = {"provider": "openrouter", "model": "vendor/test-model", "total_tokens": 10700, "output_tokens": 100}
    config = replace(config, capacity_overrides=(bounded,))
    scripted_estimate(monkeypatch, 200000, reduced=500, protected=400)
    sid = call_log.start_session(config)
    previous = " ".join(f"prior{i}" for i in range(1200))
    call_log.write_conversation_compressed(previous)
    older = [({"role": "user", "content": "old-context " + " ".join(f"source{i}" for i in range(n * 150, (n + 1) * 150))},)
             for n in range(25)]
    protected = [({"role": "user", "content": "protected one"},), ({"role": "user", "content": "protected two"},)]
    for turn in older + protected:
        call_log.write_turn_end("ok", messages=turn)
    calls = install_fake_urlopen([Repeat("short summary")])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\nexit\n"), output_stream=output,
             resumed=(sid, tuple(older + protected), previous, [], call_log.load_conversation(sid)[3]))
    sources, prior = [], []
    import re
    for call in calls[:-1]:
        body = json.loads(call["request"].data)
        assert body["session_id"] == f"{sid}:compression"
        assert body["model"] == "vendor/test-model"
        assert body["max_tokens"] == 100 and "tools" not in body
        assert fixture_estimate("", {"messages": body["messages"]}).tokens <= 600
        text = body["messages"][1]["content"]
        assert "protected one" not in text and "pending" not in text
        sources.extend(re.findall(r"source\d+", text))
        prior.extend(re.findall(r"prior\d+", text))
    assert len(calls) > 10
    assert sources == [f"source{i}" for i in range(3750)]
    assert prior == [f"prior{i}" for i in range(1200)]
    last = json.loads(calls[-1]["request"].data)
    assert last["model"] == "vendor/test-model"
    assert [m["content"] for m in last["messages"][1:]] == ["protected one", "protected two", "pending"]
    assert call_log.load_conversation(sid)[0][:-1] == tuple(protected)
    assert sum(e["type"] == "conversation_compressed" for e in entries()) == 2


@pytest.mark.parametrize("provider_name", ["openrouter", "openai", "anthropic", "gemini"])
def test_multiple_tool_follow_ups_preserve_pairs_once_and_commit_before_turn_end(config, monkeypatch,
                                                                               install_fake_urlopen, provider_name):
    config = replace(config, provider=provider_name,
                     capacity_overrides=tuple({**record, "provider": provider_name} for record in config.capacity_overrides))
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    measured = []
    def estimate(model, prepared):
        measured.append(prepared)
        if "tools" not in prepared:
            return fixture_estimate(model, prepared)
        text = json.dumps(prepared)
        tokens = 210000 if "old-context" in text and "2+2" in text else 174000 if "old-context" in text else 150000
        return token_estimate.TokenEstimate(tokens, "supplied boundary", True)
    monkeypatch.setattr(token_estimate, "estimate", estimate)
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "first", "name": "calculator", "arguments": {"expression": "2+2"}}]},
        "short summary",
        {"tool_calls": [{"id": "second", "name": "calculator", "arguments": {"expression": "3+3"}}]},
        "answer",
    ])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/usage\nexit\n"), output_stream=output, resumed=resumed)
    assert len(calls) == 4
    bodies = [json.loads(call["request"].data) for call in calls]
    if provider_name == "openrouter":
        assert [body["session_id"] for body in bodies] == [
            resumed[0], f"{resumed[0]}:compression", resumed[0], resumed[0]]
    else:
        assert all("session_id" not in body for body in bodies)
    ordinary = [body for body in bodies if "tools" in body]
    assert len(ordinary) == 3
    for body in ordinary:
        prepared = {key: value for key, value in body.items()
                    if key not in {"model", "max_tokens", "max_completion_tokens", "generationConfig", "provider", "stream", "stream_options", "session_id", "cache_control"}}
        assert sum(candidate == prepared for candidate in measured) == 1
    assert "old-context" not in json.dumps(ordinary[1:])
    assert "short summary" in json.dumps(ordinary[1:])
    turns, summary, _, _ = call_log.load_conversation(resumed[0])
    assert summary == "short summary" and len(turns) == 3
    active = turns[-1]
    assert active[0] == {"role": "user", "content": "pending"}
    assert [m["content"] for m in active if m["role"] == "tool_result"] == [{"result": 4}, {"result": 6}]
    log = entries()
    executions = [e for e in log if e["type"] == "tool_execution"]
    assert [e["arguments"] for e in executions] == [{"expression": "2+2"}, {"expression": "3+3"}]
    assert [e["result"] for e in executions] == [{"result": 4}, {"result": 6}]
    commit_index = next(i for i, e in enumerate(log) if e["type"] == "conversation_compressed")
    final_index = max(i for i, e in enumerate(log) if e["type"] == "turn_end")
    assert commit_index < final_index and log[final_index]["status"] == "ok"
    assert sum(e["type"] == "conversation_compressed" for e in log) == 1
    assert all(e["task"] in {"pending", "/compress"} for e in log if e["type"] == "attempt")


def test_changed_pair_after_exhaustion_rechecks_actual_route_and_uses_new_summary(config, monkeypatch,
                                                                                 install_fake_urlopen):
    from urllib.error import HTTPError
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    smaller = {"provider": "openrouter", "model": "vendor/smaller-model", "total_tokens": 128000}
    config = replace(config, capacity_overrides=(config.capacity_overrides[0], smaller))
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    seen = []
    def estimate(model, prepared):
        if "tools" not in prepared:
            return fixture_estimate(model, prepared)
        tokens = 70000 if "short summary" in json.dumps(prepared) else 100000 if model == "vendor/test-model" else 110000
        seen.append((model, tokens))
        return token_estimate.TokenEstimate(tokens, "actual route fixture", model != "vendor/test-model")
    monkeypatch.setattr(token_estimate, "estimate", estimate)
    failure = HTTPError("https://example.invalid", 503, "retry", None, None)
    calls = install_fake_urlopen([failure, failure, failure, "short summary", "answer", "later answer"])
    run_repl(config, input_stream=StringIO("pending\nexit\n"), output_stream=StringIO(), resumed=resumed)
    changed = replace(config, model="vendor/smaller-model")
    run_repl(changed, input_stream=StringIO("/retry\nlater\n/usage\nexit\n"), output_stream=StringIO(),
             resumed=(resumed[0], *call_log.load_conversation(resumed[0])))
    bodies = [json.loads(call["request"].data) for call in calls]
    assert [body["model"] for body in bodies] == ["vendor/test-model"] * 3 + ["vendor/smaller-model"] * 3
    assert "old-context" not in json.dumps(bodies[-2:])
    assert "short summary" in bodies[-1]["messages"][0]["content"]
    assert seen[:4] == [("vendor/test-model", 100000)] * 3 + [("vendor/smaller-model", 110000)]
    assert ("vendor/smaller-model", 70000) in seen
    assert sum(e["type"] == "conversation_compressed" for e in entries()) == 1


@pytest.mark.parametrize("failure", ["summary", "count", "ceiling", "append", "partial_append", "interrupt", "after_commit"])
def test_mid_task_failures_preserve_tool_evidence_and_transactional_conversation(config, monkeypatch,
                                                                             install_fake_urlopen, failure):
    from urllib.error import HTTPError
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    def estimate(model, prepared):
        if "tools" not in prepared:
            return fixture_estimate(model, prepared)
        text = json.dumps(prepared)
        if "short summary" in text and failure == "count":
            raise ValueError("pending tokenizer failed")
        tokens = (224001 if failure == "ceiling" else 150000) if "short summary" in text else 210000 if "2+2" in text else 174000
        return token_estimate.TokenEstimate(tokens, "fixture", True)
    monkeypatch.setattr(token_estimate, "estimate", estimate)
    if failure in {"append", "partial_append"}:
        inject_append_failure(monkeypatch, partial=failure == "partial_append")
    summary_outcome = KeyboardInterrupt() if failure == "interrupt" else "" if failure == "summary" else "short summary"
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "executed", "name": "calculator", "arguments": {"expression": "2+2"}}]},
        summary_outcome,
        HTTPError("https://example.invalid", 400, "failed pending", None, None),
    ])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/history\n/usage\nexit\n"), output_stream=output, resumed=resumed)
    stops = failure in {"append", "partial_append", "interrupt"}
    assert len(calls) == (2 if stops else 3)
    log = entries()
    executions = [e for e in log if e["type"] == "tool_execution"]
    assert len(executions) == 1
    assert executions[0]["tool_call_id"] == "executed"
    assert executions[0]["arguments"] == {"expression": "2+2"} and executions[0]["result"] == {"result": 4}
    assert sum(e["type"] == "conversation_compressed" for e in log) == int(failure == "after_commit")
    assert [e for e in log if e["type"] == "turn_end"][-1]["status"] == ("interrupted" if failure == "interrupt" else "error")
    expected = (resumed[1][-2:], "short summary", []) if failure == "after_commit" else (resumed[1], None, [])
    assert call_log.load_conversation(resumed[0])[:3] == expected
    assert "Automatic Compression" in output.getvalue()
    assert ("sending the pending exchange" in output.getvalue()) == (failure in {"summary", "count", "ceiling"})
    if failure == "count":
        assert "pending tokenizer failed" in output.getvalue()


def test_interrupt_after_commit_keeps_compression_not_partial_turn(config, monkeypatch, install_fake_urlopen):
    scripted_estimate(monkeypatch, 200000)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    calls = install_fake_urlopen(["short summary", KeyboardInterrupt()])
    run_repl(config, input_stream=StringIO("pending\nexit\n"), output_stream=StringIO(), resumed=resumed)
    assert len(calls) == 2
    assert call_log.load_conversation(resumed[0])[:3] == (resumed[1][-2:], "short summary", [])
    log = entries()
    assert sum(e["type"] == "conversation_compressed" for e in log) == 1
    assert [e for e in log if e["type"] == "turn_end"][-1]["status"] == "interrupted"


@pytest.mark.parametrize("count_failure", [False, True])
def test_real_offline_gemini_rebases_grouped_replay_with_exact_signatures_once(config, monkeypatch, count_failure):
    import socket
    from personal_agent.providers import http
    from tests.fakes import FakeOpenRouterResponse
    network = []
    def deny_network(*args, **kwargs):
        network.append(args)
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    config = replace(config, provider="gemini", capacity_overrides=({
                         "provider": "gemini", "model": "vendor/test-model", "total_tokens": 17000, "output_tokens": 100},))
    older = ({"role": "user", "content": "old-context " + "history " * 3000},)
    sid = call_log.start_session(config)
    protected = (({"role": "user", "content": "protected one"},), (
        {"role": "user", "content": "protected two"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "historic", "name": "calculator", "arguments": {"expression": "1+1"}}]},
        {"role": "tool_result", "id": "historic", "name": "calculator", "content": {"result": 2}},
        {"role": "assistant", "content": "historic answer"},
    ))
    for turn in (older, *protected):
        call_log.write_turn_end("ok", messages=turn)
    first_parts = [
        {"text": "original model text one", "thoughtSignature": "opaque " * 1400},
        {"functionCall": {"name": "calculator", "args": {"expression": "2+2"}, "id": "vendor-first"},
         "thoughtSignature": "exact-call-signature"},
        {"functionCall": {"name": "calculator", "args": {"expression": "4+4"}}},
    ]
    second_parts = [
        {"text": "original model text two", "thoughtSignature": "hidden " * 1400},
        {"functionCall": {"name": "calculator", "args": {"expression": "6+6"}}},
    ]
    calls, before_success = [], []
    responses = iter([first_parts, second_parts, [{"text": "pending answer"}]])
    def fake_http(request, timeout=None):
        body = json.loads(request.data)
        calls.append(body)
        if "tools" in body:
            parts = next(responses)
            if parts == [{"text": "pending answer"}]:
                before_success.append(call_log.load_conversation(sid))
            return FakeOpenRouterResponse({"candidates": [{"content": {"parts": parts}}]})
        return FakeOpenRouterResponse({"candidates": [{"content": {"parts": [{"text": "short summary"}]}}]})
    monkeypatch.setattr(http, "urlopen", fake_http)
    measured = []
    real_estimate = token_estimate.estimate
    def capture(model, prepared):
        if count_failure and "contents" in prepared and "short summary" in json.dumps(prepared):
            raise ValueError("pending candidate counting failed")
        result = real_estimate(model, prepared)
        measured.append((prepared, result, token_estimate.render_input(prepared)))
        return result
    monkeypatch.setattr(token_estimate, "estimate", capture)
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending task\n/usage\nexit\n"), output_stream=output,
             resumed=(sid, (older, *protected), None, [], call_log.load_conversation(sid)[3]))
    ordinary = [body for body in calls if "tools" in body]
    if count_failure:
        assert len(ordinary) == 2 and len(calls) == 3
        assert call_log.load_conversation(sid)[:3] == ((older, *protected), None, [])
        log = entries()
        assert not any(e["type"] == "conversation_compressed" for e in log)
        assert [e["result"] for e in log if e["type"] == "tool_execution"] == [{"result": 4}, {"result": 8}, {"result": 12}]
        assert [e for e in log if e["type"] == "turn_end"][-1]["status"] == "error"
        assert "pending candidate counting failed" in output.getvalue()
        assert network == []
        return
    assert len(ordinary) == 3
    assert len(calls) == 4
    assert "old-context" in json.dumps(ordinary[0]) and "old-context" in json.dumps(ordinary[1]), [
        (result.tokens, "old-context" in rendered, "original model text two" in rendered)
        for prepared, result, rendered in measured if "contents" in prepared]
    last = ordinary[2]
    assert "old-context" not in json.dumps(last)
    assert "short summary" in last["systemInstruction"]["parts"][0]["text"]
    active_start = next(i for i, content in enumerate(last["contents"]) if content["parts"] == [{"text": "pending task"}])
    active = last["contents"][active_start:]
    assert len(active) == 5
    assert active[1] == {"role": "model", "parts": first_parts}
    assert active[3] == {"role": "model", "parts": second_parts}
    assert active[2]["parts"] == [
        {"functionResponse": {"name": "calculator", "response": {"result": 4}, "id": "vendor-first"}},
        {"functionResponse": {"name": "calculator", "response": {"result": 8}}},
    ]
    assert active[4]["parts"] == [{"functionResponse": {"name": "calculator", "response": {"result": 12}}}]
    for body in ordinary:
        prepared = {key: value for key, value in body.items() if key != "generationConfig"}
        records = [(result, rendered) for candidate, result, rendered in measured if candidate == prepared]
        assert len(records) == 1
        result, rendered = records[0]
        assert result.generic and result.encoding == "cl100k_base" and result.tokens <= 6900
        assert json.loads(rendered) == prepared
        assert body["generationConfig"]["maxOutputTokens"] == 100
    final_prepared = {key: value for key, value in last.items() if key != "generationConfig"}
    rendered = next(rendered for candidate, _, rendered in measured if candidate == final_prepared)
    assert rendered.count("original model text one") == rendered.count("original model text two") == 1
    assert rendered.count("exact-call-signature") == 1
    assert [item[:3] for item in before_success] == [(protected, "short summary", [])]
    restored = call_log.load_conversation(sid)
    assert restored[0][:-1] == protected and restored[1] == "short summary"
    executions = [e for e in entries() if e["type"] == "tool_execution"]
    assert [e["tool_call_id"] for e in executions] == ["vendor-first", "gemini-call-2", "gemini-call-1"]
    assert [e["result"] for e in executions] == [{"result": 4}, {"result": 8}, {"result": 12}]
    assert network == []


@pytest.mark.parametrize("source", ["task", "memory", "skill", "schema", "result"])
def test_hard_overflow_never_discards_protected_input_or_commits_candidate(config, monkeypatch,
                                                                       install_fake_urlopen, tmp_path, source):
    from personal_agent.providers.contract import ToolDef
    from personal_agent.tools import registry, workspace
    from tests.test_workspace_skills import _skill
    workspace.configure_workspace(tmp_path)
    marker = "hard-overflow " * 400
    script = ""
    memory = [{"text": marker}] if source == "memory" else []
    task = marker if source == "task" else "pending"
    if source == "skill":
        _skill(tmp_path, "overflow", body=marker)
        script = "/skill overflow\n"
    if source == "schema":
        monkeypatch.setattr(registry, "definitions_for_mode", lambda *_: (ToolDef(
            "calculator", "calculator", {"type": "object", "description": marker}),))
    if source == "result":
        (tmp_path / "large.txt").write_text(marker)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    seen = []
    def estimate(model, prepared):
        if "tools" not in prepared:
            return fixture_estimate(model, prepared)
        text = json.dumps(prepared)
        seen.append(text)
        tokens = 250000 if "hard-overflow" in text and "old-context" in text else 240000 if "hard-overflow" in text else 174000
        return token_estimate.TokenEstimate(tokens, "fixture", True)
    monkeypatch.setattr(token_estimate, "estimate", estimate)
    outcomes = ([{"tool_calls": [{"id": "read-once", "name": "read_file", "arguments": {"path": "large.txt"}}]}]
                if source == "result" else []) + ["short summary"]
    calls = install_fake_urlopen(outcomes)
    output = StringIO()
    run_repl(config, input_stream=StringIO(script + task + "\n/usage\nexit\n"), output_stream=output,
             resumed=resumed, memory_notes=memory)
    assert len(calls) == (2 if source == "result" else 1)
    assert "preserved input 240000 exceeds input ceiling 224000" in output.getvalue()
    assert "locally blocked" in output.getvalue()
    assert any("short summary" in text and "hard-overflow" in text for text in seen)
    assert call_log.load_conversation(resumed[0])[:3] == (resumed[1], None, [])
    log = entries()
    assert not any(e["type"] == "conversation_compressed" for e in log)
    executions = [e for e in log if e["type"] == "tool_execution"]
    assert len(executions) == int(source == "result")
    if executions:
        assert executions[0]["tool_call_id"] == "read-once"
        assert "hard-overflow" in executions[0]["result"]["content"]


@pytest.mark.parametrize("interactive", [False, True])
def test_compression_and_retry_do_not_repeat_mutating_tool_apply_or_confirmation(config, monkeypatch,
                                                                              install_fake_urlopen, tmp_path, interactive):
    from urllib.error import HTTPError
    from personal_agent.tools import workspace
    workspace.configure_workspace(tmp_path)
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    monkeypatch.delenv("NO_COLOR", raising=False)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    def estimate(model, prepared):
        if "tools" not in prepared:
            return fixture_estimate(model, prepared)
        text = json.dumps(prepared)
        tokens = 220000 if "old-context" in text and "bytes_written" in text else 174000 if "old-context" in text else 210000
        return token_estimate.TokenEstimate(tokens, "fixture", True)
    monkeypatch.setattr(token_estimate, "estimate", estimate)
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "write-once", "name": "write", "arguments": {"path": "effect.txt", "content": "effect"}}]},
        "short summary", HTTPError("https://example.invalid", 503, "transient", None, None), "answer",
    ])
    class Output(StringIO):
        def isatty(self):
            return interactive
    output = Output()
    run_repl(config, input_stream=StringIO("pending\ny\nexit\n"), output_stream=output, resumed=resumed)
    assert len(calls) == 4
    assert calls[2]["request"].data == calls[3]["request"].data
    assert (tmp_path / "effect.txt").read_text() == "effect"
    assert output.getvalue().count("Apply this change? [y/N]") == 1
    assert output.getvalue().count("Automatic Compression completed") == 1
    log = entries()
    executions = [e for e in log if e["type"] == "tool_execution"]
    assert len(executions) == 1 and executions[0]["result"] == {"path": "effect.txt", "bytes_written": 6, "created": True}
    assert sum(e["type"] == "conversation_compressed" for e in log) == 1


@pytest.mark.parametrize("after_commit", [False, True])
def test_mid_task_detail_failure_is_fatal_without_later_actions(config, monkeypatch, install_fake_urlopen, after_commit):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    scripted_estimate(monkeypatch, 200000)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    calls = install_fake_urlopen([Repeat("short summary")])
    original_write = call_log.write_detail
    def fail_detail(kind, **fields):
        if (not after_commit and kind == "attempt_end") or (after_commit and kind == "attempt_start" and fields["tools"]):
            raise call_log.AuditError("detail failed")
        return original_write(kind, **fields)
    monkeypatch.setattr(call_log, "write_detail", fail_detail)
    with pytest.raises(call_log.AuditError, match="detail failed"):
        run_repl(config, input_stream=StringIO("pending\nlater\nexit\n"), output_stream=StringIO(), resumed=resumed)
    assert len(calls) == 1
    expected = (resumed[1][-2:], "short summary", []) if after_commit else (resumed[1], None, [])
    assert call_log.load_conversation(resumed[0])[:3] == expected
    assert len([e for e in entries() if e["type"] == "turn_end"]) == 3


def test_active_todo_baseline_and_resume_undo_clear_match_committed_live_state(config, monkeypatch, install_fake_urlopen):
    from personal_agent.tools import todo
    old = [{"content": "old todo", "status": "pending"}]
    recent = [{"content": "recent todo", "status": "completed"}]
    active = [{"content": "active todo", "status": "in_progress"}]
    older = ({"role": "user", "content": "old-context " * 300},
             {"role": "tool_result", "id": "old", "name": "todo", "content": {"todos": old}})
    sid = call_log.start_session(config)
    protected = (({"role": "user", "content": "protected one"},), (
        {"role": "user", "content": "protected two"},
        {"role": "tool_result", "id": "recent", "name": "todo", "content": {"todos": recent}},
    ))
    for turn in (older, *protected):
        call_log.write_turn_end("ok", messages=turn)
    def estimate(model, prepared):
        if "tools" not in prepared:
            return fixture_estimate(model, prepared)
        text = json.dumps(prepared)
        tokens = 210000 if "old-context" in text and "active todo" in text else 174000 if "old-context" in text else 150000
        return token_estimate.TokenEstimate(tokens, "fixture", True)
    monkeypatch.setattr(token_estimate, "estimate", estimate)
    calls = install_fake_urlopen([{"tool_calls": [{"id": "active", "name": "todo", "arguments": {"todos": active}}]},
                                 "short summary", "answer"])
    run_repl(config, input_stream=StringIO("pending\nexit\n"), output_stream=StringIO(),
             resumed=(sid, (older, *protected), None, [], call_log.load_conversation(sid)[3]))
    bodies = [json.loads(call["request"].data) for call in calls]
    assert "active todo" in bodies[-1]["messages"][0]["content"]
    assert "active todo" not in json.dumps(bodies[1])
    restored = call_log.load_conversation(sid)
    assert restored[1:3] == ("short summary", old)
    assert todo.current_list(restored[0], restored[2]) == active
    run_repl(config, input_stream=StringIO("/undo\nexit\n"), output_stream=StringIO(), resumed=(sid, *restored))
    undone = call_log.load_conversation(sid)
    assert undone[:3] == (protected, "short summary", old)
    assert todo.current_list(undone[0], undone[2]) == recent
    run_repl(config, input_stream=StringIO("/undo\nexit\n"), output_stream=StringIO(), resumed=(sid, *undone))
    undone = call_log.load_conversation(sid)
    assert undone[:3] == (protected[:1], "short summary", old)
    assert todo.current_list(undone[0], undone[2]) == old
    run_repl(config, input_stream=StringIO("/clear\nexit\n"), output_stream=StringIO(), resumed=(sid, *undone))
    assert call_log.load_conversation(sid)[:3] == ((), None, [])


def test_gemini_initial_replay_construction_failure_stops_locally(config, monkeypatch, install_fake_urlopen):
    from personal_agent.providers import gemini
    config = replace(config, provider="gemini")
    resumed = seed(config, ({"role": "user", "content": "prior context"},))
    def cannot_prepare(history):
        raise ValueError("cannot prepare historical replay")
    monkeypatch.setattr(gemini, "begin_replay", cannot_prepare)
    calls = install_fake_urlopen("unused")
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/usage\nexit\n"), output_stream=output, resumed=resumed)
    assert calls == []
    assert "cannot prepare historical replay" in output.getvalue()
    assert "locally blocked" in output.getvalue()
    assert call_log.load_conversation(resumed[0])[:3] == (resumed[1], None, [])


def test_summary_only_conversation_at_soft_trigger_sends_without_compression(config, monkeypatch, install_fake_urlopen):
    scripted_estimate(monkeypatch, 210000)
    previous = "old-context " * 300
    sid = call_log.start_session(config)
    call_log.write_conversation_compressed(previous)
    protected = (({"role": "user", "content": "protected one"},), ({"role": "user", "content": "protected two"},))
    for turn in protected:
        call_log.write_turn_end("ok", messages=turn)
    calls = install_fake_urlopen(["answer"])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\nexit\n"), output_stream=output,
             resumed=(sid, protected, previous, [], call_log.load_conversation(sid)[3]))
    assert len(calls) == 1
    assert "Automatic Compression" not in output.getvalue()
    assert sum(e["type"] == "conversation_compressed" for e in entries()) == 1
    assert call_log.load_conversation(sid)[1] == previous


def test_soft_trigger_failure_sends_unchanged_pending_exchange_without_rerunning_on_retry(
        config, monkeypatch, install_fake_urlopen):
    from urllib.error import HTTPError
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    scripted_estimate(monkeypatch, 210000, reduced=210000)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    calls = install_fake_urlopen([{"content": "short summary", "usage": {"cost": 0.1}},
                                 HTTPError("https://example.invalid", 503, "retry", None, None), "answer"])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/history\n/usage\nexit\n"), output_stream=output,
             resumed=resumed)
    assert len(calls) == 3
    bodies = [json.loads(call["request"].data) for call in calls]
    assert "Summarize the conversation" in bodies[0]["messages"][1]["content"]
    assert calls[1]["request"].data == calls[2]["request"].data
    assert "short summary" not in json.dumps(bodies[1:]) and "old-context" in json.dumps(bodies[1])
    text = output.getvalue()
    assert "did not reduce the pending request" in text
    assert "prior Conversation retained, sending the pending exchange" in text
    assert "stopped" not in text and "Automatic Compression completed" not in text
    log = entries()
    assert sum(e["type"] == "conversation_compressed" for e in log) == 0
    assert [e["task"] for e in log if e["type"] == "attempt"] == ["/compress", "pending", "pending"]
    assert call_log.total_cost() == 0.1
    turns, summary, _, _ = call_log.load_conversation(resumed[0])
    assert turns[:-1] == resumed[1] and summary is None


def test_previous_summary_is_eligible_without_older_complete_turns(config, monkeypatch, install_fake_urlopen):
    scripted_estimate(monkeypatch, 224001)
    sid = call_log.start_session(config)
    previous = "old-context " * 300
    call_log.write_conversation_compressed(previous)
    protected = (({"role": "user", "content": "protected one"},), ({"role": "user", "content": "protected two"},))
    for turn in protected:
        call_log.write_turn_end("ok", messages=turn)
    calls = install_fake_urlopen(["short summary", "answer"])
    run_repl(config, input_stream=StringIO("pending\nexit\n"), output_stream=StringIO(),
             resumed=(sid, protected, previous, [], call_log.load_conversation(sid)[3]))
    assert len(calls) == 2
    summary_input = json.loads(calls[0]["request"].data)["messages"][1]["content"]
    assert previous in summary_input and "Source: Previous summary" in summary_input
    assert "protected one" not in summary_input and "protected two" not in summary_input
    turns, summary, baseline, _ = call_log.load_conversation(sid)
    assert turns[:-1] == protected and summary == "short summary" and baseline == []
    assert sum(e["type"] == "conversation_compressed" for e in entries()) == 2


@pytest.mark.parametrize("failure", [OSError("disk full"), call_log.PersistenceError("restore failed")])
def test_soft_trigger_summarization_attempt_persistence_failure_does_not_dispatch(
        config, monkeypatch, install_fake_urlopen, failure):
    scripted_estimate(monkeypatch, 210000, reduced=100000)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    original = call_log.append_entry
    def failing_append(**fields):
        if fields["task"] == "/compress":
            raise failure
        return original(**fields)
    monkeypatch.setattr(call_log, "append_entry", failing_append)
    calls = install_fake_urlopen(["short summary", "answer"])
    with pytest.raises(call_log.PersistenceError):
        run_repl(config, input_stream=StringIO("pending\nexit\n"),
                 output_stream=StringIO(), resumed=resumed)
    assert len(calls) == 1
    assert "Summarize the conversation" in json.loads(calls[0]["request"].data)["messages"][1]["content"]


@pytest.mark.parametrize("path", ["manual", "above_ceiling", "recovery"])
def test_summarization_attempt_persistence_failure_is_fatal_on_every_caller(
        config, monkeypatch, install_fake_urlopen, path):
    from tests.test_context_overflow import rejection
    scripted_estimate(monkeypatch, 230000 if path == "above_ceiling" else 174000, reduced=100000)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    original = call_log.append_entry
    def failing_append(**fields):
        if fields["task"] == "/compress":
            raise OSError("disk full")
        return original(**fields)
    monkeypatch.setattr(call_log, "append_entry", failing_append)
    calls = install_fake_urlopen(([rejection()] if path == "recovery" else []) + ["short summary", "answer"])
    script = "/compress\nexit\n" if path == "manual" else "pending\nexit\n"
    with pytest.raises(call_log.PersistenceError):
        run_repl(config, input_stream=StringIO(script), output_stream=StringIO(),
                 resumed=resumed)
    assert len(calls) == (2 if path == "recovery" else 1)
    assert "Summarize the conversation" in json.loads(calls[-1]["request"].data)["messages"][1]["content"]
    assert call_log.load_conversation(resumed[0])[:3] == (resumed[1], None, [])
    assert not any(e["type"] == "conversation_compressed" for e in entries())
