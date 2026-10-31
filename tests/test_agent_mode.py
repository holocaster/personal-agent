import json
import re
from io import BytesIO, StringIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from personal_agent import call_log
from personal_agent.routing import router, runtime_config
from personal_agent.terminal.repl import run_repl
from personal_agent.tools import registry as tools, webfetch, workspace


def _entries():
    return [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]


def _requests(calls):
    return [json.loads(call["request"].data) for call in calls]


def _names(request):
    return {tool["function"]["name"] for tool in request["tools"]}


PLAN_TOOLS = {"session_logs", "list_files", "read_file", "search_text", "calculator", "current_time", "todo", "webfetch", "question"}


def test_mode_commands_are_local_validate_arguments_and_switch_only_subsequent_turns(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["first", "second", "third"])
    output = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(
            "/mode\n/mode plan\n/mode\n/mode PLAN\n/mode build extra\n/help\n"
            "summarize this line\n/mode build\nsummarize this other line\n/retry\nexit\n"
        ),
        output_stream=output,
    )

    text = output.getvalue()
    assert text.startswith("Provider/model: openrouter vendor/test-model\nModels.dev catalog fetched ")
    assert "refresh with /models refresh.\nbuild\n" in text
    assert "plan\nplan\n" in text
    assert text.count("Error: usage: /mode [plan|build|auto]") == 2
    assert "/mode [plan|build|auto]" in text
    assert len(calls) == 3
    assert [_names(request) for request in _requests(calls)][0] == PLAN_TOOLS
    assert "write" in _names(_requests(calls)[1])
    assert "write" in _names(_requests(calls)[2])
    assert [entry["type"] for entry in _entries()].count("attempt") == 3
    assert all("mode" not in entry for entry in _entries())


def test_resume_starts_build_without_replaying_prior_run_mode(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["first", "second"])
    config = runtime_config.load()
    run_repl(config, input_stream=StringIO("/mode plan\nsummarize this line\nexit\n"), output_stream=StringIO())
    session_id = call_log.current_session_id()
    turns, summary, todos, _ = call_log.load_conversation(session_id)
    output = StringIO()

    run_repl(
        config, input_stream=StringIO("/mode\nsummarize this other line\nexit\n"), output_stream=output,
        resumed=(session_id, turns, summary, todos, call_log.load_conversation(session_id)[3]),
    )

    assert "build\n" in output.getvalue()
    assert _names(_requests(calls)[0]) == PLAN_TOOLS
    assert "write" in _names(_requests(calls)[1])
    assert [m["content"] for m in _requests(calls)[1]["messages"] if m["role"] == "user"] == [
        "summarize this line", "summarize this other line"
    ]


def test_interactive_mode_footer_and_completion_keep_existing_status(route_env, install_fake_urlopen):
    from personal_agent.terminal.repl import COMMANDS

    class Box:
        def __init__(self):
            self.lines = iter(["/mode plan", "/model", "summarize this line", "/mode build", "/exit"])
            self.footer = None
            self.snapshots = []

        def read(self):
            self.snapshots.append(self.footer())
            return next(self.lines)

    box = Box()
    calls = install_fake_urlopen([{"content": "answer", "usage": {"cost": 0.0009}}])
    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=box)

    assert "/mode" in COMMANDS
    assert box.snapshots[0] == " mode: build · openrouter vendor/test-model · API key · ctx unknown · $0.0000 · /help"
    assert box.snapshots[1] == " mode: plan · openrouter vendor/test-model · API key · ctx unknown · $0.0000 · /help"
    assert re.fullmatch(r" mode: plan · openrouter vendor/test-model · API key · ctx ~\d+/\d+ public · "
                        r"\$0\.0009 \(1 reported\) · /help", box.snapshots[3])
    assert box.footer() == " mode: build · openrouter vendor/test-model · API key · ctx unknown · $0.0009 (1 reported) · /help"
    assert _names(_requests(calls)[0]) == PLAN_TOOLS


def test_plan_allows_read_only_tools_and_webfetch_with_both_confirmation_outcomes(
    route_env, install_fake_urlopen, tmp_path, monkeypatch
):
    workspace.configure_workspace(tmp_path)
    (tmp_path / "note.txt").write_text("hello world\n")
    fetched = []

    class Response(BytesIO):
        status = 200
        headers = {"Content-Type": "text/plain"}

        def geturl(self):
            return "https://example.com/"

    class Opener:
        def open(self, request, timeout):
            fetched.append(request.full_url)
            return Response(b"safe content")

    monkeypatch.setattr(webfetch, "build_opener", lambda *handlers: Opener())
    calls = install_fake_urlopen([
        {"tool_calls": [
            {"id": "l", "name": "list_files", "arguments": {}},
            {"id": "r", "name": "read_file", "arguments": {"path": "note.txt"}},
            {"id": "s", "name": "search_text", "arguments": {"text": "hello"}},
            {"id": "c", "name": "calculator", "arguments": {"expression": "2+2"}},
            {"id": "t", "name": "current_time", "arguments": {}},
            {"id": "d", "name": "todo", "arguments": {"todos": [{"content": "Inspect", "status": "in_progress"}]}},
            {"id": "w1", "name": "webfetch", "arguments": {"url": "https://example.com/"}},
            {"id": "w2", "name": "webfetch", "arguments": {"url": "https://example.com/"}},
        ]},
        "done",
    ])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("/mode plan\nsummarize this line\ny\nn\nexit\n"), output_stream=output)

    results = [entry for entry in _entries() if entry["type"] == "tool_execution"]
    assert len(results) == 8
    assert [result["ok"] for result in results] == [True] * 7 + [False]
    assert results[1]["result"]["content"].startswith("1\thello world")
    assert results[2]["result"]["matches"]
    assert results[3]["result"]["result"] == 4
    assert results[6]["result"]["content"] == "safe content"
    assert results[7]["error"] == "change rejected by the user"
    assert fetched == ["https://example.com/"]
    assert output.getvalue().count("Fetch this URL? [y/N]") == 2
    assert [_names(request) for request in _requests(calls)] == [PLAN_TOOLS, PLAN_TOOLS]
    system = _requests(calls)[1]["messages"][0]["content"]
    assert "do not change the workspace" in system
    assert "switch to build or auto mode with /mode build or /mode auto" in system
    assert "untrusted data" in system
    assert "Todo List" in system


def test_plan_denies_mutating_tools_before_validation_and_confirmation_even_with_shell_registered(
    route_env, install_fake_urlopen, tmp_path
):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    (tmp_path / "note.txt").write_text("before")
    calls = install_fake_urlopen([
        {"tool_calls": [
            {"id": "w", "name": "write", "arguments": {"path": "new.txt", "content": "created"}},
            {"id": "e", "name": "edit", "arguments": {"path": "note.txt", "old_string": "before", "new_string": "after"}},
            {"id": "sh", "name": "shell", "arguments": {"command": "touch shell-created"}},
            {"id": "ok", "name": "calculator", "arguments": {"expression": "3*3"}},
            {"id": "unknown", "name": "invented", "arguments": {}},
        ]},
        {"tool_calls": [
            {"id": "badw", "name": "write", "arguments_raw": "{"},
            {"id": "bade", "name": "edit", "arguments": {}},
            {"id": "badsh", "name": "shell", "arguments": {"command": 42}},
        ]},
        "done",
    ])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("/mode plan\nsummarize this line\nexit\n"), output_stream=output)

    results = [entry for entry in _entries() if entry["type"] == "tool_execution"]
    assert [entry["name"] for entry in results] == ["write", "edit", "shell", "calculator", "invented", "write", "edit", "shell"]
    for entry in results[:3] + results[-3:]:
        assert entry["ok"] is False
        assert "plan mode" in entry["error"]
        assert entry["arguments"] is None
    attempts = [entry for entry in _entries() if entry["type"] == "attempt"]
    assert attempts[0]["tool_calls"][0]["arguments"] == {"path": "new.txt", "content": "created"}
    assert results[3]["ok"] is True
    assert results[4]["error"] == "unknown tool 'invented'"
    assert (tmp_path / "note.txt").read_text() == "before"
    assert not (tmp_path / "new.txt").exists()
    assert not (tmp_path / "shell-created").exists()
    assert "Apply this change?" not in output.getvalue()
    assert "Run this command?" not in output.getvalue()
    assert [_names(request) for request in _requests(calls)] == [PLAN_TOOLS | {"job_status"}] * 3


def test_plan_denies_apply_patch_before_validation_and_confirmation_and_omits_it_from_the_plan_tool_set(
    route_env, install_fake_urlopen, tmp_path
):
    workspace.configure_workspace(tmp_path)
    (tmp_path / "note.txt").write_text("before")
    patch = "*** Begin Patch\n*** Update File: note.txt\n-before\n+after\n*** End Patch"
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "p", "name": "apply_patch", "arguments": {"patch": patch}}]},
        "done",
    ])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("/mode plan\nsummarize this line\nexit\n"), output_stream=output)

    results = [entry for entry in _entries() if entry["type"] == "tool_execution"]
    assert results[0]["name"] == "apply_patch"
    assert results[0]["ok"] is False
    assert results[0]["error"] == "tool 'apply_patch' is unavailable in plan mode"
    assert results[0]["arguments"] is None
    assert (tmp_path / "note.txt").read_text() == "before"
    assert "Apply this change?" not in output.getvalue()
    assert [_names(request) for request in _requests(calls)] == [PLAN_TOOLS, PLAN_TOOLS]


def test_switch_to_plan_then_retry_preserves_route_conversation_and_todos(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "d", "name": "todo", "arguments": {"todos": [
            {"content": "Inspect", "status": "in_progress"},
        ]}}]},
        "first answer", "second answer", "retried", "later",
    ])
    output = StringIO()
    run_repl(
        runtime_config.load(),
        input_stream=StringIO(
            "summarize this line\nsummarize the followup\n/mode plan\n/retry\nsummarize this other line\nexit\n"
        ), output_stream=output,
        memory_notes=[{"text": "remember this", "added": "2026-09-26T00:00:00Z"}],
    )

    requests = _requests(calls)
    assert "write" in _names(requests[0])
    assert [_names(request) for request in requests[3:]] == [PLAN_TOOLS, PLAN_TOOLS]
    assert {request["model"] for request in requests} == {"vendor/test-model"}
    assert [m["content"] for m in requests[4]["messages"] if m["role"] == "user"] == [
        "summarize this line", "summarize the followup", "summarize this other line"
    ]
    for request in requests[3:]:
        system = request["messages"][0]["content"]
        assert "Facts the user asked to be remembered" in system
        assert "Inspect" in system
        assert "switch to build" in system
    assert "Turn undone." not in output.getvalue()


def test_build_mode_keeps_existing_tool_set_and_confirmation_after_switch(route_env, install_fake_urlopen, tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "w", "name": "write", "arguments": {"path": "note.txt", "content": "done"}}]},
        "complete",
    ])
    output = StringIO()
    run_repl(
        runtime_config.load(), input_stream=StringIO("/mode plan\n/mode build\nsummarize this line\ny\nexit\n"),
        output_stream=output,
    )

    assert (tmp_path / "note.txt").read_text() == "done"
    assert "Apply this change? [y/N]" in output.getvalue()
    assert "shell" in _names(_requests(calls)[0])
    assert _names(_requests(calls)[0]) == _names(_requests(calls)[1])
    assert "switch to build" not in _requests(calls)[0]["messages"][0]["content"]


def test_build_without_shell_registered_keeps_shell_unavailable(route_env, install_fake_urlopen):
    calls = install_fake_urlopen("done")
    run_repl(runtime_config.load(), input_stream=StringIO("summarize this line\nexit\n"), output_stream=StringIO())

    assert "shell" not in _names(_requests(calls)[0])
    assert "write" in _names(_requests(calls)[0])


def test_plan_remains_plan_during_provider_retries(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    calls = install_fake_urlopen([
        HTTPError("https://openrouter.ai", 503, "temporary", None, None),
        HTTPError("https://openrouter.ai", 503, "temporary", None, None),
        "answer",
    ])
    run_repl(runtime_config.load(), input_stream=StringIO("/mode plan\nsummarize this line\nexit\n"), output_stream=StringIO())

    assert len(calls) == 3
    assert [_names(request) for request in _requests(calls)] == [PLAN_TOOLS] * 3
    assert [_requests(calls)[i]["model"] for i in range(3)] == ["vendor/test-model"] * 3
    assert all("/mode build" in request["messages"][0]["content"] for request in _requests(calls))


def test_plan_rejects_shell_even_when_opted_out_of_registration(route_env, install_fake_urlopen, tmp_path):
    workspace.configure_workspace(tmp_path)
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "s", "name": "shell", "arguments": {"command": "touch marker"}}]},
        "done",
    ])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("/mode plan\nsummarize this line\nexit\n"), output_stream=output)

    assert [_names(request) for request in _requests(calls)] == [PLAN_TOOLS] * 2
    result = next(entry for entry in _entries() if entry["type"] == "tool_execution")
    assert result["error"] == "tool 'shell' is unavailable in plan mode"
    assert not (tmp_path / "marker").exists()
    assert "Run this command?" not in output.getvalue()


def test_plan_preserves_summary_and_compression_stays_tool_free(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["one", "two", "three", "summary text", "four"])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO(
            "summarize first\nsummarize second\nsummarize third\n/mode plan\n/compress\nsummarize fourth\nexit\n"
        ),
        output_stream=StringIO(),
    )

    requests = _requests(calls)
    assert len(requests) == 5
    assert "tools" not in requests[3]
    assert _names(requests[4]) == PLAN_TOOLS
    assert "Conversation Summary of earlier turns:\nsummary text" in requests[4]["messages"][0]["content"]


def test_auto_mode_commands_retry_and_resume_are_run_local(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["one", "two", "three"])
    output = StringIO()
    config = runtime_config.load()
    run_repl(config, input_stream=StringIO(
        "/mode auto\n/model\n/mode nope\n/mode auto extra\n/mode\n"
        "summarize this line\n/retry\nexit\n"
    ), output_stream=output)
    assert "Error: usage: /mode [plan|build|auto]" in output.getvalue()
    assert output.getvalue().count("Error: usage: /mode [plan|build|auto]") == 2
    assert "auto\n" in output.getvalue()
    assert len(calls) == 2
    assert [_names(r) for r in _requests(calls)] == [_names(_requests(calls)[0])] * 2
    assert all(request["model"] == "vendor/test-model" for request in _requests(calls))
    assert all("auto mode" in request["messages"][0]["content"].lower() for request in _requests(calls))
    session_id = call_log.current_session_id()
    turns, summary, todos, _ = call_log.load_conversation(session_id)
    run_repl(config, input_stream=StringIO("/mode\nsummarize again\nexit\n"), output_stream=output,
             resumed=(session_id, turns, summary, todos, call_log.load_conversation(session_id)[3]))
    assert "build\n" in output.getvalue()
    assert "auto mode" not in _requests(calls)[2]["messages"][0]["content"].lower()
    assert len(calls) == 3


def test_auto_runs_prepared_mutating_calls_without_consuming_the_next_task(route_env, install_fake_urlopen, tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    patch = "*** Begin Patch\n*** Add File: patch.txt\n+patched\n*** End Patch"
    calls = install_fake_urlopen([
        {"tool_calls": [
            {"id": "w", "name": "write", "arguments": {"path": "note.txt", "content": "before"}},
            {"id": "e", "name": "edit", "arguments": {"path": "note.txt", "old_string": "before", "new_string": "after"}},
            {"id": "p", "name": "apply_patch", "arguments": {"patch": patch}},
            {"id": "s", "name": "shell", "arguments": {"command": "touch marker.txt"}},
        ]}, "done", "next answer",
    ])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("/mode auto\nsummarize work\nsummarize next\nexit\n"), output_stream=output)
    assert (tmp_path / "note.txt").read_text() == "after"
    assert (tmp_path / "patch.txt").read_text() == "patched\n"
    assert (tmp_path / "marker.txt").exists()
    assert [entry["ok"] for entry in _entries() if entry["type"] == "tool_execution"] == [True] * 4
    assert "llm> next answer" in output.getvalue()
    assert "tool> shell(" in output.getvalue()
    assert "Apply this change?" not in output.getvalue()
    assert "Run this command?" not in output.getvalue()
    assert "write:" not in output.getvalue()
    assert len(calls) == 3


@pytest.mark.parametrize("answer,approved", [("y", False), ("no", False), ("", False), (" YES  ", True)])
def test_auto_only_flagged_shell_needs_strong_confirmation_after_external_content(
    route_env, install_fake_urlopen, tmp_path, monkeypatch, answer, approved,
):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    class Response(BytesIO):
        status = 200
        headers = {"Content-Type": "text/plain"}

        def geturl(self):
            return "https://example.org/page"

    class Opener:
        def open(self, request, timeout):
            return Response(b"untrusted content")

    monkeypatch.setattr(webfetch, "build_opener", lambda *handlers: Opener())
    calls = install_fake_urlopen([{"tool_calls": [
        {"id": "f", "name": "webfetch", "arguments": {"url": "https://example.org/page"}},
        {"id": "s", "name": "shell", "arguments": {"command": "touch safe.txt"}},
        {"id": "d", "name": "shell", "arguments": {"command": "eval touch marker.txt"}},
    ]}, "done"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("/mode auto\nsummarize work\n" + (answer + "\n" if answer else "")),
             output_stream=output)
    assert (tmp_path / "safe.txt").exists()
    assert (tmp_path / "marker.txt").exists() is approved
    results = [entry for entry in _entries() if entry["type"] == "tool_execution"]
    assert [entry["ok"] for entry in results] == [True, True, approved]
    assert "dangerous_rules" not in results[1]
    assert results[2]["dangerous_rules"] == ["eval"]
    assert "untrusted content" in str(_requests(calls)[1])
    text = output.getvalue()
    assert text.count("shell:") == 1
    assert "eval touch marker.txt\nDangerous command: eval" in text
    assert "Warning: this turn fetched https://example.org/page" in text
    assert text.count("Type 'yes' to run this dangerous command:") == 1
    assert "Run this command?" not in text and "Fetch this URL?" not in text
    assert "Warning:" not in text.split("shell:")[0]


def test_auto_bad_arguments_and_workspace_paths_fail_before_effects(route_env, install_fake_urlopen, tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    install_fake_urlopen([{"tool_calls": [
        {"id": "w", "name": "write", "arguments": {"path": "../escaped", "content": "no"}},
        {"id": "e", "name": "edit", "arguments": {"path": "missing", "old_string": "a", "new_string": "b"}},
        {"id": "s", "name": "shell", "arguments": {"command": 42}},
        {"id": "f", "name": "webfetch", "arguments": {"url": "file:///etc/passwd"}},
    ]}, "done"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("/mode auto\nsummarize work\nexit\n"), output_stream=output)
    assert not (tmp_path.parent / "escaped").exists()
    results = [entry for entry in _entries() if entry["type"] == "tool_execution"]
    assert len(results) == 4 and all(not entry["ok"] for entry in results)
    assert "Apply this change?" not in output.getvalue() and "Fetch this URL?" not in output.getvalue()


def test_auto_websearch_uses_registered_definition_and_warns_only_on_flagged_shell(
    route_env, install_fake_urlopen, tmp_path, monkeypatch,
):
    from tests.test_websearch import FakeResponse
    from personal_agent.tools import websearch

    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    tools.enable_websearch_tool("tvly-secret")
    searches = []

    class Opener:
        def open(self, request, timeout):
            searches.append(request)
            return FakeResponse({"results": [{"title": "Title", "url": "https://example.org/a", "content": "Excerpt"}]})

    monkeypatch.setattr(websearch, "build_opener", lambda *handlers: Opener())
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "q", "name": "websearch", "arguments": {"query": "news"}},
                        {"id": "s", "name": "shell", "arguments": {"command": "touch safe.txt"}}]},
        {"tool_calls": [{"id": "d", "name": "shell", "arguments": {"command": "eval touch marker.txt"}}]},
        "done",
    ])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("/mode auto\nsummarize work\nYES\nexit\n"), output_stream=output)
    assert (tmp_path / "safe.txt").exists() and (tmp_path / "marker.txt").exists()
    assert len(searches) == 1
    assert "websearch" in _names(_requests(calls)[0])
    assert [_names(request) for request in _requests(calls)] == [_names(_requests(calls)[0])] * 3
    assert "Search the web?" not in output.getvalue()
    assert output.getvalue().count("Warning: this turn saw external search content") == 1
    assert "news" in output.getvalue()
    assert "tvly-secret" not in output.getvalue() + str(_entries())


def test_auto_keeps_build_tool_set_across_retries_and_followups(
    route_env, install_fake_urlopen, monkeypatch,
):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    calls = install_fake_urlopen([
        HTTPError("https://openrouter.ai", 503, "temporary", None, None),
        HTTPError("https://openrouter.ai", 503, "temporary", None, None),
        {"tool_calls": [{"id": "c", "name": "calculator", "arguments": {"expression": "2+2"}}]},
        "done",
    ])
    run_repl(runtime_config.load(), input_stream=StringIO("/mode auto\nsummarize this line\nexit\n"),
             output_stream=StringIO())
    requests = _requests(calls)
    assert len(requests) == 4
    assert [_names(request) for request in requests] == [_names(requests[0])] * 4
    assert "write" in _names(requests[0]) and "webfetch" in _names(requests[0])
    assert "shell" not in _names(requests[0]) and "websearch" not in _names(requests[0])
    assert all("Auto mode" in request["messages"][0]["content"] for request in requests)
    assert [request["model"] for request in requests] == ["vendor/test-model"] * 4


def test_switching_to_auto_changes_only_later_retried_turns(route_env, install_fake_urlopen, tmp_path):
    workspace.configure_workspace(tmp_path)
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "w", "name": "write", "arguments": {"path": "note.txt", "content": "first"}}]},
        "rejected",
        {"tool_calls": [{"id": "w2", "name": "write", "arguments": {"path": "note.txt", "content": "second"}}]},
        "written",
    ])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("summarize work\nn\n/mode auto\n/retry\nexit\n"),
             output_stream=output)
    assert (tmp_path / "note.txt").read_text() == "second"
    assert output.getvalue().count("Apply this change? [y/N]") == 1
    assert [entry["ok"] for entry in _entries() if entry["type"] == "tool_execution"] == [False, True]
    assert "Build mode" in _requests(calls)[0]["messages"][0]["content"]
    assert all("Auto mode" in request["messages"][0]["content"] for request in _requests(calls)[2:])


def test_live_mode_changes_apply_to_same_batch_and_provider_followup(route_env, install_fake_urlopen, tmp_path):
    workspace.configure_workspace(tmp_path)
    calls = install_fake_urlopen([{"tool_calls": [
        {"id": "w1", "name": "write", "arguments": {"path": "one.txt", "content": "one"}},
        {"id": "w2", "name": "write", "arguments": {"path": "two.txt", "content": "two"}},
    ]}, "done"])
    mode = ["build"]
    prompts = []

    def confirm(*args):
        prompts.append(args[0])
        mode[0] = "auto"
        return True

    result = router.route("write files", runtime_config.load(), mode=lambda: mode[0], confirm=confirm)
    assert result.ok
    assert prompts == ["write"]
    assert (tmp_path / "one.txt").read_text() == "one"
    assert (tmp_path / "two.txt").read_text() == "two"
    assert "Auto mode" in _requests(calls)[1]["messages"][0]["content"]


@pytest.mark.parametrize("switches,expected_mode", [(1, "auto"), (2, "plan")])
def test_queued_question_mode_changes_refresh_provider_input_audit_and_retry_budget(
    route_env, install_fake_urlopen, monkeypatch, switches, expected_mode,
):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from personal_agent import token_estimate
    from personal_agent.terminal.input_box import InputBox

    monkeypatch.setattr(router, "_sleep", lambda seconds: None)
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "q", "name": "question", "arguments": {"questions": [{"text": "Value?"}]}}]},
        HTTPError("https://openrouter.ai", 503, "temporary", None, None),
        HTTPError("https://openrouter.ai", 503, "temporary", None, None),
        "done",
    ])
    mode = ["build"]
    assessments = []
    call_log.open_detail()
    try:
        with create_pipe_input() as pipe:
            box = InputBox((), input=pipe, output=DummyOutput())
            box.on_mode_toggle = lambda: mode.__setitem__(0, {"build": "auto", "auto": "plan"}[mode[0]])

            def question(questions):
                pipe.send_text("answer\r" + "\x1b[Z" * switches)
                return {"answers": [{"question": questions[0]["text"], "answer": box.ask("Value? ")}]}

            result = router.route(
                "ask a question", runtime_config.load(), mode=lambda: mode[0],
                question=question, run_busy=box.run_busy,
                on_assessment=lambda assessment: assessments.append(dict(assessment)),
            )
    finally:
        call_log.close_detail()

    assert result.ok and result.answer == "done"
    assert mode[0] == expected_mode
    requests = _requests(calls)
    details = [json.loads(line) for line in Path(call_log.detail_path()).read_text().splitlines()]
    starts = [entry for entry in details if entry["type"] == "attempt_start"]
    assert len(requests) == len(starts) == 4
    assert all(request["session_id"] == call_log.current_session_id() for request in requests)
    assert [entry["attempt"] for entry in _entries() if entry["type"] == "attempt"] == [1, 2, 3, 4]
    assert len(assessments) == 8
    for index, request in enumerate(requests[1:], 1):
        names = _names(request)
        expected_mutations = {"write", "edit", "apply_patch"} if expected_mode == "auto" else set()
        assert names & {"write", "edit", "apply_patch"} == expected_mutations
        system = request["messages"][0]["content"]
        assert ("Auto mode" if expected_mode == "auto" else "do not change the workspace") in system
        assert "Build mode" not in system
        assert starts[index]["system"] == system
        assert {tool["name"] for tool in starts[index]["tools"]} == names
        assert json.loads(request["messages"][-1]["content"])["answers"][0]["answer"] == "answer"
        prepared = {key: value for key, value in request.items() if key not in {"model", "max_tokens", "provider", "session_id"}}
        expected_estimate = token_estimate.estimate(request["model"], prepared)
        assert assessments[index * 2]["estimate"] == expected_estimate
        assert assessments[index * 2 + 1]["estimate"] == expected_estimate


def test_mode_refresh_preserves_completed_overflow_compression(route_env, install_fake_urlopen):
    from tests.test_context_overflow import rejection

    calls = install_fake_urlopen([rejection(), "short summary", "done"])
    mode = ["build"]
    summaries = []
    history = [({"role": "user", "content": "old-context " * 300},),
               ({"role": "user", "content": "protected one"},),
               ({"role": "user", "content": "protected two"},)]

    def busy(operation):
        if len(calls) == 2:
            mode[0] = "plan"
        return operation()

    result = router.route("pending", runtime_config.load(), history_turns=history,
                          on_compression=summaries.append, mode=lambda: mode[0], run_busy=busy)
    assert result.ok, result.error
    assert len(calls) == 3
    assert summaries == ["short summary"]
    request = json.loads(calls[-1]["request"].data)
    assert "do not change the workspace" in request["messages"][0]["content"]
    assert {"write", "edit", "apply_patch"}.isdisjoint(_names(request))


def test_busy_start_cancellation_leaves_no_orphan_detail(route_env):
    def busy(operation):
        raise KeyboardInterrupt()

    call_log.open_detail()
    try:
        with pytest.raises(KeyboardInterrupt):
            router.route("task", runtime_config.load(), run_busy=busy)
    finally:
        call_log.close_detail()
    details = [json.loads(line) for line in Path(call_log.detail_path()).read_text().splitlines()]
    starts = {entry["attempt_id"] for entry in details if entry["type"] == "attempt_start"}
    assert all(entry["attempt_id"] in starts for entry in details if entry["type"] == "attempt_end")


@pytest.mark.parametrize("name,arguments", [
    ("write", {"path": "note.txt", "content": "after"}),
    ("shell", {"command": "touch note.txt"}),
])
def test_switch_to_plan_blocks_a_pending_approved_mutation(route_env, tmp_path, name, arguments):
    from personal_agent.providers.contract import ToolCall

    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    mode = ["build"]

    def confirm(*args):
        mode[0] = "plan"
        return True

    result = tools.execute_batch([ToolCall("1", name, arguments)], confirm=confirm, mode=lambda: mode[0])[0]
    assert result.is_error
    assert "unavailable in plan mode" in result.content["error"]
    assert not (tmp_path / "note.txt").exists()


def test_live_switch_from_auto_to_build_restores_next_confirmation(route_env, tmp_path):
    from personal_agent.providers.contract import ToolCall

    workspace.configure_workspace(tmp_path)
    mode = ["auto"]
    prompts = []

    def busy(operation):
        result = operation()
        mode[0] = "build"
        return result

    results = tools.execute_batch([
        ToolCall("1", "write", {"path": "one.txt", "content": "one"}),
        ToolCall("2", "write", {"path": "two.txt", "content": "two"}),
    ], mode=lambda: mode[0], run_busy=busy, confirm=lambda *args: prompts.append(args[0]) or False)
    assert [result.is_error for result in results] == [False, True]
    assert prompts == ["write"]
    assert (tmp_path / "one.txt").read_text() == "one"
    assert not (tmp_path / "two.txt").exists()


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("name,switches", [("write", 2), ("webfetch", 2), ("webfetch", 1)])
def test_queued_switch_from_auto_restores_confirmation_before_effects(
    route_env, tmp_path, monkeypatch, name, switches, approved,
):
    import threading
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from personal_agent.providers.contract import ToolCall
    from personal_agent.terminal.input_box import InputBox

    workspace.configure_workspace(tmp_path)
    mode = ["auto"]
    events = []
    audit = []

    class Response(BytesIO):
        status = 200
        headers = {"Content-Type": "text/plain"}

        def geturl(self):
            return "https://example.com/"

    class Opener:
        def open(self, request, timeout):
            events.append("fetch")
            return Response(b"content")

    monkeypatch.setattr(webfetch, "build_opener", lambda *handlers: Opener())
    arguments = ({"path": "note.txt", "content": "hello"} if name == "write"
                 else {"url": "https://example.com/"})
    with create_pipe_input() as pipe:
        box = InputBox((), input=pipe, output=DummyOutput())
        box.on_mode_toggle = lambda: mode.__setitem__(0, {"auto": "plan", "plan": "build"}[mode[0]])
        pipe.send_text("task\r" + "\x1b[Z" * switches + ("y\r" if approved else "n\r"))
        assert box.read() == "task"

        def confirm(*args):
            assert not any(thread.name == "agent-mode-input" for thread in threading.enumerate())
            assert events == []
            assert not (tmp_path / "note.txt").exists()
            events.append("confirmation")
            return box.ask("Approve? ") == "y"

        result = tools.execute_batch(
            [ToolCall("1", name, arguments)], mode=lambda: mode[0], run_busy=box.run_busy,
            confirm=confirm, on_confirmation=lambda *args: audit.append(args),
        )[0]

    assert mode[0] == ("build" if switches == 2 else "plan")
    assert result.is_error is not approved
    assert events == (["confirmation", "fetch"] if name == "webfetch" and approved else ["confirmation"])
    assert (tmp_path / "note.txt").exists() is (name == "write" and approved)
    assert audit == [("1", name, "approved" if approved else "rejected", ())]
