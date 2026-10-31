import json
import signal
import subprocess
import sys
import time
from io import StringIO
from pathlib import Path

import pytest

from personal_agent import call_log
from personal_agent import __main__ as main_module
from personal_agent.providers.contract import ToolCall
from personal_agent.routing import runtime_config
from personal_agent.terminal.repl import run_repl
from personal_agent.tools import registry, mcp_resources


def test_configuration_and_mode_gates(tmp_path):
    assert mcp_resources.parse_config("  ") is None
    for value in ('[]', '{}', '{"name":"x","command":"sh","env":{}}',
                  '{"name":"x","command":"sh\\u0000"}'):
        with pytest.raises(ValueError, match="PA_MCP_SERVER"):
            mcp_resources.parse_config(value)
    config = mcp_resources.parse_config(json.dumps({"name": "local", "command": "server", "args": ["--x"]}))
    registry.enable_mcp_resources(config, tmp_path)
    for mode in ("plan", "build", "auto"):
        assert {name for name in (d.name for d in registry.definitions_for_mode(mode)) if name.startswith("mcp_")} == {
            "mcp_list_resources", "mcp_list_resource_templates", "mcp_read_resource"
        }
    for uri in ("catalog://item/{id}", "catalog://item\x85", "catalog://item\x7f", "catalog://item\n"):
        call = ToolCall(id="1", name="mcp_read_resource", arguments={"uri": uri})
        result = registry.execute_batch([call], confirm=lambda *args: pytest.fail("invalid call prompted"))[0]
        assert result.is_error
    registry.enable_mcp_resources(None, tmp_path)
    assert registry.execute_batch([ToolCall(id="2", name="mcp_list_resources", arguments={})])[0].is_error


def test_invalid_startup_config_exits_before_repl_without_echo(route_env, monkeypatch, capsys):
    monkeypatch.setenv("PA_MCP_SERVER", '{"name":"secret-name","command":"sh","other":"secret-value"}')
    monkeypatch.setattr(main_module, "run_repl", lambda *args, **kwargs: pytest.fail("REPL started"))
    with pytest.raises(SystemExit):
        main_module.main([])
    error = capsys.readouterr().err
    assert "PA_MCP_SERVER" in error
    assert "secret-name" not in error and "secret-value" not in error


def test_modern_fixture_discovery_template_read_and_cleanup(tmp_path, monkeypatch):
    marker = tmp_path / "launch"
    script = Path(__file__).parent / "fixtures" / "mcp_server.py"
    monkeypatch.setenv("PA_MCP_SENTINEL", "parent-secret")
    config = mcp_resources.parse_config(json.dumps({"name": "local", "command": sys.executable,
                                                    "args": [str(script), str(marker)]}))
    registry.enable_mcp_resources(config, tmp_path)
    calls = []
    def invoke(name, arguments, mode="plan", confirm=lambda *args: True):
        return registry.execute_batch([ToolCall(id="1", name=name, arguments=arguments)], mode=mode,
                                      confirm=lambda *args: calls.append(args) or confirm(*args))[0]
    assert invoke("mcp_list_resources", {}, confirm=lambda *args: False).is_error
    assert not marker.exists()
    resources = invoke("mcp_list_resources", {})
    assert not resources.is_error, resources.content
    assert resources.content["resources"][0]["uri"] == "catalog://fixed"
    assert marker.with_suffix(".exit").exists()
    assert "parent-secret" not in marker.read_text()
    templates = invoke("mcp_list_resource_templates", {})
    assert not templates.is_error, templates.content
    assert templates.content["resource_templates"][0]["uriTemplate"] == "catalog://items/{item}"
    read = invoke("mcp_read_resource", {"uri": "catalog://items/apple"})
    assert not read.is_error, read.content
    assert read.content["contents"][0]["text"] == "context for apple"
    assert "catalog://items/apple" in calls[-1][1]
    assert all(len(json.dumps(item.content, ensure_ascii=False).encode()) <= 32768 for item in (resources, templates, read))


def _fixture_call(tmp_path, fixture_mode, tool="mcp_list_resources", arguments=None, confirm=lambda *args: True,
                  mode="plan"):
    marker = tmp_path / "launch"
    script = Path(__file__).parent / "fixtures" / "mcp_server.py"
    config = mcp_resources.parse_config(json.dumps({"name": "local", "command": sys.executable,
                                                    "args": [str(script), str(marker), fixture_mode]}))
    registry.enable_mcp_resources(config, tmp_path)
    result = registry.execute_batch([ToolCall(id="1", name=tool, arguments=arguments or {})],
                                    confirm=confirm, mode=mode)[0]
    assert len(json.dumps(result.content, ensure_ascii=False).encode()) <= 32768
    return result, marker


def test_legacy_fallback_and_auto(tmp_path):
    result, marker = _fixture_call(tmp_path, "legacy", mode="auto", confirm=lambda *args: pytest.fail("auto prompted"))
    assert not result.is_error, result.content
    assert marker.with_suffix(".methods").read_text().splitlines()[:2] == ["server/discover", "initialize"]
    assert marker.with_suffix(".exit").exists()


@pytest.mark.parametrize("fixture_mode,expected", [
    ("empty", False), ("pages", False), ("huge-description", False),
    ("huge-uri", True), ("capless", True), ("server-error", True), ("malformed", True),
    ("many", False), ("endless", False), ("instructions", False),
])
def test_list_bounds_and_errors(tmp_path, fixture_mode, expected):
    result, marker = _fixture_call(tmp_path, fixture_mode)
    assert result.is_error is expected, result.content
    assert marker.with_suffix(".exit").exists()
    specific = {
        "huge-uri": "required provenance exceeds output limit",
        "capless": "Resources capability unavailable",
        "server-error": "server request failed",
        "malformed": "server request failed",
    }
    if fixture_mode in specific:
        assert result.content["error"] == f"MCP server 'local' list resources: {specific[fixture_mode]}"
    if fixture_mode == "many":
        assert result.content["truncated"] is True
        assert len(result.content["resources"]) == 100
    if fixture_mode == "endless":
        assert result.content["truncated"] is True
        assert marker.with_suffix(".methods").read_text().count("resources/list") == 10
    if fixture_mode == "pages":
        assert result.content["truncated"] is True
        assert marker.with_suffix(".methods").read_text().count("resources/list") == 2
    if fixture_mode == "huge-description":
        assert result.content["truncated"] is True
        assert result.content["resources"][0]["uri"] == "catalog://fixed"
    assert "private-server-secret" not in str(result.content)


@pytest.mark.parametrize("fixture_mode,expected_error", [
    ("empty", False), ("huge-text", False), ("blob", True), ("blob-only", True), ("missing", True),
])
def test_read_bounds_and_binary_rejection(tmp_path, fixture_mode, expected_error):
    result, marker = _fixture_call(tmp_path, fixture_mode, "mcp_read_resource", {"uri": "catalog://items/apple"})
    assert result.is_error is expected_error, result.content
    assert marker.with_suffix(".exit").exists()
    if fixture_mode in ("blob", "blob-only"):
        assert result.content["error"] == (
            "MCP server 'local' read resource: unsupported binary content [catalog://items/apple]")
    if fixture_mode == "missing":
        assert result.content["error"] == (
            "MCP server 'local' read resource: server request failed [catalog://items/apple]")
        assert "private-missing-detail" not in str(result.content)
    if fixture_mode == "huge-text":
        assert result.content["truncated"] is True
        assert result.content["contents"][0]["text"].endswith("🙂")
        assert len(result.content["contents"]) == 1


def test_missing_command_does_not_prompt_and_timeout_cleans_child(tmp_path, monkeypatch):
    config = mcp_resources.ServerConfig("local", "/missing/server", ())
    registry.enable_mcp_resources(config, tmp_path)
    result = registry.execute_batch([ToolCall(id="1", name="mcp_list_resources", arguments={})],
                                    confirm=lambda *args: True)[0]
    assert result.is_error and "local" in result.content["error"]
    monkeypatch.setattr(mcp_resources, "TIMEOUT_SECONDS", 0.2)
    result, marker = _fixture_call(tmp_path, "hang")
    assert result.is_error and "timed out" in result.content["error"]
    assert marker.with_suffix(".exit").exists()


@pytest.mark.parametrize("tool,key,first", [
    ("mcp_list_resources", "resources", "catalog://fixed"),
    ("mcp_list_resource_templates", "resource_templates", "catalog://items/{item}"),
])
def test_deadline_mid_pagination_returns_partial_result(tmp_path, monkeypatch, tool, key, first):
    monkeypatch.setattr(mcp_resources, "TIMEOUT_SECONDS", 0.5)
    result, marker = _fixture_call(tmp_path, "pages-hang", tool)
    assert not result.is_error, result.content
    assert result.content["truncated"] is True
    assert [next(iter(item.values())) for item in result.content[key]] == [first]
    assert marker.with_suffix(".exit").exists()


@pytest.mark.parametrize("fixture_mode", ["sampling", "elicitation", "legacy-sampling", "legacy-elicitation"])
def test_server_initiated_requests_are_rejected(tmp_path, fixture_mode):
    result, marker = _fixture_call(tmp_path, fixture_mode)
    assert not result.is_error, result.content
    assert result.content["resources"][0]["uri"] == "catalog://fixed"
    reply = json.loads(marker.with_suffix(".reply").read_text())
    assert reply["id"] == "srv1" and "result" not in reply and "error" in reply
    assert marker.with_suffix(".methods").read_text().count("resources/list") == 1
    assert marker.with_suffix(".exit").exists()


def test_hung_negotiation_and_early_exit_are_bounded_and_reaped(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_resources, "TIMEOUT_SECONDS", 0.5)
    result, marker = _fixture_call(tmp_path, "hang-init")
    assert result.content["error"] == "MCP server 'local' list resources: timed out"
    assert marker.with_suffix(".exit").exists()
    result, marker = _fixture_call(tmp_path, "exit-early")
    assert result.content["error"] == "MCP server 'local' list resources: server request failed"
    assert marker.with_suffix(".exit").exists()


def test_declined_eof_and_missing_callback_do_not_launch(tmp_path):
    for confirm in (lambda *args: False, lambda *args: None, None):
        result, marker = _fixture_call(tmp_path, "modern", confirm=confirm)
        assert result.content["error"] == "local — list resources: operation rejected by the user"
        assert not marker.exists()


def test_recovery_after_failure_and_method_allowlist(tmp_path):
    result, marker = _fixture_call(tmp_path, "missing", "mcp_read_resource", {"uri": "catalog://items/apple"})
    assert result.is_error
    result = registry.execute_batch([ToolCall(id="2", name="mcp_list_resources", arguments={})],
                                    confirm=lambda *args: True)[0]
    assert not result.is_error, result.content
    methods = set(marker.with_suffix(".methods").read_text().split())
    assert methods <= {"server/discover", "initialize", "notifications/initialized",
                       "resources/list", "resources/read"}
    assert {"resources/list"} <= methods


def test_input_required_is_rejected_without_retry(tmp_path):
    result, marker = _fixture_call(tmp_path, "input-required", "mcp_read_resource", {"uri": "catalog://fixed"})
    assert result.is_error and "unsupported interaction" in result.content["error"]
    assert marker.with_suffix(".methods").read_text().count("resources/read") == 1


def test_ctrl_c_reaps_server(tmp_path):
    marker = tmp_path / "launch"
    script = Path(__file__).parent / "fixtures" / "mcp_server.py"
    driver = (
        "import sys, signal; from pathlib import Path; "
        "signal.signal(signal.SIGINT, signal.default_int_handler); "
        "from personal_agent.tools.mcp_resources import ServerConfig, prepare_operation, apply_operation; "
        "config=ServerConfig('local',sys.executable,(sys.argv[1],sys.argv[2],'hang')); "
        "apply_operation(prepare_operation(config,Path(sys.argv[2]).parent,'list resources',{}))"
    )
    process = subprocess.Popen([sys.executable, "-c", driver, str(script), str(marker)],
                               cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if marker.with_suffix(".methods").exists():
                break
            time.sleep(0.02)
        assert marker.with_suffix(".methods").exists()
        process.send_signal(signal.SIGINT)
        process.wait(timeout=7)
        assert process.returncode == -signal.SIGINT
        assert marker.with_suffix(".exit").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


@pytest.mark.parametrize("mode,answer,launched", [("plan", "y", True), ("build", "n", False),
                                                ("plan", "", False), ("auto", "", True)])
def test_repl_confirmation_provider_result_and_log(
    route_env, install_fake_urlopen, tmp_path, mode, answer, launched,
):
    marker = tmp_path / "launch"
    script = Path(__file__).parent / "fixtures" / "mcp_server.py"
    config = mcp_resources.ServerConfig("local", sys.executable, (str(script), str(marker)))
    registry.enable_mcp_resources(config, tmp_path)
    provider = install_fake_urlopen([
        {"tool_calls": [{"id": "m1", "name": "mcp_read_resource", "arguments": {"uri": "catalog://items/apple"}}]},
        "done",
    ])
    output = StringIO()
    command = f"/mode {mode}\n" if mode != "build" else ""
    run_repl(runtime_config.load(), input_stream=StringIO(command + "research\n" + (answer + "\n" if answer else "")),
             output_stream=output)
    assert marker.exists() is launched
    assert ("local" in output.getvalue() and "catalog://items/apple" in output.getvalue())
    assert ("Run this MCP operation? [y/N]" in output.getvalue()) is (mode != "auto")
    assert "Apply this change?" not in output.getvalue()
    followup = json.loads(provider[1]["request"].data)
    assert any("context for apple" in message["content"] for message in followup["messages"]
               if message.get("role") == "tool") is launched
    entries = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    execution = next(entry for entry in entries if entry["type"] == "tool_execution")
    assert execution["ok"] is launched


def test_server_instructions_never_reach_provider_and_calls_still_prompt(route_env, install_fake_urlopen, tmp_path):
    marker = tmp_path / "launch"
    script = Path(__file__).parent / "fixtures" / "mcp_server.py"
    registry.enable_mcp_resources(
        mcp_resources.ServerConfig("local", sys.executable, (str(script), str(marker), "instructions")), tmp_path)
    provider = install_fake_urlopen([
        {"tool_calls": [{"id": "m1", "name": "mcp_list_resources", "arguments": {}}]},
        {"tool_calls": [{"id": "m2", "name": "mcp_read_resource", "arguments": {"uri": "catalog://items/apple"}}]},
        "done",
    ])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("/mode plan\nresearch\ny\ny\n"), output_stream=output)
    assert output.getvalue().count("Run this MCP operation? [y/N]") == 2
    assert marker.with_suffix(".methods").read_text().count("resources/read") == 1
    for call in provider:
        assert "INJECTED" not in call["request"].data.decode()
    followup = json.loads(provider[2]["request"].data)
    assert any("context for apple" in m["content"] for m in followup["messages"] if m.get("role") == "tool")


def test_resume_replays_call_log_content(route_env, install_fake_urlopen, tmp_path):
    marker = tmp_path / "launch"
    script = Path(__file__).parent / "fixtures" / "mcp_server.py"
    registry.enable_mcp_resources(
        mcp_resources.ServerConfig("local", sys.executable, (str(script), str(marker))), tmp_path)
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "m1", "name": "mcp_read_resource", "arguments": {"uri": "catalog://items/apple"}}]},
        "done", "resumed",
    ])
    run_repl(runtime_config.load(), input_stream=StringIO("/mode auto\nresearch\nexit\n"), output_stream=StringIO())
    marker.unlink()
    session_id = call_log.current_session_id()
    turns, summary, todos, _ = call_log.load_conversation(session_id)
    run_repl(runtime_config.load(), input_stream=StringIO("next\nexit\n"), output_stream=StringIO(),
             resumed=(session_id, turns, summary, todos, call_log.load_conversation(session_id)[3]))
    messages = json.loads(calls[2]["request"].data)["messages"]
    assert any(m.get("role") == "tool" and "context for apple" in m["content"] for m in messages)
    assert not marker.exists()
