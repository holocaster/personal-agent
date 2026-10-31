import json
from dataclasses import replace
from io import StringIO

import pytest

from personal_agent import call_log
from personal_agent.routing import router
from personal_agent.terminal.repl import run_repl
from tests.fakes import FakeOpenRouterResponse
from tests.test_compression import anthropic_summary, entries, fixture_estimate, seed, seed_summary_and_todos
from tests.test_context_overflow import choice_rejection, rejection
from tests.test_preventive_compression import config, scripted_estimate


@pytest.mark.parametrize("mode", ["preventive", "recovery"])
@pytest.mark.parametrize("usage", [True, False])
def test_anthropic_truncated_tool_follow_up_compression_preserves_state(
    config, monkeypatch, install_fake_urlopen, tmp_path, mode, usage
):
    from personal_agent import cost, token_estimate
    from personal_agent.providers import anthropic
    from personal_agent.tools import todo, workspace
    workspace.configure_workspace(tmp_path)
    config = replace(config, provider="anthropic",
                     capacity_overrides=({**config.capacity_overrides[0], "provider": "anthropic"},
                                         *config.capacity_overrides[1:]))
    monkeypatch.setattr(router, "_sleep", lambda _: pytest.fail("unfinished summaries must not retry"))
    pricing = []
    def estimate_cost(model, prompt, completion, **cache):
        assert cache["provider"] == "anthropic"
        pricing.append((model, prompt, completion))
        return 0.1 if prompt is not None and completion is not None else None
    monkeypatch.setattr(cost, "estimate", estimate_cost)
    resumed = seed_summary_and_todos(config, (
        {"role": "user", "content": "old-context " * 300}, {"role": "assistant", "content": "old answer"},
    ))
    before = StringIO()
    run_repl(config, input_stream=StringIO("/history\nexit\n"), output_stream=before, resumed=resumed)
    assessed, probes = [], []
    def estimate(model, prepared):
        if "tools" not in prepared:
            return fixture_estimate(model, prepared)
        if prepared["messages"][-1] == {"role": "user", "content": "state probe"}:
            assert prepared["messages"][:-1] == anthropic.prepare_input(
                "", [message for turn in resumed[1] for message in turn])["messages"]
            assert f"Conversation Summary of earlier turns:\n{resumed[2]}" in prepared["system"]
            assert "Todo List:\n- [pending] prior todo" in prepared["system"]
            probes.append(prepared)
            ends = [e for e in entries() if e["type"] == "turn_end"]
            assert len(ends) == 5 + len(probes) and ends[-1]["status"] == "error"
            if len(probes) == 1:
                assert "context-truncated" in ends[-1]["error"]
            raise ValueError("state probe complete; no dispatch")
        assessed.append(prepared)
        text = json.dumps(prepared)
        tokens = 224001 if mode == "preventive" and "bytes_written" in text and "old-context" in text else 174000
        return token_estimate.TokenEstimate(tokens, "follow-up fixture", True)
    monkeypatch.setattr(token_estimate, "estimate", estimate)
    arguments = {"path": "effect.txt", "content": "effect"}
    first = {"tool_calls": [{"id": "write-once", "name": "write", "arguments": arguments}],
             "usage": {"prompt_tokens": 10, "completion_tokens": 3}}
    outcomes = [first] + ([rejection("anthropic")] if mode == "recovery" else []) + [
        anthropic_summary("short summary", "model_context_window_exceeded", usage)]
    calls = install_fake_urlopen(outcomes)
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending task\ny\n/history\n/usage\nstate probe\nexit\n"),
             output_stream=output, resumed=resumed)
    assert len(calls) == len(outcomes)
    bodies = [json.loads(call["request"].data) for call in calls]
    assert all(body["model"] == "vendor/test-model" and "tools" in body for body in bodies[:-1])
    assert calls[-1]["request"].full_url == anthropic.API_URL
    summary = bodies[-1]
    assert summary["model"] == "vendor/test-model" and "tools" not in summary
    assert summary["max_tokens"] == 16000
    assert "Summarize the conversation" in summary["messages"][0]["content"]
    assert "old-context" in summary["messages"][0]["content"]
    assert "prior summary" in summary["messages"][0]["content"]
    assert all(text not in json.dumps(summary) for text in (
        "protected one", "protected two", "pending task", "write-once", "prior todo"))
    follow_ups = [prepared for prepared in assessed if "old-context" in json.dumps(prepared)
                  and "bytes_written" in json.dumps(prepared)]
    assert len(follow_ups) == (2 if mode == "recovery" else 1)
    expected_result = {"path": "effect.txt", "bytes_written": 6, "created": True}
    for prepared in follow_ups:
        active = prepared["messages"][-3:]
        assert active[0] == {"role": "user", "content": "pending task"}
        assert active[1]["content"] == [{"type": "tool_use", "id": "write-once", "name": "write", "input": arguments}]
        assert active[2] == {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "write-once", "content": json.dumps(expected_result)}]}
        assert "Todo List:\n- [pending] prior todo" in prepared["system"]
    assert (tmp_path / "effect.txt").read_text() == "effect"
    text = output.getvalue()
    assert text.count("Apply this change? [y/N]") == 1
    assert text.count("Automatic Compression failed; pending exchange stopped.") == 1
    assert text.count("Context overflow recovery:" if mode == "recovery" else "Automatic Compression: reducing") == 1
    assert "context-truncated" in text
    assert "Automatic Compression completed" not in text and "Compressed" not in text
    assert "outcome: locally blocked" in text and "reported input: unknown" in text
    assert "vendor/test-model" in text and "reported input: 111" not in text
    assert before.getvalue().split("\n", 3)[3] in text
    restored = call_log.load_conversation(resumed[0])
    assert restored[:3] == resumed[1:4]
    assert todo.current_list(restored[0], restored[2]) == [{"content": "prior todo", "status": "pending"}]
    assert len(probes) == 1
    log = entries()
    executions = [e for e in log if e["type"] == "tool_execution"]
    assert len(executions) == 1
    assert executions[0]["tool_call_id"] == "write-once" and executions[0]["name"] == "write"
    assert executions[0]["arguments"] == arguments and executions[0]["result"] == expected_result and executions[0]["ok"]
    confirmations = [e for e in log if e.get("action") == "tool_confirmation"]
    assert len(confirmations) == 1 and confirmations[0]["tool_call_id"] == "write-once"
    assert confirmations[0]["decision"] == "approved"
    assert sum(e["type"] == "conversation_compressed" for e in log) == 1
    ends = [e for e in log if e["type"] == "turn_end"]
    assert len(ends) == 7 and all(e["status"] == "error" and "messages" not in e for e in ends[-2:])
    assert "context-truncated" in ends[-2]["error"]
    assert "state probe complete" in ends[-1]["error"]
    attempts = [e for e in log if e["type"] == "attempt"]
    assert [e["task"] for e in attempts] == ["pending task"] * (len(outcomes) - 1) + ["/compress"]
    assert [e["attempt"] for e in attempts] == ([1, 2, 1] if mode == "recovery" else [1, 1])
    assert [e["ok"] for e in attempts] == ([True, False, True] if mode == "recovery" else [True, True])
    assert [e["cost"] for e in attempts] == [0.1] + ([None] if mode == "recovery" else []) + [0.1 if usage else None]
    assert all(e["cost_estimated"] for e in attempts) and attempts[-1]["answer"] == "short summary"
    assert (attempts[-1]["prompt_tokens"], attempts[-1]["completion_tokens"]) == ((111, 7) if usage else (None, None))
    assert pricing[0] == ("vendor/test-model", 10, 3)
    assert pricing[-1] == ("vendor/test-model", 111 if usage else None, 7 if usage else None)
    total = 0.1 + (0.1 if usage else 0)
    assert call_log.total_cost() == pytest.approx(total)
    assert f"spend: ${total:.4f}" in text
    after = StringIO()
    run_repl(config, input_stream=StringIO("/history\nstate probe\nexit\n"), output_stream=after,
             resumed=(resumed[0], *call_log.load_conversation(resumed[0])))
    assert after.getvalue().startswith(before.getvalue())
    assert call_log.load_conversation(resumed[0])[:3] == resumed[1:4]
    assert len(probes) == 2 and probes[0]["messages"] == probes[1]["messages"] and probes[0]["tools"] == probes[1]["tools"]
    assert "Recorded context from the previous unfinished task" in probes[0]["system"]
    assert "effect.txt" in probes[0]["system"]
    assert "Recorded context from the previous unfinished task" not in probes[1]["system"]
    assert len(calls) == len(outcomes)
    assert [e for e in entries() if e["type"] == "tool_execution"] == executions


@pytest.mark.parametrize("provider_name", ["openrouter", "openai", "anthropic", "gemini"])
@pytest.mark.parametrize("failure", ["http overflow", "response overflow", "http tools", "response tools",
                                    "http invalid", "response invalid", "malformed"])
def test_provider_failures_preserve_normalized_usage(config, monkeypatch, install_fake_urlopen,
                                                   provider_name, failure):
    from io import BytesIO
    from urllib.error import HTTPError
    from personal_agent import cost

    config = replace(config, provider=provider_name,
                     capacity_overrides=tuple({**record, "provider": provider_name} for record in config.capacity_overrides))
    pricing = []
    monkeypatch.setattr(cost, "estimate", lambda *args, **kwargs: pricing.append((args, kwargs)) or 0.3)
    raw_usage = ({"input_tokens": 91, "cache_read_input_tokens": 15, "cache_creation_input_tokens": 5,
                  "output_tokens": 7} if provider_name == "anthropic" else
                 {"promptTokenCount": 111, "candidatesTokenCount": 7} if provider_name == "gemini" else
                 {"cost": 0.3, "prompt_tokens": 111, "completion_tokens": 7,
                  "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}})
    data = {"usageMetadata" if provider_name == "gemini" else "usage": raw_usage}
    if failure != "malformed":
        messages = {"anthropic": "prompt is too long: 130000 tokens > 128000 maximum",
                    "gemini": "The input token count (130000) exceeds the maximum number of tokens allowed (128000)."}
        data["error"] = {"code": 400, "message": messages.get(provider_name,
            "This model's maximum context length is 128000 tokens. However, you requested 130000 tokens.")}
        if "tools" in failure:
            data["error"] = {"code": 400, "message": "This model does not support tools"}
        elif "invalid" in failure:
            data["error"] = {"code": 400, "message": "Invalid request"}
    response = (HTTPError("https://example.invalid", 400, "rejected", {}, BytesIO(json.dumps(data).encode()))
                if failure.startswith("http") else FakeOpenRouterResponse(data))
    calls = install_fake_urlopen([response])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/usage\nexit\n"), output_stream=output)
    assert len(calls) == 1
    attempts = [e for e in entries() if e["type"] == "attempt"]
    assert len(attempts) == 1
    attempt = attempts[0]
    assert not attempt["ok"] and attempt["answer"] is None and attempt["tool_calls"] is None
    assert attempt["cost"] == call_log.total_cost() == 0.3
    assert (attempt["prompt_tokens"], attempt["completion_tokens"]) == (111, 7)
    assert attempt["cost_estimated"] == (provider_name != "openrouter")
    if provider_name == "openrouter":
        assert pricing == []
    else:
        assert pricing == [(("gemini/vendor/test-model" if provider_name == "gemini" else "vendor/test-model",
                             111, 7), {"provider": provider_name, "cached_tokens": 15 if provider_name == "anthropic" else 0,
                                       "cache_write_tokens": 5 if provider_name == "anthropic" else 0,
                                       "cache_creation_token_details": None})]
    if "overflow" not in failure:
        assert "reported input: 111" in output.getvalue()
    assert call_log.load_conversation(call_log.current_session_id())[:3] == ((), None, [])


@pytest.mark.parametrize("outcome", ["overflow", "tool rejection", "rate limit", "success", "summary rejection",
                                    "empty summary", "missing usage"])
@pytest.mark.parametrize("envelope", ["choice", "top", "http"])
@pytest.mark.parametrize("follow_up", [False, True])
def test_usage_bearing_recovery_rejections_are_charged_once(config, monkeypatch, install_fake_urlopen,
                                                         outcome, envelope, follow_up):
    from io import BytesIO
    from urllib.error import HTTPError

    def response(data):
        if envelope != "choice":
            data = {"error": data["choices"][0]["error"], "usage": data.get("usage")}
        if envelope == "http":
            return HTTPError("https://example.invalid", data["error"]["code"], "rejected", {},
                             BytesIO(json.dumps(data).encode()))
        return FakeOpenRouterResponse(data)

    scripted_estimate(monkeypatch, 174000, reduced=140000)
    monkeypatch.setattr(router, "_sleep", lambda _: pytest.fail("recovery must be terminal"))
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    first = choice_rejection()
    second = choice_rejection({"code": 400 if outcome == "tool rejection" else 429,
                               "message": "This model does not support tools" if outcome == "tool rejection"
                               else "Rate limit exceeded"} if outcome in {"tool rejection", "rate limit"} else None)
    first["usage"] = {"cost": 0.3, "prompt_tokens": 111, "completion_tokens": 7,
                      "prompt_tokens_details": {"cached_tokens": 80, "cache_write_tokens": 4}}
    second["usage"] = {**first["usage"], "cost": 0.2}
    for rejected in (first, second):
        rejected["choices"][0]["message"]["tool_calls"] = [{"id": "must-not-run", "type": "function",
            "function": {"name": "calculator", "arguments": json.dumps({"expression": "1+1"})}}]
    summary = {"content": "" if outcome == "empty summary" else "short summary", "usage": {"cost": 0.1}}
    final = {"content": "answer", "usage": {"cost": 0.2, "prompt_tokens": 222, "completion_tokens": 8}}
    if outcome == "missing usage":
        second.pop("usage")
    outcomes = ([{"tool_calls": [{"id": "once", "name": "calculator", "arguments": {"expression": "2+2"}}]}]
                if follow_up else []) + [response(first), response(second) if outcome == "summary rejection" else summary]
    if outcome not in {"summary rejection", "empty summary"}:
        outcomes.append(final if outcome == "success" else response(second))
    calls = install_fake_urlopen(outcomes)
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/usage\nexit\n"),
             output_stream=output, resumed=resumed)
    assert len(calls) == len(outcomes)
    total = 0.5 if outcome == "summary rejection" else 0.4 if outcome in {"empty summary", "missing usage"} else 0.6
    assert call_log.total_cost() == pytest.approx(total)
    attempts = [e for e in entries() if e["type"] == "attempt"]
    recovered_dispatch = outcome not in {"summary rejection", "empty summary"}
    assert [e["purpose"] for e in attempts] == (["execution"] if follow_up else []) + ["execution", "compression"] + (["execution"] if recovered_dispatch else [])
    assert [e["retry_kind"] for e in attempts] == ["initial"] * (len(attempts) - int(recovered_dispatch)) + (["context_overflow"] if recovered_dispatch else [])
    assert [e["cost"] for e in attempts] == ([None] if follow_up else []) + ([0.3, 0.2] if outcome == "summary rejection" else
                                            [0.3, 0.1] if outcome == "empty summary" else
                                            [0.3, 0.1, None if outcome == "missing usage" else 0.2])
    failed = [e for e in attempts if not e["ok"] and e["cost"] is not None]
    assert all(e["prompt_tokens"] == 111 and e["completion_tokens"] == 7
               and e["cached_tokens"] == 80 and e["cache_write_tokens"] == 4
               and e["answer"] is None and e["tool_calls"] is None for e in failed)
    reported = "222" if outcome == "success" else "unknown" if outcome in {
        "summary rejection", "empty summary", "missing usage"} else "111"
    assert "reported input: " + reported in output.getvalue()
    assert f"spend: ${total:.4f}" in output.getvalue()
    expected_outcome = "recovered" if outcome == "success" else "locally blocked" if outcome in {
        "summary rejection", "empty summary"} else "recovery failed"
    assert "outcome: " + expected_outcome in output.getvalue()
    assert "partial output" not in output.getvalue()
    assert [e for e in entries() if e["type"] == "turn_end"][-1]["status"] == (
        "ok" if outcome == "success" else "error")
    assert sum(e["type"] == "conversation_compressed" for e in entries()) == int(
        outcome not in {"summary rejection", "empty summary"})
    executions = [e for e in entries() if e["type"] == "tool_execution"]
    assert [e["result"] for e in executions] == ([{"result": 4}] if follow_up else [])
    from tests.test_detailed_audit import lines
    ends = [e for e in lines(call_log.detail_path()) if e["type"] == "attempt_end"]
    assert len(ends) == len(attempts)
    assert all(e["answer"] is None and e["tool_calls"] is None for e in ends if e["outcome"] == "error")


@pytest.mark.parametrize("failure", ["second overflow", "rate limit", "tool rejection"])
@pytest.mark.parametrize("follow_up", [False, True])
def test_choice_level_recovery_failure_is_terminal_and_not_replayed(config, monkeypatch, install_fake_urlopen,
                                                                 tmp_path, failure, follow_up):
    from personal_agent.tools import workspace
    from tests.test_detailed_audit import lines
    workspace.configure_workspace(tmp_path)
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    monkeypatch.setattr(router, "_sleep", lambda _: pytest.fail("recovery must not back off"))
    scripted_estimate(monkeypatch, 174000, reduced=140000)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    outcome = choice_rejection(None if failure == "second overflow" else {
        "code": 429 if failure == "rate limit" else 400,
        "message": "Recovery rate limit" if failure == "rate limit" else "This model does not support tools",
        "metadata": {"error_type": "rate_limit_exceeded" if failure == "rate limit" else "invalid_request"},
    })
    outcome["choices"][0]["message"]["tool_calls"] = [{
        "id": "must-not-run", "type": "function", "function": {
            "name": "write", "arguments": json.dumps({"path": "unexpected.txt", "content": "wrong"})},
    }]
    first = [{"tool_calls": [{"id": "once", "name": "write", "arguments": {
        "path": "effect.txt", "content": "effect"}}]}] if follow_up else []
    calls = install_fake_urlopen(first + [FakeOpenRouterResponse(choice_rejection()), "short summary",
                                         FakeOpenRouterResponse(outcome)])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n" + ("y\n" if follow_up else "") + "/usage\nexit\n"),
             output_stream=output, resumed=resumed)
    assert len(calls) == 3 + follow_up
    bodies = [json.loads(call["request"].data) for call in calls]
    rejected, summary, retry = bodies[-3:]
    assert rejected["model"] == retry["model"] == "vendor/test-model"
    assert calls[-3]["request"].full_url == calls[-1]["request"].full_url
    assert "tools" in retry and "tools" not in summary
    assert "old-context" not in json.dumps(retry) and "short summary" in json.dumps(retry)
    assert rejected["messages"][-(3 if follow_up else 1):] == retry["messages"][-(3 if follow_up else 1):]
    log = entries()
    attempts = [e for e in log if e["type"] == "attempt" and e["task"] == "pending"]
    assert [e["attempt"] for e in attempts] == list(range(1, 3 + follow_up))
    assert [e["ok"] for e in attempts] == ([True] if follow_up else []) + [False, False]
    assert all(e["answer"] is None for e in attempts[-2:])
    assert len([e for e in log if e["type"] == "tool_execution"]) == int(follow_up)
    assert output.getvalue().count("Apply this change? [y/N]") == int(follow_up)
    if follow_up:
        assert (tmp_path / "effect.txt").read_text() == "effect"
    assert not (tmp_path / "unexpected.txt").exists()
    assert [e for e in log if e["type"] == "turn_end"][-1]["status"] == "error"
    assert "outcome: recovery failed" in output.getvalue()
    assert "reported input: unknown" in output.getvalue() and "estimated input: 140000" in output.getvalue()
    assert "partial output" not in output.getvalue() and "outcome: recovered" not in output.getvalue()
    audit = lines(call_log.detail_path())
    ends = [e for e in audit if e["type"] == "attempt_end"]
    assert [e["outcome"] for e in ends] == (["ok"] if follow_up else []) + ["error", "ok", "error"]
    assert [e["attempt_id"] for e in ends] == [e["attempt_id"] for e in log if e["type"] == "attempt"]
    assert all(e["answer"] is None and e["tool_calls"] is None for e in (ends[-3], ends[-1]))
    assert sum(e["type"] == "conversation_compressed" for e in log) == 1
    expected = (resumed[1][-2:], "short summary", [])
    assert call_log.load_conversation(resumed[0])[:3] == expected
    run_repl(config, input_stream=StringIO("/history\nexit\n"), output_stream=StringIO(),
             resumed=(resumed[0], *call_log.load_conversation(resumed[0])))
    assert call_log.load_conversation(resumed[0])[:3] == expected
    assert len(calls) == 3 + follow_up


@pytest.mark.parametrize("provider_name,choice_level", [
    ("openrouter", False), ("openai", False), ("anthropic", False), ("gemini", False), ("openrouter", True),
])
@pytest.mark.parametrize("follow_up", [False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_rejected_exchange_retries_same_route_without_reexecuting_tools(config, monkeypatch,
                                                                     install_fake_urlopen, provider_name, choice_level, follow_up, stream):
    provider = router.get_provider(provider_name)
    original_call = provider.call
    if not stream:
        monkeypatch.setattr(provider, "call", lambda *args, **kwargs: original_call(*args, **kwargs))
    config = replace(config, provider=provider_name,
                     capacity_overrides=tuple({**record, "provider": provider_name} for record in config.capacity_overrides))
    scripted_estimate(monkeypatch, 174000, reduced=140000)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    first = [{"tool_calls": [{"id": "once", "name": "calculator", "arguments": {"expression": "2+2"}}]}] if follow_up else []
    rejected_response = FakeOpenRouterResponse(choice_rejection()) if choice_level else rejection(provider_name)
    calls = install_fake_urlopen(first + [rejected_response, "short summary", "pending answer"])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/usage\nexit\n"), output_stream=output, resumed=resumed)
    assert len(calls) == 3 + follow_up
    bodies = [json.loads(call["request"].data) for call in calls]
    rejected, summary, retry = bodies[-3:]
    assert calls[-3]["request"].full_url == calls[-1]["request"].full_url
    if provider_name == "openrouter":
        assert [body["session_id"] for body in bodies] == [resumed[0]] * (1 + follow_up) + [
            f"{resumed[0]}:compression", resumed[0]]
    else:
        assert all("session_id" not in body for body in bodies)
    assert "tools" in retry and "tools" not in summary
    assert "old-context" not in json.dumps(retry)
    assert "short summary" in json.dumps(retry)
    key = "contents" if provider_name == "gemini" else "messages"
    suffix = 3 if follow_up else 1
    assert rejected[key][-suffix:] == retry[key][-suffix:]
    log = entries()
    attempts = [e for e in log if e["type"] == "attempt" and e["task"] == "pending"]
    assert [e["attempt"] for e in attempts] == list(range(1, 3 + follow_up))
    assert [e["ok"] for e in attempts] == ([True] if follow_up else []) + [False, True]
    executions = [e for e in log if e["type"] == "tool_execution"]
    assert len(executions) == int(follow_up)
    if follow_up:
        assert executions[0]["result"] == {"result": 4}
    restored = call_log.load_conversation(resumed[0])
    assert restored[0][:-1] == resumed[1][-2:] and restored[1] == "short summary"
    assert sum(e["type"] == "conversation_compressed" for e in log) == 1
    assert "outcome: recovered" in output.getvalue()
    assert "140000" in output.getvalue() and "reported input: unknown" in output.getvalue()


@pytest.mark.parametrize("failure", ["second overflow", "timeout", "rate limit", "bad request", "summary overflow",
                                   "summary choice overflow", "empty summary", "count", "no reduction", "ceiling",
                                   "interrupt", "summary interrupt"])
def test_failed_recovery_stops_with_tool_evidence_and_truthful_resume(config, monkeypatch,
                                                                   install_fake_urlopen, failure):
    from urllib.error import HTTPError
    from personal_agent import token_estimate
    from tests.test_compression import fixture_estimate
    monkeypatch.setattr(router, "_sleep", lambda _: pytest.fail("recovery must not back off"))
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    def estimate(model, prepared):
        if "tools" not in prepared:
            return fixture_estimate(model, prepared)
        reduced = "short summary" in json.dumps(prepared)
        if reduced and failure == "count":
            raise ValueError("candidate tokenizer failed")
        count = 174000 if not reduced or failure == "no reduction" else 224001 if failure == "ceiling" else 140000
        return token_estimate.TokenEstimate(count, "fixture", True)
    monkeypatch.setattr(token_estimate, "estimate", estimate)
    summary = (rejection() if failure == "summary overflow" else
               FakeOpenRouterResponse(choice_rejection()) if failure == "summary choice overflow" else
               "" if failure == "empty summary" else
               KeyboardInterrupt() if failure == "summary interrupt" else "short summary")
    outcome = (rejection() if failure == "second overflow" else TimeoutError("retry failed") if failure == "timeout"
               else KeyboardInterrupt() if failure == "interrupt" else
               HTTPError("https://example.invalid", 429 if failure == "rate limit" else 400, "retry failed", None, None))
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "once", "name": "calculator", "arguments": {"expression": "2+2"}}]},
        rejection(), summary, outcome,
    ])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/history\n/usage\nexit\n"), output_stream=output, resumed=resumed)
    committed = failure in {"second overflow", "timeout", "rate limit", "bad request", "interrupt"}
    assert len(calls) == (4 if committed else 3)
    log = entries()
    executions = [e for e in log if e["type"] == "tool_execution"]
    assert len(executions) == 1 and executions[0]["result"] == {"result": 4}
    assert sum(e["type"] == "conversation_compressed" for e in log) == int(committed)
    expected = (resumed[1][-2:], "short summary", []) if committed else (resumed[1], None, [])
    assert call_log.load_conversation(resumed[0])[:3] == expected
    assert [e for e in log if e["type"] == "turn_end"][-1]["status"] == ("interrupted" if "interrupt" in failure else "error")
    assert "outcome: " + ("interrupted" if "interrupt" in failure else "recovery failed" if committed else "locally blocked") in output.getvalue()
    assert "reported input: unknown" in output.getvalue()
    run_repl(config, input_stream=StringIO("/history\nexit\n"), output_stream=StringIO(),
             resumed=(resumed[0], *call_log.load_conversation(resumed[0])))
    assert call_log.load_conversation(resumed[0])[:3] == expected
    assert len(calls) == (4 if committed else 3)


@pytest.mark.parametrize("choice_level", [False, True])
def test_rejected_exchange_without_eligible_older_context_never_retries_or_escalates(config, install_fake_urlopen,
                                                                                 choice_level):
    rejected_response = FakeOpenRouterResponse(choice_rejection()) if choice_level else rejection()
    calls = install_fake_urlopen([rejected_response, "unused"])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/usage\nexit\n"), output_stream=output)
    assert len(calls) == 1
    assert "no safe older context" in output.getvalue()
    assert "outcome: locally blocked" in output.getvalue()
    assert len([e for e in entries() if e["type"] == "attempt"]) == 1
    assert call_log.load_conversation(call_log.current_session_id())[:3] == ((), None, [])


def test_overflow_after_last_transient_attempt_still_gets_one_recovery(config, monkeypatch, install_fake_urlopen):
    from urllib.error import HTTPError
    sleeps = []
    monkeypatch.setattr(router, "_sleep", sleeps.append)
    scripted_estimate(monkeypatch, 174000, reduced=140000)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    calls = install_fake_urlopen([
        HTTPError("fake", 503, "transient", None, None), TimeoutError("transient"), rejection(),
        {"content": "short summary", "usage": {"cost": 0.1}},
        {"content": "answer", "usage": {"cost": 0.2, "prompt_tokens": 150001, "completion_tokens": 3}},
    ])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/usage\nexit\n"), output_stream=output, resumed=resumed)
    assert len(calls) == 5 and sleeps == [0.5, 1]
    assert call_log.total_cost() == pytest.approx(0.3)
    assert [e["attempt"] for e in entries() if e["type"] == "attempt" and e["task"] == "pending"] == [1, 2, 3, 4]
    assert "outcome: recovered" in output.getvalue()
    assert "estimated input: 140000" in output.getvalue() and "reported input: 150001" in output.getvalue()


def test_later_tool_exchange_has_its_own_allowance_and_can_reduce_prior_summary(config, monkeypatch,
                                                                            install_fake_urlopen):
    from personal_agent import token_estimate
    from tests.test_compression import fixture_estimate
    first_summary = "first summary " * 200
    measured = []
    def estimate(model, prepared):
        if "tools" not in prepared:
            return fixture_estimate(model, prepared)
        text = json.dumps(prepared)
        count = 174000 if "old-context" in text else 140000 if "first summary" in text else 120000
        measured.append((prepared, count))
        return token_estimate.TokenEstimate(count, "fixture", True)
    monkeypatch.setattr(token_estimate, "estimate", estimate)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 1000},))
    calls = install_fake_urlopen([
        rejection(), first_summary,
        {"tool_calls": [{"id": "once", "name": "calculator", "arguments": {"expression": "2+2"}}]},
        rejection(), "short summary", "answer",
    ])
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\n/usage\nexit\n"), output_stream=output, resumed=resumed)
    assert len(calls) == 6
    bodies = [json.loads(call["request"].data) for call in calls]
    assert "Source: Previous summary" in bodies[4]["messages"][1]["content"]
    assert first_summary in bodies[4]["messages"][1]["content"]
    log = entries()
    assert sum(e["type"] == "conversation_compressed" for e in log) == 2
    assert sum(e["type"] == "tool_execution" for e in log) == 1
    assert [e["attempt"] for e in log if e["type"] == "attempt" and e["task"] == "pending"] == [1, 2, 3, 4]
    assert "outcome: recovered" in output.getvalue()
    assert call_log.load_conversation(resumed[0])[1] == "short summary"


@pytest.mark.parametrize("count_failure", [None, "zero", "exception"])
def test_real_offline_recovery_preserves_gemini_parts_and_one_mutating_apply(config, monkeypatch, tmp_path,
                                                                         count_failure):
    import importlib.metadata
    import socket
    from personal_agent import token_estimate
    from personal_agent.providers import gemini, http
    from personal_agent.tools import workspace
    from tests.fakes import FakeOpenRouterResponse
    from tests.test_detailed_audit import lines
    assert importlib.metadata.version("litellm") == "1.102.0"
    network = []
    def deny(*args, **kwargs):
        network.append(args)
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    workspace.configure_workspace(tmp_path)
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    config = replace(config, provider="gemini", capacity_overrides=({
                         "provider": "gemini", "model": "vendor/test-model", "total_tokens": 250000},))
    resumed = seed(config, ({"role": "user", "content": "old-context " + "history " * 3000},))
    first_parts = [
        {"text": "model text one", "thoughtSignature": "exact-text-signature"},
        {"functionCall": {"name": "write", "args": {"path": "effect.txt", "content": "effect"}, "id": "write-once"},
         "thoughtSignature": "exact-write-signature"},
    ]
    second_parts = [
        {"text": "model text two", "thoughtSignature": "exact-second-signature"},
        {"functionCall": {"name": "calculator", "args": {"expression": "2+2"}}},
    ]
    outcomes = iter([first_parts, second_parts, rejection("gemini"), [{"text": "answer"}]])
    bodies = []
    def post(request, timeout=None):
        body = json.loads(request.data)
        bodies.append(body)
        if "tools" in body:
            outcome = next(outcomes)
            if isinstance(outcome, BaseException):
                raise outcome
            return FakeOpenRouterResponse({"candidates": [{"content": {"parts": outcome}}]})
        return FakeOpenRouterResponse({"candidates": [{"content": {"parts": [{"text": "short summary"}]}}]})
    monkeypatch.setattr(http, "urlopen", post)
    library, _ = token_estimate.local_library()
    counter = library.token_counter
    def count(**kwargs):
        if count_failure and "short summary" in kwargs["text"] and "systemInstruction" in kwargs["text"]:
            if count_failure == "exception":
                raise ValueError("candidate counting failed")
            return 0
        return counter(**kwargs)
    monkeypatch.setattr(library, "token_counter", count)
    measured = []
    real_estimate = token_estimate.estimate
    def capture(model, prepared):
        result = real_estimate(model, prepared)
        measured.append((prepared, result))
        return result
    monkeypatch.setattr(token_estimate, "estimate", capture)
    output = StringIO()
    run_repl(config, input_stream=StringIO("pending\ny\n/usage\nexit\n"),
             output_stream=output, resumed=resumed)
    assert output.getvalue().count("Apply this change? [y/N]") == 1
    assert (tmp_path / "effect.txt").read_text() == "effect"
    log = entries()
    assert [e["result"] for e in log if e["type"] == "tool_execution"] == [
        {"path": "effect.txt", "bytes_written": 6, "created": True}, {"result": 4}]
    assert call_log.total_cost() == 0.0
    ordinary = [body for body in bodies if "tools" in body]
    assert len(ordinary) == (3 if count_failure else 4)
    audit = lines(call_log.detail_path())
    starts = [e for e in audit if e["type"] == "attempt_start"]
    ends = [e for e in audit if e["type"] == "attempt_end"]
    attempts = [e for e in log if e["type"] == "attempt"]
    assert len(starts) == len(ends) == len(attempts) == len(bodies)
    assert [e["attempt_id"] for e in starts] == [e["attempt_id"] for e in ends] == [e["attempt_id"] for e in attempts]
    for start, body in zip(starts, bodies):
        assert "session_id" not in body
        prepared = gemini.prepare_input(start["system"], start["messages"], (), start["replay"])
        if "tools" in body:
            prepared["tools"] = [{"functionDeclarations": start["tools"]}]
        assert prepared == {key: value for key, value in body.items()
                            if key not in {"model", "max_tokens", "provider", "generationConfig", "session_id"}}
    if count_failure:
        assert call_log.load_conversation(resumed[0])[:3] == (resumed[1], None, [])
        assert [e for e in log if e["type"] == "turn_end"][-1]["status"] == "error"
        assert "outcome: locally blocked" in output.getvalue()
    else:
        rejected, retry = ordinary[-2:]
        active = next(i for i, content in enumerate(rejected["contents"]) if content["parts"] == [{"text": "pending"}])
        retry_active = next(i for i, content in enumerate(retry["contents"]) if content["parts"] == [{"text": "pending"}])
        assert rejected["contents"][active:] == retry["contents"][retry_active:]
        assert retry["contents"][retry_active + 1]["parts"] == first_parts
        assert retry["contents"][retry_active + 3]["parts"] == second_parts
        assert retry["contents"][-1]["parts"] == [{"functionResponse": {"name": "calculator", "response": {"result": 4}}}]
        before = next(result.tokens for prepared, result in measured if prepared.get("tools") and
                      "contents" in prepared and prepared["contents"] == rejected["contents"])
        after = next(result.tokens for prepared, result in measured if "contents" in prepared and prepared["contents"] == retry["contents"])
        assert after < before < 200000
        rendered = token_estimate.render_input(retry)
        assert rendered.count("exact-write-signature") == rendered.count("exact-second-signature") == 1
        assert "approximate cl100k_base (generic fallback)" in output.getvalue()
        assert "outcome: recovered" in output.getvalue()
        assert call_log.load_conversation(resumed[0])[1] == "short summary"
        run_repl(config, input_stream=StringIO("/history\nexit\n"), output_stream=StringIO(),
                 resumed=(resumed[0], *call_log.load_conversation(resumed[0])))
        assert len(bodies) == 5
    assert network == []


@pytest.mark.parametrize("stage", ["rejection outcome", "summary outcome", "recovery input"])
def test_recovery_detail_failure_stops_before_any_later_action(config, monkeypatch, install_fake_urlopen, stage):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    scripted_estimate(monkeypatch, 174000, reduced=140000)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    calls = install_fake_urlopen([rejection(), "short summary", "answer", "later answer"])
    write = call_log.write_detail
    def fail(kind, **fields):
        if ((stage == "rejection outcome" and kind == "attempt_end" and fields["outcome"] == "error")
                or (stage == "summary outcome" and kind == "attempt_end" and fields["answer"] == "short summary")
                or (stage == "recovery input" and kind == "attempt_start" and "short summary" in fields["system"])):
            raise call_log.AuditError("detail failed")
        return write(kind, **fields)
    monkeypatch.setattr(call_log, "write_detail", fail)
    with pytest.raises(call_log.AuditError, match="detail failed"):
        run_repl(config, input_stream=StringIO("pending\nlater\nexit\n"), output_stream=StringIO(), resumed=resumed)
    committed = stage == "recovery input"
    assert len(calls) == (1 if stage == "rejection outcome" else 2)
    assert call_log.load_conversation(resumed[0])[:3] == ((resumed[1][-2:], "short summary", []) if committed else
                                                   (resumed[1], None, []))


def test_usage_cache_unknown_then_recovery_failure_never_reuses_success_counts(config, monkeypatch, install_fake_urlopen):
    from tests.test_detailed_audit import lines
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    scripted_estimate(monkeypatch, 174000, reduced=140000)
    resumed = seed(config, ({"role": "user", "content": "old-context " * 300},))
    calls = install_fake_urlopen([
        {"content": "cached answer", "usage": {"cost": 0.2, "prompt_tokens": 174005, "completion_tokens": 4,
                                               "prompt_tokens_details": {"cached_tokens": 170000}}},
        {"content": "answer without usage"},
        rejection(message="test-key This model's maximum context length is 128000 tokens. However, you requested 130000 tokens."),
        {"content": "short summary", "usage": {"cost": 0.1, "prompt_tokens": 999, "completion_tokens": 5}},
        TimeoutError("test-key recovery timed out"),
    ])
    output = StringIO()
    run_repl(config, input_stream=StringIO("/usage\ncached\n/usage\nunknown\n/usage\nrejected\n/usage\nexit\n"),
             output_stream=output, resumed=resumed)
    assert len(calls) == 5
    text = output.getvalue()
    assert "No ordinary exchange assessed" in text
    assert "estimated input: 174000" in text and "reported input: 174005" in text
    after_cached = text.split("llm> answer without usage")[-1]
    assert "reported input: 174005" not in after_cached
    assert "reported input: 999" not in after_cached
    assert "reported input: unknown" in after_cached
    assert "outcome: recovery failed" in after_cached
    assert "spend: $0.3000" in text
    assert "test-key" not in text
    assert "test-key" not in json.dumps(entries())
    assert "test-key" not in json.dumps(lines(call_log.detail_path()))
