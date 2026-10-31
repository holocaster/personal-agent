import json
import re
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from personal_agent import call_log, context_budget, token_estimate
from personal_agent.routing import runtime_config
from personal_agent.terminal.repl import run_repl
from tests.fakes import FakeOpenRouterResponse, Repeat


def fixture_estimate(model, prepared):
    return token_estimate.TokenEstimate(len(re.findall(r"\w+|[^\w\s]", json.dumps(prepared))), "fixture", True)


def seed(config, older, previous=None):
    sid = call_log.start_session(config)
    turns = (older, ({"role": "user", "content": "protected one"},),
             ({"role": "user", "content": "protected two"},))
    if previous is not None:
        call_log.write_conversation_compressed(previous)
    for turn in turns:
        call_log.write_turn_end("ok", messages=turn)
    return sid, turns, previous, [], call_log.load_conversation(sid)[3]


def entries():
    return [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]


def test_manual_large_old_turn_is_bounded_and_committed_once(route_env, monkeypatch, install_fake_urlopen):
    monkeypatch.setattr(token_estimate, "estimate", fixture_estimate)
    monkeypatch.setattr(context_budget, "model_info", lambda *_: {})
    config = replace(runtime_config.load(), capacity_overrides=({"provider": "openrouter",
        "model": "vendor/test-model", "total_tokens": 10700, "output_tokens": 100},))
    text = " ".join(f"source{i}" for i in range(5000))
    resumed = seed(config, ({"role": "user", "content": text},))
    calls = install_fake_urlopen([Repeat({"content": " ".join(f"fact{i}" for i in range(90)),
                                         "usage": {"cost": 0.1}})])
    output = StringIO()
    run_repl(config, input_stream=StringIO("/compress\n/history\n/usage\nexit\n"),
             output_stream=output, resumed=resumed)
    assert "Compressed 1 turn." in output.getvalue()
    assert len(calls) > 5
    seen = []
    for call in calls:
        body = json.loads(call["request"].data)
        assert body["session_id"] == f"{resumed[0]}:compression"
        assert body["model"] == "vendor/test-model"
        assert "tools" not in body
        assert body["max_tokens"] <= 100
        assert fixture_estimate("", {"messages": body["messages"]}).tokens <= 600
        seen.extend(re.findall(r"source\d+", body["messages"][1]["content"]))
        assert "protected one" not in body["messages"][1]["content"]
    assert seen == [f"source{i}" for i in range(5000)]
    log = entries()
    assert sum(e["type"] == "conversation_compressed" for e in log) == 1
    assert sum(e["type"] == "turn_end" for e in log) == 3
    assert [e["attempt"] for e in log if e["type"] == "attempt"] == list(range(1, len(calls) + 1))
    assert call_log.total_cost() == pytest.approx(len(calls) * 0.1)
    turns, summary, baseline, _ = call_log.load_conversation(resumed[0])
    assert turns == resumed[1][-2:]
    assert summary.startswith("fact0")
    assert baseline == []


@pytest.fixture
def bounded_config(route_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-anthropic-key")
    monkeypatch.setattr(token_estimate, "estimate", fixture_estimate)
    monkeypatch.setattr(context_budget, "model_info", lambda *_: {})
    return replace(runtime_config.load(), capacity_overrides=({"provider": "openrouter",
        "model": "vendor/test-model", "total_tokens": 10700, "output_tokens": 100},))


def large_turn():
    return ({"role": "user", "content": " ".join(f"source{i}" for i in range(5000))},)


def seed_summary_and_todos(config, older):
    sid = call_log.start_session(config)
    baseline = [{"content": "prior todo", "status": "pending"}]
    call_log.write_turn_end("ok", messages=(
        {"role": "user", "content": "prior task"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "prior-todo", "name": "todo", "arguments": {"todos": baseline}},
        ]},
        {"role": "tool_result", "id": "prior-todo", "name": "todo", "content": {"todos": baseline}},
        {"role": "assistant", "content": "prior answer"},
    ))
    for turn in (older, ({"role": "user", "content": "eligible task"},
                         {"role": "assistant", "content": "eligible answer"})):
        call_log.write_turn_end("ok", messages=turn)
    call_log.write_conversation_compressed("prior summary " * 100)
    for name in ("protected one", "protected two"):
        call_log.write_turn_end("ok", messages=(
            {"role": "user", "content": name}, {"role": "assistant", "content": name + " answer"},
        ))
    return (sid, *call_log.load_conversation(sid))


def anthropic_summary(text, stop_reason="end_turn", usage=True):
    payload = {"content": [{"type": "text", "text": text}], "stop_reason": stop_reason}
    if usage:
        payload["usage"] = {"input_tokens": 91, "cache_read_input_tokens": 15,
                            "cache_creation_input_tokens": 5, "output_tokens": 7}
    return FakeOpenRouterResponse(payload)


@pytest.mark.parametrize("stage", ["first", "later", "combination"])
@pytest.mark.parametrize("stop_reason,error", [("model_context_window_exceeded", "context-truncated"),
                                             ("max_tokens", "length-truncated")])
@pytest.mark.parametrize("usage", [True, False])
def test_manual_anthropic_truncated_summary_preserves_state(bounded_config, monkeypatch,
                                                          stage, stop_reason, error, usage):
    from personal_agent import cost
    from personal_agent.providers import anthropic, http
    from personal_agent.tools import todo
    config = replace(bounded_config, provider="anthropic",
                     capacity_overrides=({**bounded_config.capacity_overrides[0], "provider": "anthropic"},))
    pricing = []
    def estimate_cost(model, prompt, completion, **cache):
        assert cache == {"provider": "anthropic", "cached_tokens": 15 if prompt is not None else 0,
                         "cache_write_tokens": 5 if prompt is not None else 0, "cache_creation_token_details": None}
        pricing.append((model, prompt, completion))
        return 0.1 if prompt is not None and completion is not None else None
    monkeypatch.setattr(cost, "estimate", estimate_cost)
    resumed = seed_summary_and_todos(config, large_turn() + ({"role": "assistant", "content": "old answer"},))
    before = StringIO()
    run_repl(config, input_stream=StringIO("/history\nexit\n"), output_stream=before, resumed=resumed)
    calls, failures = [], []
    good_text = " ".join(f"fact{i}" for i in range(90))
    def post(request, timeout=None):
        assert not failures, "no dispatch after an unfinished summary"
        assert request.full_url == anthropic.API_URL
        body = json.loads(request.data)
        calls.append(body)
        data = body["messages"][0]["content"]
        failing = (stage == "first" or stage == "later" and len(calls) == 2
                   or stage == "combination" and "[Source: Summary " in data)
        if failing:
            failures.append(len(calls))
        return anthropic_summary("short summary" if failing else good_text,
                                 stop_reason if failing else "end_turn", usage if failing else True)
    monkeypatch.setattr(http, "urlopen", post)
    probes = []
    def estimate_input(model, prepared):
        if prepared.get("tools") and prepared["messages"][-1] == {"role": "user", "content": "state probe"}:
            assert model == "vendor/test-model"
            assert prepared["messages"][:-1] == anthropic.prepare_input(
                "", [message for turn in resumed[1] for message in turn])["messages"]
            assert f"Conversation Summary of earlier turns:\n{resumed[2]}" in prepared["system"]
            assert "Todo List:\n- [pending] prior todo" in prepared["system"]
            probes.append(prepared)
            assert sum(e["type"] == "turn_end" for e in entries()) == 4 + len(probes)
            raise ValueError("state probe complete; no dispatch")
        return fixture_estimate(model, prepared)
    monkeypatch.setattr(token_estimate, "estimate", estimate_input)
    output = StringIO()
    run_repl(config, input_stream=StringIO("/compress\n/history\n/usage\nstate probe\nexit\n"),
             output_stream=output, resumed=resumed)
    assert f"Error: the summary answer was {error}" in output.getvalue()
    assert "Compressed" not in output.getvalue()
    assert failures == [len(calls)]
    if stage == "combination":
        assert len(calls) > 2
    else:
        assert len(calls) == (1 if stage == "first" else 2)
    for body in calls:
        assert "tools" not in body and body["model"] == "vendor/test-model"
        assert body["max_tokens"] == 100
        assert fixture_estimate("", {key: body[key] for key in ("system", "messages")}).tokens <= 600
        assert "Summarize the conversation" in body["messages"][0]["content"]
        assert "protected one" not in body["messages"][0]["content"]
        assert "protected two" not in body["messages"][0]["content"]
    restored = call_log.load_conversation(resumed[0])
    assert restored[:3] == resumed[1:4]
    assert todo.current_list(restored[0], restored[2]) == [{"content": "prior todo", "status": "pending"}]
    history = before.getvalue().split("\n", 3)[3]
    assert history in output.getvalue()
    assert sum(e["type"] == "conversation_compressed" for e in entries()) == 1
    ends = [e for e in entries() if e["type"] == "turn_end"]
    assert len(ends) == 6 and ends[-1]["status"] == "error" and "state probe complete" in ends[-1]["error"]
    assert len(probes) == 1
    attempts = [e for e in entries() if e["type"] == "attempt"]
    assert [e["attempt"] for e in attempts] == list(range(1, len(calls) + 1))
    assert all(e["task"] == "/compress" and e["provider"] == "anthropic"
               and e["ok"] and e["error"] is None and e["cost_estimated"] for e in attempts)
    assert attempts[-1]["answer"] == "short summary"
    known = attempts if usage else attempts[:-1]
    assert all((e["prompt_tokens"], e["completion_tokens"], e["cost"]) == (111, 7, 0.1) for e in known)
    if not usage:
        assert all(attempts[-1][field] is None for field in ("prompt_tokens", "completion_tokens", "cost"))
    assert pricing == [("vendor/test-model", 111, 7)] * len(known) + (
        [] if usage else [("vendor/test-model", None, None)])
    assert call_log.total_cost() == pytest.approx(len(known) * 0.1)
    assert "No ordinary exchange assessed" in output.getvalue()
    after = StringIO()
    run_repl(config, input_stream=StringIO("/history\nstate probe\nexit\n"), output_stream=after,
             resumed=(resumed[0], *call_log.load_conversation(resumed[0])))
    assert after.getvalue().startswith(before.getvalue())
    assert call_log.load_conversation(resumed[0])[:3] == resumed[1:4]
    assert len(probes) == 2 and probes[0] == probes[1]
    assert failures == [len(calls)]


def test_manual_anthropic_complete_summary_is_committed(bounded_config, monkeypatch, install_fake_urlopen):
    from personal_agent import cost
    from personal_agent.tools import todo
    config = replace(bounded_config, provider="anthropic",
                     capacity_overrides=({**bounded_config.capacity_overrides[0], "provider": "anthropic"},))
    monkeypatch.setattr(cost, "estimate", lambda *args, **kwargs: 0.1)
    resumed = seed_summary_and_todos(config, large_turn() + ({"role": "assistant", "content": "old answer"},))
    calls = install_fake_urlopen([Repeat(anthropic_summary("short summary"))])
    output = StringIO()
    run_repl(config, input_stream=StringIO("/compress\n/history\nexit\n"), output_stream=output,
             resumed=resumed)
    assert "Compressed 2 turns." in output.getvalue()
    assert "Error:" not in output.getvalue() and len(calls) > 2
    expected = (resumed[1][-2:], "short summary", resumed[3])
    assert call_log.load_conversation(resumed[0])[:3] == expected
    assert todo.current_list(expected[0], expected[2]) == resumed[3]
    assert sum(e["type"] == "conversation_compressed" for e in entries()) == 2
    assert sum(e["type"] == "turn_end" for e in entries()) == 5
    assert call_log.total_cost() == pytest.approx(len(calls) * 0.1)


def test_anthropic_context_generation_stop_does_not_change_ordinary_answer_policy(
    bounded_config, monkeypatch, install_fake_urlopen
):
    from personal_agent import cost
    config = replace(bounded_config, provider="anthropic",
                     capacity_overrides=({"provider": "anthropic", "model": "vendor/test-model",
                                          "total_tokens": 250000},))
    monkeypatch.setattr(cost, "estimate", lambda *args, **kwargs: 0.1)
    calls = install_fake_urlopen([anthropic_summary("ordinary answer", "model_context_window_exceeded")])
    output = StringIO()
    run_repl(config, input_stream=StringIO("ordinary task\nexit\n"), output_stream=output)
    assert "llm> ordinary answer" in output.getvalue() and "Error:" not in output.getvalue()
    assert len(calls) == 1 and "tools" in json.loads(calls[0]["request"].data)
    assert not any(e["type"] == "conversation_compressed" for e in entries())
    assert [e for e in entries() if e["type"] == "turn_end"][-1]["status"] == "ok"
    assert call_log.load_conversation(call_log.current_session_id())[:3] == (((
        {"role": "user", "content": "ordinary task"}, {"role": "assistant", "content": "ordinary answer"},
    ),), None, [])


@pytest.mark.parametrize("failure_at", [2, 7, 12, 15])
@pytest.mark.parametrize("failure", ["http", "empty", "interrupted", "nonreducing"])
def test_failed_block_or_combination_preserves_conversation(bounded_config, install_fake_urlopen,
                                                           failure_at, failure):
    from urllib.error import HTTPError
    failures = {"http": HTTPError("https://example.invalid", 400, "bad request", None, None),
                "empty": "", "interrupted": KeyboardInterrupt(), "nonreducing": "word " * 1000}
    good = {"content": " ".join(f"fact{i}" for i in range(90)), "usage": {"cost": 0.1}}
    calls = install_fake_urlopen([good] * (failure_at - 1) + [failures[failure]])
    resumed = seed(bounded_config, large_turn())
    output = StringIO()
    run_repl(bounded_config, input_stream=StringIO("/compress\n/history\nexit\n"),
             output_stream=output, resumed=resumed)
    assert "Error:" in output.getvalue()
    assert "Compressed" not in output.getvalue()
    assert "source4999" in output.getvalue()
    assert len(calls) == failure_at
    assert call_log.load_conversation(resumed[0])[:3] == (resumed[1], None, [])
    assert not any(e["type"] == "conversation_compressed" for e in entries())
    attempts = [e for e in entries() if e["type"] == "attempt"]
    assert [e["attempt"] for e in attempts] == list(range(1, failure_at + 1))
    assert all(e["task"] == "/compress" for e in attempts)
    if failure == "interrupted":
        assert not attempts[-1]["ok"]
        assert "KeyboardInterrupt" in attempts[-1]["error"]
        assert all(attempts[-1][field] is None for field in (
            "cost", "prompt_tokens", "completion_tokens", "cached_tokens", "cache_write_tokens",
            "answer", "tool_calls"))
    assert call_log.total_cost() == pytest.approx((failure_at - 1) * 0.1)


@pytest.mark.parametrize("failure_at", [2, 15], ids=["middle-block", "combination"])
@pytest.mark.parametrize("transport", ["response", "http"])
@pytest.mark.parametrize("status", [400, 503])
def test_failed_summary_attempts_retain_reported_usage(bounded_config, monkeypatch, install_fake_urlopen,
                                                     failure_at, transport, status):
    from io import BytesIO
    from urllib.error import HTTPError
    from personal_agent.routing import router
    from tests.fakes import FakeOpenRouterResponse
    from tests.test_context_overflow import choice_rejection

    monkeypatch.setattr(router, "_sleep", lambda _: None)
    failure = choice_rejection({"code": status, "message": "Provider failed"})
    failure["usage"] = {"cost": 0.2, "prompt_tokens": 111, "completion_tokens": 7}
    if transport == "http":
        failure = {"error": failure["choices"][0]["error"], "usage": failure["usage"]}
    retries = 3 if status == 503 else 1
    failures = [HTTPError("https://example.invalid", status, "failed", {}, BytesIO(json.dumps(failure).encode()))
                if transport == "http" else FakeOpenRouterResponse(failure) for _ in range(retries)]
    good = {"content": " ".join(f"fact{i}" for i in range(90)), "usage": {"cost": 0.1}}
    calls = install_fake_urlopen([good] * (failure_at - 1) + failures)
    resumed = seed(bounded_config, large_turn())
    output = StringIO()
    run_repl(bounded_config, input_stream=StringIO("/compress\n/history\n/usage\nexit\n"),
             output_stream=output, resumed=resumed)
    assert len(calls) == failure_at - 1 + retries
    expected_cost = (failure_at - 1) * 0.1 + retries * 0.2
    assert call_log.total_cost() == pytest.approx(expected_cost)
    assert call_log.total_cost() == pytest.approx(expected_cost)
    attempts = [e for e in entries() if e["type"] == "attempt"]
    assert [e["attempt"] for e in attempts] == list(range(1, len(calls) + 1))
    assert all(not e["ok"] and e["cost"] == 0.2 and e["prompt_tokens"] == 111 and e["completion_tokens"] == 7
               and e["answer"] is None and e["tool_calls"] is None for e in attempts[-retries:])
    assert call_log.load_conversation(resumed[0])[:3] == (resumed[1], None, [])
    assert not any(e["type"] == "conversation_compressed" for e in entries())
    assert "No ordinary exchange assessed" in output.getvalue()
    assert "Compressed" not in output.getvalue() and "partial output" not in output.getvalue()


@pytest.mark.parametrize("failure_at", [2, 15], ids=["middle-block", "combination"])
@pytest.mark.parametrize("audit_failure", [False, True])
def test_interrupted_compression_records_attempt_and_closes_audit_or_halts(
    bounded_config, monkeypatch, install_fake_urlopen, failure_at, audit_failure
):
    baseline = [{"content": "prior todo", "status": "pending"}]
    sid, *_ = seed(bounded_config, (
        {"role": "user", "content": "prior task"},
        {"role": "tool_result", "id": "prior-todo", "name": "todo", "content": {"todos": baseline}},
    ))
    call_log.write_conversation_compressed("prior summary")
    for turn in (large_turn(), ({"role": "user", "content": "latest one"},),
                 ({"role": "user", "content": "latest two"},)):
        call_log.write_turn_end("ok", messages=turn)
    original = call_log.load_conversation(sid)
    assert original[1:3] == ("prior summary", baseline)
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    monkeypatch.setenv("TAVILY_API_KEY", "prior-key")
    good = {"content": "test-key prior-key " + " ".join(f"fact{i}" for i in range(90)),
            "usage": {"cost": 0.1, "prompt_tokens": 240, "completion_tokens": 90,
                      "prompt_tokens_details": {"cached_tokens": 30, "cache_write_tokens": 5}}}
    calls = install_fake_urlopen([good] * (failure_at - 1) + [KeyboardInterrupt("test-key prior-key")])
    original_write = call_log.write_detail
    def failing_detail(kind, **fields):
        if audit_failure and kind == "attempt_end" and fields["outcome"] == "interrupted":
            raise call_log.AuditError("interrupted audit unavailable")
        return original_write(kind, **fields)
    monkeypatch.setattr(call_log, "write_detail", failing_detail)
    output = StringIO()
    script = "/compress\nnext task\nexit\n" if audit_failure else "/compress\n/history\nexit\n"
    if audit_failure:
        with pytest.raises(call_log.AuditError, match="interrupted audit unavailable"):
            run_repl(bounded_config, input_stream=StringIO(script), output_stream=output,
                     resumed=(sid, *original))
    else:
        run_repl(bounded_config, input_stream=StringIO(script), output_stream=output,
                 resumed=(sid, *original))
        assert "Error: Interrupted." in output.getvalue()
        assert "prior summary" in output.getvalue() and "source4999" in output.getvalue()
    assert "Compressed" not in output.getvalue()
    assert len(calls) == failure_at
    interrupted_input = json.loads(calls[-1]["request"].data)["messages"][1]["content"]
    assert ("[Source: Summary" if failure_at == 15 else "[Source: Turn") in interrupted_input
    assert call_log.load_conversation(sid)[:3] == original[:3]
    log = entries()
    assert sum(e["type"] == "conversation_compressed" for e in log) == 1
    assert sum(e["type"] == "turn_end" for e in log) == 6
    attempts = [e for e in log if e["type"] == "attempt"]
    assert [e["attempt"] for e in attempts] == list(range(1, failure_at + 1))
    assert all(e["task"] == "/compress" and e["model"] == "vendor/test-model" for e in attempts)
    assert all(e["ok"] and e["cost"] == 0.1 and e["prompt_tokens"] == 240
               and e["completion_tokens"] == 90 and e["cached_tokens"] == 30
               and e["cache_write_tokens"] == 5 for e in attempts[:-1])
    assert not attempts[-1]["ok"] and "KeyboardInterrupt" in attempts[-1]["error"]
    assert all(attempts[-1][field] is None for field in (
        "cost", "prompt_tokens", "completion_tokens", "cached_tokens", "cache_write_tokens", "answer", "tool_calls"))
    assert call_log.total_cost() == pytest.approx((failure_at - 1) * 0.1)
    audit = [json.loads(line) for line in Path(call_log.detail_path()).read_text().splitlines()]
    starts = [e for e in audit if e["type"] == "attempt_start"]
    ends = [e for e in audit if e["type"] == "attempt_end"]
    assert [e["attempt_id"] for e in starts] == [e["attempt_id"] for e in attempts]
    assert [e["attempt_id"] for e in ends] == [e["attempt_id"] for e in attempts[:len(ends)]]
    assert len(ends) == failure_at - int(audit_failure)
    assert all(e["outcome"] == "ok" for e in ends[:failure_at - 1])
    assert "test-key" not in json.dumps(audit) and "prior-key" not in json.dumps(audit)
    if audit_failure:
        assert not any(e["type"] in {"audit_coverage_end", "session_end"} for e in log)
    else:
        assert ends[-1]["outcome"] == "interrupted"
        assert ends[-1]["error"] == attempts[-1]["error"]
        assert ends[-1]["answer"] is None and ends[-1]["tool_calls"] is None


@pytest.mark.parametrize("after_attempt", [2, 12])
def test_later_counting_failure_stops_with_no_partial_commit(bounded_config, monkeypatch,
                                                            install_fake_urlopen, after_attempt):
    calls = install_fake_urlopen([Repeat(" ".join(f"fact{i}" for i in range(90)))])
    resumed = seed(bounded_config, large_turn())
    def failing_count(model, prepared):
        if len(calls) >= after_attempt:
            raise ValueError("tokenizer unavailable")
        return fixture_estimate(model, prepared)
    monkeypatch.setattr(token_estimate, "estimate", failing_count)
    output = StringIO()
    run_repl(bounded_config, input_stream=StringIO("/compress\nexit\n"),
             output_stream=output, resumed=resumed)
    assert "tokenizer unavailable" in output.getvalue()
    assert len(calls) == after_attempt
    assert call_log.load_conversation(resumed[0])[:3] == (resumed[1], None, [])


def test_oversized_previous_summary_only_is_reduced(bounded_config, install_fake_urlopen):
    sid = call_log.start_session(bounded_config)
    previous = " ".join(f"prior{i}" for i in range(2500))
    call_log.write_conversation_compressed(previous)
    protected = (({"role": "user", "content": "protected one"},),
                 ({"role": "user", "content": "protected two"},))
    for turn in protected:
        call_log.write_turn_end("ok", messages=turn)
    calls = install_fake_urlopen([Repeat("short summary")])
    output = StringIO()
    run_repl(bounded_config, input_stream=StringIO("/compress\n/history\nexit\n"), output_stream=output,
             resumed=(sid, protected, previous, [], call_log.load_conversation(sid)[3]))
    assert "Compressed 0 turns." in output.getvalue()
    seen = [word for call in calls for word in re.findall(r"prior\d+", json.loads(call["request"].data)["messages"][1]["content"])]
    assert seen == [f"prior{i}" for i in range(2500)]
    assert call_log.load_conversation(sid)[:3] == (protected, "short summary", [])


def test_fixed_memory_overhead_fails_before_http(bounded_config, install_fake_urlopen):
    calls = install_fake_urlopen("unused")
    resumed = seed(bounded_config, large_turn())
    output = StringIO()
    run_repl(bounded_config, input_stream=StringIO("/compress\nexit\n"), output_stream=output,
             resumed=resumed, memory_notes=[{"text": "memory " * 1000}])
    assert "fixed summarization overhead cannot fit" in output.getvalue()
    assert calls == []
    assert call_log.load_conversation(resumed[0])[:3] == (resumed[1], None, [])


def inject_append_failure(monkeypatch, *, partial, restoration_fails=False):
    import builtins
    original_open = builtins.open
    class FailingFile:
        def __init__(self, file):
            self.file = file
        def __enter__(self):
            self.file.__enter__()
            return self
        def __exit__(self, *args):
            return self.file.__exit__(*args)
        def __getattr__(self, name):
            return getattr(self.file, name)
        def write(self, text):
            if '"type": "conversation_compressed"' in text:
                if partial:
                    self.file.write(text[:35])
                    self.file.flush()
                raise OSError("append failed")
            return self.file.write(text)
        def truncate(self, offset):
            if restoration_fails:
                raise OSError("restoration failed")
            return self.file.truncate(offset)
    def patched_open(path, mode="r", *args, **kwargs):
        file = original_open(path, mode, *args, **kwargs)
        if isinstance(path, int) and mode in {"a", "r+b"}:
            return FailingFile(file)
        return file
    monkeypatch.setattr(builtins, "open", patched_open)


@pytest.mark.parametrize("partial", [False, True])
def test_failed_durable_append_restores_live_and_replay_state(bounded_config, monkeypatch,
                                                            install_fake_urlopen, partial):
    resumed = seed(bounded_config, large_turn())
    calls = install_fake_urlopen([Repeat("short summary")])
    inject_append_failure(monkeypatch, partial=partial)
    output = StringIO()
    run_repl(bounded_config, input_stream=StringIO("/compress\n/history\nexit\n"),
             output_stream=output, resumed=resumed)
    assert calls
    assert "could not be saved: append failed" in output.getvalue()
    assert "source4999" in output.getvalue()
    assert "Compressed" not in output.getvalue()
    assert call_log.load_conversation(resumed[0])[:3] == (resumed[1], None, [])


def test_failed_append_restoration_is_fatal(bounded_config, monkeypatch, install_fake_urlopen):
    resumed = seed(bounded_config, large_turn())
    calls = install_fake_urlopen([Repeat("short summary")])
    inject_append_failure(monkeypatch, partial=True, restoration_fails=True)
    with pytest.raises(call_log.PersistenceError, match="could not restore"):
        run_repl(bounded_config, input_stream=StringIO("/compress\nnext task\nexit\n"),
                 output_stream=StringIO(), resumed=resumed)
    assert all("next task" not in call["request"].data.decode() for call in calls)
    with pytest.raises(call_log.ResumeError, match="invalid Call Log line"):
        call_log.load_conversation(resumed[0])


@pytest.mark.parametrize("after_commit", [False, True])
def test_detailed_audit_failure_halts_further_actions(bounded_config, monkeypatch,
                                                    install_fake_urlopen, after_commit):
    resumed = seed(bounded_config, large_turn())
    calls = install_fake_urlopen([Repeat("short summary")])
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    original_write = call_log.write_detail
    def failing_detail(kind, **fields):
        if (not after_commit and kind == "attempt_end" and len(calls) == 2) or (
            after_commit and kind == "local_outcome" and fields["event"].get("name") == "/compress"):
            raise call_log.AuditError("audit failure")
        return original_write(kind, **fields)
    monkeypatch.setattr(call_log, "write_detail", failing_detail)
    with pytest.raises(call_log.AuditError, match="audit failure"):
        run_repl(bounded_config, input_stream=StringIO("/compress\nnext task\nexit\n"),
                 output_stream=StringIO(), resumed=resumed)
    assert all("next task" not in call["request"].data.decode() for call in calls)
    turns, summary, baseline, _ = call_log.load_conversation(resumed[0])
    assert turns == (resumed[1][-2:] if after_commit else resumed[1])
    assert summary == ("short summary" if after_commit else None)
    assert baseline == []


def test_real_local_counter_measures_full_compression_requests_without_network(route_env, monkeypatch,
                                                                             install_fake_urlopen):
    import socket
    network_attempts = []
    def deny_network(*args, **kwargs):
        network_attempts.append(args)
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(context_budget, "model_info", lambda *_: {})
    config = replace(runtime_config.load(), capacity_overrides=({"provider": "openrouter",
        "model": "vendor/test-model", "total_tokens": 11500, "output_tokens": 100},))
    content = "规则 café def lambda(x): return x ** 2\n" * 600
    older = ({"role": "user", "content": "question"},
             {"role": "assistant", "content": "answer", "tool_calls": [
                 {"id": "id-evidence", "name": "calculator", "arguments": {"expression": "2+2"},
                  "arguments_raw": '{"expression":"2+2"}'}]},
             {"role": "tool_result", "id": "id-evidence", "name": "calculator",
              "is_error": False, "content": {"result": content}})
    resumed = seed(config, older)
    calls = install_fake_urlopen([Repeat("small complete summary")])
    measured = []
    actual_estimate = token_estimate.estimate
    def capture_estimate(model, prepared):
        estimate = actual_estimate(model, prepared)
        measured.append((prepared, estimate))
        return estimate
    monkeypatch.setattr(token_estimate, "estimate", capture_estimate)
    output = StringIO()
    run_repl(config, input_stream=StringIO("/compress\nexit\n"), output_stream=output, resumed=resumed,
             memory_notes=[{"text": "remembered fact"}])
    assert "Compressed 1 turn." in output.getvalue()
    assert len(calls) > 2
    rendered = []
    for call in calls:
        body = json.loads(call["request"].data)
        prepared = {"messages": body["messages"]}
        estimates = [estimate for candidate, estimate in measured if candidate == prepared]
        assert estimates and all(estimate.tokens <= 1400 for estimate in estimates)
        assert all(estimate.encoding == "cl100k_base" and estimate.generic for estimate in estimates)
        assert "remembered fact" in body["messages"][0]["content"]
        assert body["max_tokens"] == 100
        rendered.append(body["messages"][1]["content"])
    source = "".join(match.group(1) for text in rendered
                     for match in re.finditer(r"\[Source: Turn 1[^\n]*; character offset \d+\]\n(.*?)\n\[End source piece\]", text, re.S))
    assert json.dumps(older[-1], ensure_ascii=False) in source
    assert "id-evidence" in source and "arguments_raw" in source and "calculator" in source
    result_pieces = [text for text in rendered if "message 3" in text]
    assert len(result_pieces) > 1
    assert all('Tool names/ids [["calculator", "id-evidence"]]' in text for text in result_pieces)
    assert network_attempts == []


@pytest.mark.parametrize("mode", ["truncated", "malformed"])
def test_invalid_summary_response_is_rejected(bounded_config, monkeypatch, mode):
    from personal_agent.providers import http
    from tests.fakes import FakeOpenRouterResponse
    resumed = seed(bounded_config, large_turn())
    calls = []
    def fake_http(request, timeout=None):
        calls.append(request)
        if mode == "truncated":
            payload = {"choices": [{"message": {"content": "partial summary"}, "finish_reason": "length"}]}
        else:
            payload = {"choices": [{"message": {"content": None, "tool_calls": [{"id": "bad",
                "type": "function", "function": {"name": "shell", "arguments": '{}'}}]}}]}
        return FakeOpenRouterResponse(payload)
    monkeypatch.setattr(http, "urlopen", fake_http)
    output = StringIO()
    run_repl(bounded_config, input_stream=StringIO("/compress\nexit\n"), output_stream=output, resumed=resumed)
    assert len(calls) == 1
    assert ("length-truncated" if mode == "truncated" else "malformed") in output.getvalue()
    assert call_log.load_conversation(resumed[0])[:3] == (resumed[1], None, [])


def test_summary_costs_retries_redaction_and_usage_remain_ordinary_task_scoped(bounded_config, monkeypatch,
                                                                          install_fake_urlopen):
    from urllib.error import HTTPError
    from personal_agent.routing import router
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    monkeypatch.setenv("TAVILY_API_KEY", "prior-key")
    calls = install_fake_urlopen(["ordinary answer", HTTPError("https://example.invalid", 503, "retry", None, None),
                                  Repeat({"content": "test-key prior-key short summary", "usage": {"cost": 0.1}})])
    config = replace(bounded_config, capacity_overrides=())
    resumed = seed(config, large_turn())
    output = StringIO()
    run_repl(config, input_stream=StringIO("ordinary task\n/compress\n/usage\nexit\n"),
             output_stream=output, resumed=resumed)
    assert "Compressed 2 turns." in output.getvalue()
    bodies = [json.loads(call["request"].data) for call in calls]
    assert [body["session_id"] for body in bodies] == [resumed[0]] + [f"{resumed[0]}:compression"] * (len(calls) - 1)
    assert bodies[1] == bodies[2]
    usage = output.getvalue().split("Compressed 2 turns.")[-1]
    assert "vendor/test-model" in usage
    assert "No ordinary exchange" not in usage
    summary = call_log.load_conversation(resumed[0])[1]
    assert "test-key" not in summary
    assert "prior-key" not in summary
    attempts = [e for e in entries() if e["type"] == "attempt" and e["task"] == "/compress"]
    assert not attempts[0]["ok"]
    assert [e["attempt"] for e in attempts] == list(range(1, len(attempts) + 1))
    assert call_log.total_cost() == pytest.approx((len(calls) - 2) * 0.1)


def test_multi_block_commit_keeps_todo_baseline_across_resume_undo_and_clear(bounded_config,
                                                                         install_fake_urlopen):
    old_todo = [{"content": "old todo", "status": "pending"}]
    new_todo = [{"content": "recent todo", "status": "completed"}]
    older = large_turn() + ({"role": "tool_result", "id": "old-todo", "name": "todo", "content": {"todos": old_todo}},)
    sid = call_log.start_session(bounded_config)
    protected = (({"role": "user", "content": "protected one"},),
                 ({"role": "user", "content": "protected two"},
                  {"role": "tool_result", "id": "new-todo", "name": "todo", "content": {"todos": new_todo}}))
    for turn in (older, *protected):
        call_log.write_turn_end("ok", messages=turn)
    install_fake_urlopen([Repeat("summary")])
    run_repl(bounded_config, input_stream=StringIO("/compress\nexit\n"), output_stream=StringIO(),
             resumed=(sid, (older, *protected), None, [], call_log.load_conversation(sid)[3]))
    compressed = call_log.load_conversation(sid)
    assert compressed[:3] == (protected, "summary", old_todo)
    run_repl(bounded_config, input_stream=StringIO("/undo\nexit\n"), output_stream=StringIO(),
             resumed=(sid, *compressed))
    undone = call_log.load_conversation(sid)
    assert undone[:3] == (protected[:1], "summary", old_todo)
    run_repl(bounded_config, input_stream=StringIO("/clear\nexit\n"), output_stream=StringIO(),
             resumed=(sid, *undone))
    assert call_log.load_conversation(sid)[:3] == ((), None, [])
