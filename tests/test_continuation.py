import json
from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from prompt_toolkit.output.base import Size

from personal_agent import call_log
from personal_agent.__main__ import main
from personal_agent.routing import router, runtime_config
from tests.fakes import FakeOpenRouterResponse
from personal_agent.terminal.repl import run_repl
from personal_agent.tools import workspace


class Box:
    def __init__(self, tasks, answers=()):
        self.tasks = iter(tasks)
        self.answers = iter(answers)

    def read(self):
        return next(self.tasks)

    def ask(self, question):
        answer = next(self.answers)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def ask_secret(self, question):
        return self.ask(question)

    def terminal_size(self):
        return Size(rows=24, columns=80)


def tool(name, arguments, identifier="call"):
    return {"tool_calls": [{"id": identifier, "name": name, "arguments": arguments}]}


def entries():
    return [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]


@pytest.mark.parametrize("restart", [False, True])
def test_retry_keeps_question_answer_and_write_result_without_repeating_tools(
    route_env, monkeypatch, tmp_path, install_fake_urlopen, restart
):
    monkeypatch.setenv("PA_MAX_TOOL_ROUNDS", "2")
    workspace.configure_workspace(tmp_path)
    calls = install_fake_urlopen([
        tool("question", {"questions": [{"text": "Which option?", "choices": ["A", "B"]}]}, "question"),
        tool("write", {"path": "note.txt", "content": "option B"}, "write"),
        tool("calculator", {"expression": "1+1"}, "blocked"), "completed"])
    tasks = ["build it", "exit"] if restart else ["build it", "/retry", "exit"]
    run_repl(runtime_config.load(), input_box=Box(tasks, ["2", "y"]), output_stream=StringIO())
    if restart:
        monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))
        main(["--resume", call_log.current_session_id()])

    assert len(calls) == 4
    retry_messages = json.loads(calls[-1]["request"].data)["messages"]
    results = [json.loads(message["content"]) for message in retry_messages if message["role"] == "tool"]
    assert results == [
        {"answers": [{"question": "Which option?", "answer": "B"}]},
        {"path": "note.txt", "bytes_written": 8, "created": True}]
    assert "blocked" not in json.dumps(retry_messages)
    assert (tmp_path / "note.txt").read_text() == "option B"
    rows = entries()
    assert [row["name"] for row in rows if row["type"] == "tool_execution"] == ["question", "write"]
    assert len([row for row in rows if row["type"] == "routed_task_submitted"]) == 1
    turns, _, _, state = call_log.load_conversation(call_log.current_session_id())
    assert len(turns) == 1 and len(turns[0]) == 6
    assert state == 1


@pytest.mark.parametrize("provider", ["openrouter", "openai", "anthropic", "gemini"])
@pytest.mark.parametrize("restart", [False, True])
def test_followup_failure_continues_completed_results_across_providers(
    route_env, monkeypatch, install_fake_urlopen, provider, restart
):
    monkeypatch.setenv("PA_PROVIDER", provider)
    monkeypatch.setenv(runtime_config.API_KEY_ENV_VARS[provider], "test-key")
    first = tool("calculator", {"expression": "2+2"}, "completed-call")
    parts = [{"functionCall": {"name": "calculator", "args": {"expression": "2+2"}},
              "thoughtSignature": "EXACT-SIGNATURE"}]
    if provider == "gemini":
        first = FakeOpenRouterResponse({"candidates": [{"content": {"parts": parts}}]})
    calls = install_fake_urlopen([first, ValueError("follow-up failed"), ValueError("failed again"), "done"])
    tasks = ["calculate", "exit"] if restart else ["calculate", "/retry", "/retry", "exit"]
    run_repl(runtime_config.load(), input_stream=StringIO("\n".join(tasks) + "\n"), output_stream=StringIO())
    if restart:
        monkeypatch.setattr("sys.stdin", StringIO("/retry\n/retry\nexit\n"))
        main(["--resume", call_log.current_session_id()])

    assert len(calls) == 4
    for call in calls[2:]:
        payload = json.loads(call["request"].data)
        if provider == "gemini":
            assert payload["contents"][1] == {"role": "model", "parts": parts}
            response = payload["contents"][2]["parts"][0]["functionResponse"]
            assert response == {"name": "calculator", "response": {"result": 4}}
        elif provider == "anthropic":
            assert payload["messages"][-1]["content"][0]["content"] == json.dumps({"result": 4})
        else:
            assert payload["messages"][-1]["content"] == json.dumps({"result": 4})
    assert len([row for row in entries() if row["type"] == "tool_execution"]) == 1
    turns, _, _, state = call_log.load_conversation(call_log.current_session_id())
    assert len(turns) == 1 and len(turns[0]) == 4
    assert state == 1


@pytest.mark.parametrize("restart", [False, True])
def test_interrupted_batch_retains_completed_write_and_marks_remaining_calls(route_env, install_fake_urlopen, tmp_path, monkeypatch, restart):
    workspace.configure_workspace(tmp_path)
    calls = install_fake_urlopen([{"tool_calls": [
        {"id": "written", "name": "write", "arguments": {"path": "note.txt", "content": "written once"}},
        {"id": "interrupted", "name": "question", "arguments": {"questions": [{"text": "Next?"}]}},
        {"id": "not-started", "name": "calculator", "arguments": {"expression": "2+2"}}]}, "done"])
    tasks = ["work", "exit"] if restart else ["work", "/retry", "exit"]
    run_repl(runtime_config.load(), input_box=Box(tasks, ["y", KeyboardInterrupt()]), output_stream=StringIO())
    if restart:
        monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))
        main(["--resume", call_log.current_session_id()])

    assert len(calls) == 2
    messages = json.loads(calls[-1]["request"].data)["messages"]
    results = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
    assert results[0]["created"] is True
    assert "interrupted" in results[1]["error"].lower()
    assert "not executed" in results[2]["error"].lower()
    assert (tmp_path / "note.txt").read_text() == "written once"
    assert [row["name"] for row in entries() if row["type"] == "tool_execution"] == ["write"]


@pytest.mark.parametrize("command", ["/clear", "new task"])
def test_clear_or_new_task_discards_pending_state(route_env, install_fake_urlopen, command):
    calls = install_fake_urlopen([tool("calculator", {"expression": "2+2"}), ValueError("failed"), "new answer", "rerun"])
    output = StringIO()
    commands = ["first", command, "/retry", "exit"] if command == "/clear" else ["first", command, "/undo", "/retry", "exit"]

    run_repl(runtime_config.load(), input_stream=StringIO("\n".join(commands) + "\n"), output_stream=output)

    assert call_log.load_pending_turn(call_log.current_session_id()) is None
    if command == "/clear":
        assert len(calls) == 2 and "no task to retry" in output.getvalue()
    else:
        assert len(calls) == 4
        for call in calls[2:]:
            assert not any(message["role"] == "tool" for message in json.loads(call["request"].data)["messages"])


def test_repeated_limit_failures_renew_round_allowance_and_keep_todos(route_env, monkeypatch, install_fake_urlopen):
    monkeypatch.setenv("PA_MAX_TOOL_ROUNDS", "1")
    todos = [{"content": "finish preserved work", "status": "in_progress"}]
    calls = install_fake_urlopen([
        tool("calculator", {"expression": "2+2"}, "first"),
        tool("calculator", {"expression": "3+3"}, "blocked-one"),
        tool("todo", {"todos": todos}, "todo"),
        tool("calculator", {"expression": "4+4"}, "blocked-two"), "done"])

    run_repl(runtime_config.load(), input_stream=StringIO("work\n/retry\n/retry\nexit\n"), output_stream=StringIO())

    assert len(calls) == 5
    last = json.loads(calls[-1]["request"].data)
    assert "finish preserved work" in last["messages"][0]["content"]
    assert [message["tool_call_id"] for message in last["messages"] if message["role"] == "tool"] == ["first", "todo"]
    assert "blocked-" not in json.dumps(last)
    assert [row["name"] for row in entries() if row["type"] == "tool_execution"] == ["calculator", "todo"]
    assert call_log.load_conversation(call_log.current_session_id())[3] == 1


def test_retry_after_restart_uses_current_config_and_mode_without_replaying_completed_calls(
    route_env, monkeypatch, install_fake_urlopen, tmp_path
):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("PA_MAX_TOOL_ROUNDS", "1")
    workspace.configure_workspace(tmp_path)
    calls = install_fake_urlopen([
        tool("calculator", {"expression": "2+2"}, "done"), tool("calculator", {"expression": "3+3"}, "blocked"),
        tool("write", {"path": "denied.txt", "content": "must not write"}, "denied"), "finished"])
    run_repl(runtime_config.load(), input_box=Box(["work", "exit"]), output_stream=StringIO())
    sid = call_log.current_session_id()
    call_log.reset_session()
    monkeypatch.setenv("PA_PROVIDER", "openai")
    monkeypatch.setenv("PA_MODEL", "new-model")
    box = Box(["/mode plan", "/config", "/retry", "exit"], ["context", "budget", "350000", "done"])

    run_repl(runtime_config.load(), input_box=box, output_stream=StringIO(), resumed=(sid, *call_log.load_conversation(sid)))

    assert len(calls) == 4
    retry = json.loads(calls[2]["request"].data)
    assert calls[2]["request"].full_url.startswith("https://api.openai.com/")
    assert retry["model"] == "new-model"
    assert "Investigate and discuss only" in retry["messages"][0]["content"]
    assert [message["tool_call_id"] for message in retry["messages"] if message["role"] == "tool"] == ["done"]
    assert not (tmp_path / "denied.txt").exists()


def test_gemini_pending_retry_switches_provider_using_only_normalized_prefix(route_env, monkeypatch, install_fake_urlopen):
    monkeypatch.setenv("PA_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    parts = [{"functionCall": {"name": "calculator", "args": {"expression": "2+2"}},
              "thoughtSignature": "GEMINI-ONLY-SIGNATURE"}]
    first = FakeOpenRouterResponse({"candidates": [{"content": {"parts": parts}}]})
    calls = install_fake_urlopen([first, ValueError("follow-up failed"), "done"])
    run_repl(runtime_config.load(), input_box=Box(["work", "exit"]), output_stream=StringIO())
    sid = call_log.current_session_id()
    call_log.reset_session()
    monkeypatch.setenv("PA_PROVIDER", "openai")

    run_repl(runtime_config.load(), input_box=Box(["/retry", "exit"]), output_stream=StringIO(),
             resumed=(sid, *call_log.load_conversation(sid)))

    assert len(calls) == 3
    payload = json.loads(calls[-1]["request"].data)
    assert calls[-1]["request"].full_url.startswith("https://api.openai.com/")
    assert "GEMINI-ONLY-SIGNATURE" not in json.dumps(payload)
    assert "contents" not in payload
    assert payload["messages"][-2]["tool_calls"][0]["id"] == "gemini-call-0"
    assert payload["messages"][-1] == {"role": "tool", "tool_call_id": "gemini-call-0", "content": json.dumps({"result": 4})}
    assert len([row for row in entries() if row["type"] == "tool_execution"]) == 1
    assert call_log.load_conversation(call_log.current_session_id())[3] == 1


@pytest.mark.parametrize("restart", [False, True])
def test_pending_fetched_urls_survive_retry_for_confirmation_warnings(route_env, monkeypatch, install_fake_urlopen, tmp_path, restart):
    from personal_agent.tools import registry
    workspace.configure_workspace(tmp_path)
    fetch = registry._REGISTRY["webfetch"]
    prepared = SimpleNamespace(display_path="https://example.com/page", preview="fetch")
    monkeypatch.setitem(registry._REGISTRY, "webfetch", replace(fetch, prepare=lambda args: prepared,
        apply=lambda item: {"url": "https://example.com/page", "content": "external", "status": 200}))
    calls = install_fake_urlopen([tool("webfetch", {"url": "https://example.com/page"}), ValueError("failed"),
                                 tool("write", {"path": "note.txt", "content": "done"}), "finished"])
    output = StringIO()
    tasks = ["fetch", "exit"] if restart else ["fetch", "/retry", "exit"]
    run_repl(runtime_config.load(), input_box=Box(tasks, ["y", "y"]), output_stream=output)
    if restart:
        resumed = (call_log.current_session_id(), *call_log.load_conversation(call_log.current_session_id()))
        run_repl(runtime_config.load(), input_box=Box(["/retry", "exit"], ["y"]), resumed=resumed, output_stream=output)

    assert len(calls) == 4
    assert "Warning: this turn fetched https://example.com/page" in output.getvalue()


@pytest.mark.parametrize("restart", [False, True])
def test_gemini_limit_excludes_unexecuted_raw_response_and_preserves_signature(route_env, monkeypatch, install_fake_urlopen, restart):
    monkeypatch.setenv("PA_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("PA_MAX_TOOL_ROUNDS", "1")
    parts = [{"functionCall": {"id": "vendor-id", "name": "calculator", "args": {"expression": "2+2"}},
              "thoughtSignature": "SAVED-SIGNATURE"}]
    first = FakeOpenRouterResponse({"candidates": [{"content": {"parts": parts}}]})
    blocked = FakeOpenRouterResponse({"candidates": [{"content": {"parts": [
        {"functionCall": {"id": "blocked", "name": "calculator", "args": {"expression": "3+3"}},
         "thoughtSignature": "BLOCKED-SIGNATURE"}]}}]})
    calls = install_fake_urlopen([first, blocked, "done"])
    run_repl(runtime_config.load(), input_stream=StringIO("work\nexit\n" if restart else "work\n/retry\nexit\n"), output_stream=StringIO())
    if restart:
        monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))
        main(["--resume", call_log.current_session_id()])

    retry = json.loads(calls[-1]["request"].data)["contents"]
    assert retry[1] == {"role": "model", "parts": parts}
    assert retry[2]["parts"][0]["functionResponse"] == {"id": "vendor-id", "name": "calculator", "response": {"result": 4}}
    assert "BLOCKED" not in json.dumps(retry) and "blocked" not in json.dumps(retry)


@pytest.mark.parametrize("restart", [False, True])
def test_redacted_pending_task_arguments_and_raw_replay_continue_after_key_change(
    route_env, monkeypatch, install_fake_urlopen, tmp_path, restart
):
    secret = "original-sensitive-key"
    monkeypatch.setenv("PA_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    workspace.configure_workspace(tmp_path)
    parts = [{"functionCall": {"name": "write", "args": {"path": "note.txt", "content": "secret=" + secret}},
              "thoughtSignature": "signed-" + secret}]
    first = FakeOpenRouterResponse({"candidates": [{"content": {"parts": parts}}]})
    calls = install_fake_urlopen([first, ValueError("failed"), "done"])
    original_task = "build using " + secret
    tasks = [original_task, "exit"] if restart else [original_task, "/config", "/retry", "exit"]
    answers = ["y"] if restart else ["y", "key", "gemini", "replacement-key", "done"]
    run_repl(runtime_config.load(), input_box=Box(tasks, answers), output_stream=StringIO())
    failed = next(row for row in entries() if row["type"] == "turn_end" and row["status"] == "error")
    assert secret not in json.dumps(failed)
    assert failed["task_digest"] == call_log.submission_digest(original_task)
    if restart:
        monkeypatch.setenv("GEMINI_API_KEY", "replacement-key")
        monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))
        main(["--resume", call_log.current_session_id()])

    assert len(calls) == 3
    assert calls[-1]["request"].get_header("X-goog-api-key") == "replacement-key"
    retry = json.loads(calls[-1]["request"].data)
    assert secret not in json.dumps(retry)
    assert "signed-[redacted]" in json.dumps(retry)
    assert (tmp_path / "note.txt").read_text() == "secret=[redacted]"
    assert len([row for row in entries() if row["type"] == "tool_execution"]) == 1


@pytest.mark.parametrize("restart", [False, True])
def test_manual_compression_keeps_pending_prefix_separate_and_rebases_gemini(
    route_env, monkeypatch, install_fake_urlopen, restart
):
    monkeypatch.setenv("PA_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    parts = [{"functionCall": {"name": "calculator", "args": {"expression": "2+2"}},
              "thoughtSignature": "KEPT-SIGNATURE"}]
    first = FakeOpenRouterResponse({"candidates": [{"content": {"parts": parts}}]})
    calls = install_fake_urlopen(["answer one", "answer two", "answer three", first, ValueError("failed"), "older summary", "done"])
    script = "old one\nold two\nold three\npending\n/compress\n"
    run_repl(runtime_config.load(), input_stream=StringIO(script + ("exit\n" if restart else "/retry\nexit\n")), output_stream=StringIO())
    if restart:
        monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))
        main(["--resume", call_log.current_session_id()])

    assert len(calls) == 7
    compression = json.loads(calls[5]["request"].data)
    assert "pending" not in json.dumps(compression["contents"])
    retry = json.loads(calls[-1]["request"].data)
    assert "older summary" in retry["systemInstruction"]["parts"][0]["text"]
    assert "old one" not in json.dumps(retry["contents"])
    assert retry["contents"][-2] == {"role": "model", "parts": parts}
    assert retry["contents"][-1]["parts"][0]["functionResponse"]["response"] == {"result": 4}
    turns, summary, _, state = call_log.load_conversation(call_log.current_session_id())
    assert len(turns) == 3 and summary == "older summary" and state == 4


@pytest.mark.parametrize("restart", [False, True])
def test_gemini_automatic_compression_then_followup_failure_keeps_exact_pending_replay(
    route_env, monkeypatch, restart
):
    from personal_agent.providers import http
    monkeypatch.setenv("PA_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    overrides = [{"provider": "gemini", "model": "vendor/test-model", "total_tokens": 17000, "output_tokens": 100}]
    monkeypatch.setenv("PA_CONTEXT_CAPACITY_OVERRIDES", json.dumps(overrides))
    config = runtime_config.load()
    sid = call_log.start_session(config)
    older = ({"role": "user", "content": "old-context " + "history " * 3000},)
    protected = (({"role": "user", "content": "protected one"},), ({"role": "user", "content": "protected two"},))
    for turn in (older, *protected):
        call_log.write_turn_end("ok", messages=turn)
    first_parts = [
        {"text": "hidden thought", "thought": True, "thoughtSignature": "thought-signature"},
        {"text": "model "}, {"text": "one", "thoughtSignature": "opaque " * 1400},
        {"functionCall": {"id": "vendor-first", "name": "calculator", "args": {"expression": "2+2"}},
         "thoughtSignature": "exact-signature"},
        {"functionCall": {"name": "calculator", "args": {"expression": "4+4"}}},
        {"text": "", "thoughtSignature": "trailing-signature"}]
    second_parts = [{"text": "model two", "thoughtSignature": "hidden " * 1400},
                    {"functionCall": {"name": "calculator", "args": {"expression": "6+6"}}}]
    responses = iter([first_parts, second_parts, ValueError("failed after compression"), [{"text": "done"}]])
    calls = []

    def fake_http(request, timeout=None):
        body = json.loads(request.data)
        calls.append(body)
        if "tools" in body:
            parts = next(responses)
            if isinstance(parts, BaseException):
                raise parts
            return FakeOpenRouterResponse({"candidates": [{"content": {"parts": parts}}]})
        return FakeOpenRouterResponse({"candidates": [{"content": {"parts": [{"text": "short summary"}]}}]})

    monkeypatch.setattr(http, "urlopen", fake_http)
    resumed = (sid, *call_log.load_conversation(sid))
    run_repl(config, input_stream=StringIO("pending\nexit\n" if restart else "pending\n/retry\nexit\n"),
             resumed=resumed, output_stream=StringIO())
    if restart:
        assert call_log.load_conversation(sid)[:2] == (protected, "short summary")
        monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))
        main(["--resume", sid])

    assert len(calls) == 5
    assert sum("tools" not in call for call in calls) == 1
    retry = calls[-1]
    assert "old-context" not in json.dumps(retry)
    assert "short summary" in retry["systemInstruction"]["parts"][0]["text"]
    active = retry["contents"][-5:]
    assert active[0] == {"role": "user", "parts": [{"text": "pending"}]}
    assert active[1] == {"role": "model", "parts": first_parts}
    assert active[3] == {"role": "model", "parts": second_parts}
    assert active[4]["parts"][0]["functionResponse"]["response"] == {"result": 12}
    assert len([row for row in entries() if row["type"] == "tool_execution"]) == 3


@pytest.mark.parametrize("path,value", [
    (("version",), 2), (("version",), True), (("provider",), []), (("model",), None),
    (("messages",), {}), (("messages", 1, "content"), {}),
    (("messages", 1, "tool_calls", 0, "arguments"), []),
    (("messages", 1, "tool_calls", 0, "arguments_raw"), {}),
    (("messages", 1, "tool_calls", 0, "id_is_generated"), 1),
    (("messages", 2, "id"), "wrong"), (("messages", 2, "is_error"), "yes"),
    (("messages", 2, "id_is_generated"), False), (("messages", 2), None),
    (("fetched_urls",), [{}]), (("replay", "consumed"), True),
    (("replay", "consumed"), 100), (("replay", "active_start"), -1),
    (("replay", "active_contents_start"), 1), (("replay", "contents", 1, "parts"), "bad"),
    (("replay", "contents", 1, "parts", 0, "thoughtSignature"), {}),
    (("replay", "contents", 1, "parts", 0, "thought"), "true"),
    (("replay", "contents", 1, "parts", 0, "text"), "mixed with function call"),
    (("replay", "contents", 1, "parts", 0, "unexpected"), {"arbitrary": "structure"}),
    (("replay", "contents", 1, "parts", 0, "functionCall", "args"), {"expression": "changed"}),
    (("replay", "contents", 2, "parts", 0, "functionResponse", "response"), {"result": 999}),
    (("task_digest",), "0" * 64), (("ordinal",), 0),
])
def test_malformed_persisted_continuation_fails_before_resume_dispatch(
    route_env, monkeypatch, install_fake_urlopen, capsys, path, value
):
    monkeypatch.setenv("PA_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    parts = [{"functionCall": {"name": "calculator", "args": {"expression": "2+2"}}, "thoughtSignature": "saved"}]
    calls = install_fake_urlopen([FakeOpenRouterResponse({"candidates": [{"content": {"parts": parts}}]}), ValueError("failed")])
    run_repl(runtime_config.load(), input_stream=StringIO("task\nexit\n"), output_stream=StringIO())
    rows = entries()
    failed = next(row for row in rows if row["type"] == "turn_end")
    target = failed if path[0] in {"ordinal", "task_digest"} else failed["continuation"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    log_path = Path(call_log.session_log_path())
    log_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    before = log_path.read_bytes()
    monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))

    with pytest.raises(SystemExit) as exc_info:
        main(["--resume", call_log.current_session_id()])

    assert exc_info.value.code == 1
    assert "invalid pending turn" in capsys.readouterr().err
    assert len(calls) == 2 and log_path.read_bytes() == before


def test_old_logs_without_explicit_continuation_do_not_reconstruct_partial_attempts(route_env, monkeypatch, install_fake_urlopen):
    calls = install_fake_urlopen(["old answer", tool("calculator", {"expression": "2+2"}), ValueError("failed")])
    run_repl(runtime_config.load(), input_stream=StringIO("old\nfailed\nexit\n"), output_stream=StringIO())
    rows = entries()
    for row in rows:
        if row["type"] == "turn_end" and row["status"] == "error":
            for field in ("continuation", "ordinal", "task_digest"):
                del row[field]
    Path(call_log.session_log_path()).write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))

    main(["--resume", call_log.current_session_id()])

    assert call_log.load_pending_turn(call_log.current_session_id()) is None
    assert len(calls) == 3 and len(call_log.load_conversation(call_log.current_session_id())[0]) == 1


def test_pending_snapshot_write_failure_stops_before_retry(route_env, monkeypatch, install_fake_urlopen):
    calls = install_fake_urlopen([tool("calculator", {"expression": "2+2"}), ValueError("failed"), "must not dispatch"])
    original = call_log._write_line

    def fail(entry, **kwargs):
        if "continuation" in entry:
            raise OSError("pending write failed")
        return original(entry, **kwargs)

    monkeypatch.setattr(call_log, "_write_line", fail)
    with pytest.raises(OSError, match="pending write failed"):
        run_repl(runtime_config.load(), input_stream=StringIO("task\n/retry\nexit\n"), output_stream=StringIO())

    assert len(calls) == 2 and call_log.load_pending_turn(call_log.current_session_id()) is None
