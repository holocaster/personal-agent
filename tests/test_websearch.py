import json
from io import BytesIO, StringIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from personal_agent import call_log
from personal_agent import __main__ as main_module
from personal_agent.providers.contract import ToolCall
from personal_agent.routing import runtime_config
from personal_agent.terminal.repl import run_repl
from personal_agent.tools import registry as tools, webfetch, websearch, workspace


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.body = BytesIO(payload if isinstance(payload, bytes) else json.dumps(payload).encode())

    def read(self, size):
        return self.body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture
def search(monkeypatch, tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_websearch_tool("tvly-secret")
    calls = []
    replies = [FakeResponse({"results": [{"title": "Title", "url": "https://example.org/a", "content": "Excerpt"}]})]

    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    monkeypatch.setattr(websearch, "build_opener", lambda *handlers: Opener())
    return calls, replies


def _call(query, confirm=lambda *args: True, name="websearch"):
    return tools.execute_batch([ToolCall(id="1", name=name, arguments={"query": query})], confirm=confirm)[0]


def test_search_opt_in_schema_and_disabled_calls(search):
    definition = next(item for item in tools.definitions_for_mode("plan") if item.name == "websearch")
    assert definition.parameters == {"type": "object", "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 500}},
        "required": ["query"], "additionalProperties": False}
    assert "tvly-secret" not in str(definition)
    assert "websearch" in [item.name for item in tools.definitions_for_mode("build")]
    tools.reset_registry()
    assert "websearch" not in [item.name for item in tools.definitions_for_mode("plan")]
    result = _call("hello", confirm=lambda *args: pytest.fail("asked for disabled Tool"))
    assert result.is_error and "unknown" in result.content["error"]
    assert search[0] == []


@pytest.mark.parametrize("arguments", [{}, {"query": " "}, {"query": 42}, {"query": "x" * 501}, {"query": "a", "extra": 1}])
def test_search_invalid_arguments_do_not_confirm_or_request(search, arguments):
    result = tools.execute_batch([ToolCall(id="1", name="websearch", arguments=arguments)],
                                 confirm=lambda *args: pytest.fail("invalid query prompted"))[0]
    assert result.is_error and search[0] == []


def test_search_requires_confirmation_and_posts_one_basic_bounded_request(search):
    calls, _ = search
    assert _call("exact query", confirm=lambda *args: False).is_error
    assert _call("exact query", confirm=None).is_error
    assert calls == []
    seen = []
    result = _call(" exact query ", confirm=lambda *args: seen.append(args) or True)
    assert seen[0][:3] == ("websearch", " exact query ", " exact query ")
    assert result.content == {"results": [{"title": "Title", "url": "https://example.org/a", "snippet": "Excerpt"}]}
    assert len(calls) == 1
    request, timeout = calls[0]
    assert timeout == 30 and request.full_url == "https://api.tavily.com/search" and request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer tvly-secret"
    assert json.loads(request.data) == {"query": " exact query ", "search_depth": "basic", "max_results": 5,
        "chunks_per_source": 1, "include_answer": False, "include_raw_content": False,
        "include_images": False, "auto_parameters": False}


@pytest.mark.parametrize("reply,expected", [
    (HTTPError("https://api.tavily.com/search", 401, "secret", None, None), "401"),
    (HTTPError("https://api.tavily.com/search", 429, "secret", None, None), "429"),
    (HTTPError("https://api.tavily.com/search", 432, "secret", None, None), "432"),
    (HTTPError("https://api.tavily.com/search", 433, "secret", None, None), "433"),
    (HTTPError("https://api.tavily.com/search", 500, "secret", None, None), "500"),
    (URLError("tvly-secret"), "request failed"), (TimeoutError("tvly-secret"), "timed out"),
    (FakeResponse(b"not json"), "malformed"), (FakeResponse({"results": {}}), "malformed"),
    (FakeResponse(b"x" * (1024 * 1024 + 1)), "limit"),
])
def test_search_failures_are_safe_tool_errors_without_retry(search, reply, expected):
    calls, replies = search
    replies[:] = [reply]
    result = _call("question")
    assert result.is_error and expected in result.content["error"]
    assert "tvly-secret" not in str(result.content) and len(calls) == 1


def test_search_projects_at_most_five_valid_sources_and_bounds_serialized_output(search, tmp_path):
    calls, replies = search
    replies[:] = [FakeResponse({"answer": "ignore", "results": [
        {"title": "A" * 300 + "tvly-secret", "url": "https://example.org/" + str(i),
         "content": "B" * 400 + "tvly-secret", "raw_content": "ignore"} for i in range(7)
    ] + [{"title": "bad", "url": "file:///etc/passwd", "content": "bad"}]})]
    result = _call("question")
    assert not result.is_error and len(result.content["results"]) == 5
    assert all(len(item["title"]) <= 200 and len(item["snippet"]) <= 300 for item in result.content["results"])
    assert "ignore" not in str(result.content) and "tvly-secret" not in str(result.content)
    workspace.configure_workspace(tmp_path, "80")
    replies[:] = [FakeResponse({"results": [{"title": "A" * 100, "url": "https://example.org", "content": "B"}]})]
    result = _call("question")
    assert result.content == {"results": []}
    assert len(json.dumps(result.content, ensure_ascii=False).encode()) <= 80
    workspace.configure_workspace(tmp_path, "1")
    replies[:] = [FakeResponse({"results": []})]
    assert _call("question").is_error


def test_search_zero_hits_is_not_failure(search):
    search[1][:] = [FakeResponse({"results": []})]
    assert _call("question").content == {"results": []}


def test_search_deeply_nested_response_is_a_safe_tool_error(search):
    calls, replies = search
    replies[:] = [FakeResponse(b'{"results": [], "ignored": ' + b'[' * 12000 + b'0' + b']' * 12000 + b'}')]
    result = _call("question")
    assert result.is_error and result.content == {"error": "malformed Tavily response"}
    assert len(calls) == 1


def test_search_redaction_keeps_output_cap_after_replacement(search, tmp_path):
    search[1][:] = [FakeResponse({"results": [{"title": "k", "url": "https://e.co", "content": "k"}]})]
    cap = len(json.dumps({"results": [{"title": "k", "url": "https://e.co", "snippet": "k"}]}).encode())
    workspace.configure_workspace(tmp_path, str(cap))
    result = tools.execute_batch([ToolCall(id="1", name="websearch", arguments={"query": "news"})],
                                 confirm=lambda *args: True, result_secrets=("k",))[0]
    assert not result.is_error and result.content == {"results": []}
    assert len(json.dumps(result.content).encode()) <= cap


@pytest.mark.parametrize("entries", [[{"title": "a", "url": "https://example.org", "content": 123}],
                                     [{"title": "a", "url": "https://example.org"}],
                                     [123]])
def test_search_malformed_result_is_a_tool_error(search, entries):
    search[1][:] = [FakeResponse({"results": entries})]
    result = _call("question")
    assert result.is_error and "malformed" in result.content["error"]


def test_search_omits_unusable_urls_and_preserves_original_order(search):
    search[1][:] = [FakeResponse({"results": [
        {"title": "bad", "url": "http:///missing-host", "content": "x"},
        {"title": "first", "url": "https://example.org/a", "content": "a"},
        {"title": "bad", "url": "https://example.org/space here", "content": "x"},
        {"title": "secret link", "url": "https://example.org/tvly-secret", "content": "x"},
        {"title": "second", "url": "http://example.org/b", "content": "b"},
    ]})]
    result = _call("question")
    assert not result.is_error
    assert [item["title"] for item in result.content["results"]] == ["first", "second"]


@pytest.mark.parametrize("key,enabled", [(None, False), ("  ", False), ("tvly-secret", True)])
def test_startup_opt_in_from_dotenv_after_provider_setup(route_env, monkeypatch, tmp_path, key, enabled):
    if key is not None:
        (tmp_path / ".env").write_text(f"TAVILY_API_KEY={key}\n")
    captured = []
    monkeypatch.setattr(main_module, "run_repl", lambda *args, **kwargs: captured.append(
        ("websearch" in [item.name for item in tools.TOOL_DEFS],
         "webfetch" in [item.name for item in tools.TOOL_DEFS])))
    main_module.main([])
    assert captured == [(enabled, True)]


def test_search_redirect_refuses_to_forward_bearer_key(search, monkeypatch):
    calls = []

    class RedirectingOpener:
        def open(self, request, timeout):
            calls.append(request)
            raise HTTPError(request.full_url, 302, "redirect to https://example.org", {
                "Location": "https://example.org"}, None)

    monkeypatch.setattr(websearch, "build_opener", lambda *handlers: RedirectingOpener())
    result = _call("question")
    assert result.is_error and "302" in result.content["error"]
    assert "example.org" not in str(result.content)
    assert len(calls) == 1


def test_search_batch_requires_separate_approvals_and_warns_only_after_success(search, tmp_path):
    search[1][:] = [FakeResponse({"results": []})]
    seen = []
    calls = [ToolCall(id="1", name="websearch", arguments={"query": "rejected"}),
             ToolCall(id="2", name="websearch", arguments={"query": "approved"}),
             ToolCall(id="3", name="write", arguments={"path": "note.txt", "content": "note"})]

    def confirm(name, path, preview, rules, sources):
        seen.append((name, path, sources))
        return path != "rejected"

    results = tools.execute_batch(calls, confirm=confirm)
    assert [result.is_error for result in results] == [True, False, False]
    assert len(search[0]) == 1
    assert seen[0] == ("websearch", "rejected", ())
    assert seen[1] == ("websearch", "approved", ())
    assert "approved" in str(seen[2]) and "rejected" not in str(seen[2])


@pytest.mark.parametrize("decision,reply", [(False, None), (True, HTTPError(
    "https://api.tavily.com/search", 429, "secret", None, None))])
def test_rejected_or_failed_search_never_warns_for_later_write(search, decision, reply):
    if reply is not None:
        search[1][:] = [reply]
    seen = []

    def confirm(name, path, preview, rules, sources):
        seen.append((name, sources))
        return decision if name == "websearch" else False

    calls = [ToolCall(id="1", name="websearch", arguments={"query": "news"}),
             ToolCall(id="2", name="write", arguments={"path": "note.txt", "content": "note"})]
    result = tools.execute_batch(calls, confirm=confirm)
    assert result[0].is_error and seen == [("websearch", ()), ("write", ())]


def test_tavily_key_is_not_passed_to_an_approved_shell_tool(search, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    tools.enable_shell_tool()
    result = tools.execute_batch([ToolCall(id="1", name="shell", arguments={
        "command": "printenv TAVILY_API_KEY"})], confirm=lambda *args: True)[0]
    assert not result.is_error
    assert result.content["stdout"] == "" and result.content["exit_code"] != 0


@pytest.mark.parametrize("mode", ["plan", "build"])
@pytest.mark.parametrize("answer,requests", [("yes", 1), ("no", 0), ("", 0)])
def test_repl_search_confirmation_logging_and_provider_followup(
    route_env, install_fake_urlopen, search, monkeypatch, mode, answer, requests,
):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    query = "whole query " + "x" * 150
    provider = install_fake_urlopen([{"tool_calls": [{"id": "s1", "name": "websearch", "arguments": {"query": query}}]},
                                     "done"])
    output = StringIO()
    command = "/mode plan\n" if mode == "plan" else ""
    run_repl(runtime_config.load(), input_stream=StringIO(command + "research\n" + (answer + "\n" if answer else "")),
             output_stream=output)
    assert "Search the web? [y/N] " in output.getvalue()
    assert query in output.getvalue()
    assert len(search[0]) == requests
    assert len(provider) == 2
    first = json.loads(provider[0]["request"].data)
    second = json.loads(provider[1]["request"].data)
    assert "websearch" in [item["function"]["name"] for item in first["tools"]]
    assert "untrusted" in first["messages"][0]["content"]
    assert "websearch" in first["messages"][0]["content"]
    assert "Title" in str(second) if requests else "rejected" in str(second)
    log_text = Path(call_log.session_log_path()).read_text()
    assert "tvly-secret" not in output.getvalue() + log_text + str(second)
    entries = [json.loads(line) for line in log_text.splitlines()]
    execution = next(entry for entry in entries if entry["type"] == "tool_execution")
    assert execution["ok"] == bool(requests)
    assert execution["result"] == ({"results": [{"title": "Title", "url": "https://example.org/a", "snippet": "Excerpt"}]} if requests else None)


def test_repl_successful_search_warns_on_same_turn_change_but_not_next_turn(
    route_env, install_fake_urlopen, search, monkeypatch,
):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    install_fake_urlopen([
        {"tool_calls": [{"id": "s1", "name": "websearch", "arguments": {"query": "news"}}]},
        {"tool_calls": [{"id": "w1", "name": "write", "arguments": {"path": "note.txt", "content": "note"}}]},
        "done",
        {"tool_calls": [{"id": "w2", "name": "write", "arguments": {"path": "other.txt", "content": "other"}}]},
        "done",
    ])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("research then write\ny\nn\nwrite again\nn\nexit\n"),
             output_stream=output)
    first, second = output.getvalue().split("write: other.txt", 1)
    assert "external search content" in first and "news" in first
    assert "https://example.org/a" in first
    assert "external search content" not in second


def test_repl_redacts_tavily_key_in_provider_output_and_search_result(
    route_env, install_fake_urlopen, search, monkeypatch,
):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    search[1][:] = [FakeResponse({"results": [{"title": "tvly-secret", "url": "https://example.org/a",
                                                 "content": "tvly-secret in snippet"}]})]
    provider = install_fake_urlopen([
        {"content": "tvly-secret", "tool_calls": [{"id": "s1", "name": "websearch", "arguments": {
            "query": "tvly-secret"}}]}, "tvly-secret",
    ])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("research\ny\nexit\n"), output_stream=output)
    assert len(search[0]) == 1
    assert json.loads(search[0][0][0].data)["query"] == "[redacted]"
    assert "tvly-secret" not in output.getvalue() + Path(call_log.session_log_path()).read_text() + str(provider)


def test_repl_redacts_provider_key_from_search_sources_before_warning_and_followup(
    route_env, install_fake_urlopen, search, monkeypatch,
):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    provider_key = "test-key"
    search[1][:] = [FakeResponse({"results": [
        {"title": f"Title {provider_key}", "url": "https://example.org/one",
         "content": f"Excerpt {provider_key}"},
        {"title": "secret link", "url": f"https://example.org/{provider_key}",
         "content": "must not appear in warning"},
    ]})]
    provider = install_fake_urlopen([
        {"tool_calls": [{"id": "s1", "name": "websearch", "arguments": {"query": "news"}},
                        {"id": "w1", "name": "write", "arguments": {"path": "note.txt", "content": "note"}}]},
        "done",
    ])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("research\ny\nn\nexit\n"), output_stream=output)
    entries = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    result = next(entry["result"] for entry in entries if entry["type"] == "tool_execution" and
                  entry["name"] == "websearch")
    assert result == {"results": [{"title": "Title [redacted]", "url": "https://example.org/one",
                                   "snippet": "Excerpt [redacted]"}]}
    assert "external search content" in output.getvalue()
    followup = json.loads(provider[1]["request"].data)
    assert result in [json.loads(message["content"]) for message in followup["messages"]
                      if message.get("role") == "tool"]
    assert provider_key not in output.getvalue() + str(followup) + Path(call_log.session_log_path()).read_text()


@pytest.mark.parametrize("answer,requests", [(" YES ", 1), ("no", 0), (EOFError(), 0), (KeyboardInterrupt(), 0)])
def test_interactive_search_uses_input_box_and_interrupts_turn(
    route_env, install_fake_urlopen, search, monkeypatch, answer, requests,
):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    install_fake_urlopen([{"tool_calls": [{"id": "s1", "name": "websearch", "arguments": {
        "query": "a\nquery"}}]}, "done"])

    class Box:
        def __init__(self):
            self.tasks = iter(["research", "/exit"])
            self.prompts = []

        def read(self):
            return next(self.tasks)

        def ask(self, prompt):
            self.prompts.append(prompt)
            if isinstance(answer, BaseException):
                raise answer
            return answer

    box = Box()
    output = StringIO()
    run_repl(runtime_config.load(), input_box=box, output_stream=output)
    assert box.prompts == ["Search the web? [y/N] "]
    assert "a\nquery" in output.getvalue()
    assert len(search[0]) == requests
    if isinstance(answer, KeyboardInterrupt):
        assert "Interrupted." in output.getvalue()
        assert "\"status\": \"interrupted\"" in Path(call_log.session_log_path()).read_text()


def test_repl_search_then_webfetch_requires_a_second_confirmation(
    route_env, install_fake_urlopen, search, monkeypatch,
):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    calls = []

    class FetchResponse(FakeResponse):
        headers = {"Content-Type": "text/plain"}

        def geturl(self):
            return "https://example.org/a"

        def read1(self, size):
            return self.read(size)

    class FetchOpener:
        def open(self, request, timeout):
            calls.append(request)
            return FetchResponse(b"a page")

    monkeypatch.setattr(webfetch, "build_opener", lambda *handlers: FetchOpener())
    install_fake_urlopen([
        {"tool_calls": [{"id": "s1", "name": "websearch", "arguments": {"query": "news"}}]},
        {"tool_calls": [{"id": "f1", "name": "webfetch", "arguments": {"url": "https://example.org/a"}}]},
        "done",
    ])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("research\ny\nn\nexit\n"), output_stream=output)
    assert len(search[0]) == 1 and calls == []
    assert "Search the web? [y/N] " in output.getvalue()
    assert "Fetch this URL? [y/N] " in output.getvalue()
