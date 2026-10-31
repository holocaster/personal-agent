import json
import re
import threading
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.output.base import Size
from prompt_toolkit.output.vt100 import Vt100_Output

from personal_agent import call_log
from personal_agent.routing import runtime_config
from personal_agent.terminal.input_box import InputBox
from personal_agent.terminal.repl import COMMANDS, run_repl


@pytest.fixture
def pipe():
    with create_pipe_input() as pipe_input:
        yield pipe_input


def _box(pipe_input):
    return InputBox(COMMANDS, input=pipe_input, output=DummyOutput())


def test_enter_submits_the_typed_text(pipe):
    pipe.send_text("hello there\r")

    assert _box(pipe).read() == "hello there"


def test_read_after_ask_restores_the_task_prompt(pipe):
    box = _box(pipe)
    pipe.send_text("y\r")
    assert box.ask("Run this command? [y/N] ") == "y"

    pipe.send_text("next task\r")
    assert box.read() == "next task"

    assert box._session.message().endswith("> ")
    assert box._session.multiline is True


def test_secret_prompt_hides_input_and_does_not_add_it_to_repl_history(pipe):
    captured_output = StringIO()
    output = Vt100_Output(captured_output, lambda: Size(rows=24, columns=80), term="xterm")
    box = InputBox(COMMANDS, input=pipe, output=output)
    pipe.send_text("previous task\r")
    assert box.read() == "previous task"

    pipe.send_text("provider-secret-value\r")
    assert box.ask_secret("Provider API key: ") == "provider-secret-value"

    pipe.send_text("\x1b[A\r")
    assert box.read() == "previous task"
    assert "provider-secret-value" not in captured_output.getvalue()


def test_escape_then_enter_inserts_a_newline(pipe):
    pipe.send_text("first line\x1b\rsecond line\r")

    assert _box(pipe).read() == "first line\nsecond line"


@pytest.mark.parametrize("shift_enter", ("\x1b[27;2;13~", "\x1b[13;2u"))
def test_shift_enter_inserts_a_newline(pipe, shift_enter):
    pipe.send_text(f"first line{shift_enter}second line\r")

    assert _box(pipe).read() == "first line\nsecond line"


def test_tab_cycles_matching_repl_commands(pipe):
    pipe.send_text("/\t")
    threading.Timer(0.2, pipe.send_text, ["\t\r"]).start()

    assert _box(pipe).read() == "/clear"


def test_tab_completes_a_repl_command(pipe):
    pipe.send_text("/he\t")
    threading.Timer(0.2, pipe.send_text, ["\r"]).start()

    assert _box(pipe).read() == "/help"


def test_tab_completes_the_model_command(pipe):
    pipe.send_text("/mode\t")
    threading.Timer(0.2, pipe.send_text, ["\r"]).start()

    assert _box(pipe).read() == "/model"


def test_mode_argument_completion_offers_auto(pipe):
    box = _box(pipe)
    pipe.send_text("/mode a\t\r")

    assert box.read() == "/mode auto"


def test_tab_completes_the_config_command(pipe):
    pipe.send_text("/conf\t\r")

    assert _box(pipe).read() == "/config"


def test_tab_completes_skills_command(pipe):
    pipe.send_text("/skills\t\r")

    assert _box(pipe).read() == "/skills"


def test_skill_off_is_suggested_and_completable_in_the_input_box(pipe):
    box = _box(pipe)
    pipe.send_text("/skill o")
    captured = []

    def _capture_and_complete():
        captured.append(box._toolbar())
        pipe.send_text("\t\r")

    threading.Timer(0.2, _capture_and_complete).start()
    assert box.read() == "/skill off"
    assert "/skill off [name]" in captured[0]
    pipe.send_text("/skill off alpha")
    threading.Timer(0.2, _capture_and_complete).start()
    assert box.read() == "/skill off alpha"
    assert "/skill off [name]" in captured[1]


def test_tab_completes_the_undo_command(pipe):
    pipe.send_text("/un\t")
    threading.Timer(0.2, pipe.send_text, ["\r"]).start()

    assert _box(pipe).read() == "/undo"


def test_tab_completes_the_retry_command(pipe):
    pipe.send_text("/ret\t")
    threading.Timer(0.2, pipe.send_text, ["\r"]).start()

    assert _box(pipe).read() == "/retry"


def test_typing_a_slash_lists_matching_commands_in_the_toolbar(pipe):
    box = _box(pipe)
    pipe.send_text("/mo")
    captured = []

    def _capture_then_finish():
        captured.append(box._toolbar())
        pipe.send_text("\r")

    threading.Timer(0.2, _capture_then_finish).start()
    box.read()

    assert "/model" in captured[0]
    assert "/mode" in captured[0]
    assert "/models" in captured[0]
    assert "/help" not in captured[0]


def test_tab_offers_no_completion_when_input_does_not_start_with_a_slash(pipe):
    pipe.send_text("\t")
    threading.Timer(0.2, pipe.send_text, ["task\r"]).start()

    assert _box(pipe).read() == "task"


def test_arrow_up_recalls_the_previous_input(pipe):
    box = _box(pipe)
    pipe.send_text("first task\r")
    assert box.read() == "first task"

    pipe.send_text("\x1b[A\r")
    assert box.read() == "first task"


def test_ctrl_c_raises_keyboard_interrupt(pipe):
    pipe.send_text("\x03")

    with pytest.raises(KeyboardInterrupt):
        _box(pipe).read()


def test_ctrl_d_raises_eof_error(pipe):
    pipe.send_text("\x04")

    with pytest.raises(EOFError):
        _box(pipe).read()


def _session_lines():
    return [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]


def test_run_repl_with_input_box_routes_a_task_and_runs_a_command_then_ends_on_ctrl_d(
    pipe, route_env, install_fake_urlopen
):
    calls = install_fake_urlopen(["the answer"])
    output_stream = StringIO()
    pipe.send_text("/model\r")
    pipe.send_text("summarize this line\r")
    pipe.send_text("\x04")

    run_repl(runtime_config.load(), input_stream=None, output_stream=output_stream, input_box=_box(pipe))

    output = output_stream.getvalue()
    assert len(calls) == 1
    assert "Change with /model <provider> <model-id>" in output
    assert "llm> the answer\n" in output
    assert "user> " not in output
    assert _session_lines()[-1]["reason"] == "eof"


def test_run_repl_with_input_box_updates_the_footer_after_a_routed_answer(pipe, route_env, install_fake_urlopen):
    install_fake_urlopen([{"content": "the answer", "usage": {"cost": 0.0009}}])
    box = _box(pipe)
    pipe.send_text("summarize this line\r")
    pipe.send_text("\x04")

    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=box)

    assert re.fullmatch(r" mode: build · openrouter vendor/test-model · API key · ctx ~\d+/\d+ public · "
                        r"\$0\.0009 \(1 reported\) · /help", box.footer())


def test_shift_tab_switches_agent_mode_without_submitting_or_changing_the_draft(
    pipe, route_env, install_fake_urlopen
):
    calls = install_fake_urlopen(["first answer", "second answer"])
    box = _box(pipe)
    output_stream = StringIO()
    inputs = iter(["summarize first\x1b[Z line\r", "/mode\r", "\x1b[Zsummarize second\r", "\x04"])
    read = box.read

    def next_read():
        pipe.send_text(next(inputs))
        return read()

    box.read = next_read

    run_repl(runtime_config.load(), output_stream=output_stream, input_box=box)

    requests = [json.loads(call["request"].data) for call in calls]
    assert len(requests) == 2
    assert requests[0]["messages"][-1]["content"] == "summarize first line"
    assert "auto mode" in requests[0]["messages"][0]["content"].lower()
    assert "auto\n" in output_stream.getvalue()
    assert "write" not in {tool["function"]["name"] for tool in requests[1]["tools"]}
    assert box.footer().startswith(" mode: plan ·")


def test_shift_tab_cycles_through_auto_and_plan_while_preserving_draft(pipe, route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["first", "second", "third"])
    box = _box(pipe)
    inputs = iter(["/mode plan\r", "first\x1b[Z task\r", "second\x1b[Z task\r", "third\x1b[Z task\r", "\x04"])
    read = box.read

    def next_read():
        pipe.send_text(next(inputs))
        return read()

    box.read = next_read
    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=box)

    requests = [json.loads(call["request"].data) for call in calls]
    assert [r["messages"][-1]["content"] for r in requests] == ["first task", "second task", "third task"]
    assert ["write" in {t["function"]["name"] for t in r["tools"]} for r in requests] == [True, True, False]
    assert "auto mode" in requests[1]["messages"][0]["content"].lower()
    assert box.footer().startswith(" mode: plan ·")


def test_interactive_auto_confirmation_switch_to_plan_blocks_dangerous_shell(
    pipe, route_env, install_fake_urlopen, tmp_path,
):
    from personal_agent.tools import registry as tools, workspace

    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    install_fake_urlopen([{"tool_calls": [
        {"id": "w", "name": "write", "arguments": {"path": "note.txt", "content": "hello"}},
        {"id": "s", "name": "shell", "arguments": {"command": "eval touch marker.txt"}},
    ]}, "done"])
    box = _box(pipe)
    pipe.send_text("/mode auto\r")
    pipe.send_text("do work\r")
    ask = box.ask
    def answer(question):
        pipe.send_text("\x1b[ZYES\r\x04")
        return ask(question)
    box.ask = answer
    output = StringIO()
    run_repl(runtime_config.load(), output_stream=output, input_box=box)

    assert (tmp_path / "note.txt").read_text() == "hello"
    assert not (tmp_path / "marker.txt").exists()
    assert "Dangerous command: eval" in output.getvalue()
    assert "Apply this change?" not in output.getvalue()
    assert box.footer().startswith(" mode: plan ·")


def test_shift_tab_updates_the_footer_while_editing(pipe):
    box = _box(pipe)
    mode = ["build"]
    observed = []
    box.footer = lambda: f"mode: {mode[0]}"

    def toggle_mode():
        mode[0] = "plan" if mode[0] == "build" else "build"
        observed.append((box._toolbar(), box._session.default_buffer.text))

    box.on_mode_toggle = toggle_mode
    pipe.send_text("draft\x1b[Z continued\r")

    assert box.read() == "draft continued"
    assert len(observed) == 1
    assert observed[0][0].endswith("\nmode: plan")
    assert observed[0][1] == "draft"


def test_shift_tab_switches_mode_during_tool_confirmation_without_submitting(pipe):
    box = _box(pipe)
    toggles = []
    box.on_mode_toggle = lambda: toggles.append(True)
    pipe.send_text("\x1b[Zy\r")

    assert box.ask("Run this command? [y/N] ") == "y"
    assert toggles == [True]


def test_run_repl_with_input_box_footer_shows_the_configured_pair_before_any_task(pipe, route_env, install_fake_urlopen):
    install_fake_urlopen([])
    box = _box(pipe)
    pipe.send_text("/model\r")
    pipe.send_text("\x04")

    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=box)

    assert box.footer() == " mode: build · openrouter vendor/test-model · API key · ctx unknown · $0.0000 · /help"


def test_run_repl_with_input_box_footer_keeps_the_configured_pair_and_spend_after_a_failure(
    pipe, route_env, install_fake_urlopen
):
    error = HTTPError("https://openrouter.ai", 400, "bad request", None, None)
    install_fake_urlopen([{"content": "the answer", "usage": {"cost": 0.0009}}, error])
    box = _box(pipe)
    pipe.send_text("summarize this line\r")
    pipe.send_text("please refactor this module\r")
    pipe.send_text("\x04")

    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=box)

    assert re.fullmatch(r" mode: build · openrouter vendor/test-model · API key · ctx ~\d+/\d+ public · "
                        r"\$0\.0009 \(1 reported, 1 unknown\) · /help", box.footer())


def test_run_repl_with_input_box_sends_a_multi_line_submission_as_one_task(pipe, route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["the answer"])
    pipe.send_text("summarize\x1b\rthis line\r")
    pipe.send_text("\x04")

    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=_box(pipe))

    assert len(calls) == 1
    body = json.loads(calls[0]["request"].data)
    assert body["messages"][-1]["content"] == "summarize\nthis line"


def test_run_repl_with_input_box_ends_on_ctrl_c_with_interrupt_reason(pipe, route_env, install_fake_urlopen):
    install_fake_urlopen([])
    pipe.send_text("\x03")

    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=_box(pipe))

    assert _session_lines()[-1]["reason"] == "interrupt"


def test_run_repl_with_input_box_prints_interrupted_on_ctrl_c_during_a_request_and_continues(
    pipe, route_env, install_fake_urlopen
):
    calls = install_fake_urlopen([KeyboardInterrupt(), "second answer"])
    output_stream = StringIO()
    pipe.send_text("summarize this line\r")
    pipe.send_text("summarize this other line\r")
    pipe.send_text("exit\r")

    run_repl(runtime_config.load(), output_stream=output_stream, input_box=_box(pipe))

    output = output_stream.getvalue()
    assert len(calls) == 2
    assert "Interrupted.\n" in output
    assert "llm> second answer\n" in output
    assert _session_lines()[-1]["reason"] == "exit_command"


def _write_tool_call(path, content):
    return {"tool_calls": [{"id": "call_1", "name": "write", "arguments": {"path": path, "content": content}}]}


def test_run_repl_with_input_box_confirms_a_write_via_the_boxs_own_prompt(
    pipe, route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([_write_tool_call("note.txt", "hello"), "wrote it"])
    box = _box(pipe)
    pipe.send_text("create a note\r")
    pipe.send_text("y\r")
    pipe.send_text("\x04")
    output_stream = StringIO()

    run_repl(runtime_config.load(), output_stream=output_stream, input_box=box)

    assert (tmp_path / "note.txt").read_text() == "hello"
    assert "llm> wrote it\n" in output_stream.getvalue()


@pytest.mark.parametrize("approval", ["y\r", "v\rqyes\r"])
def test_interactive_long_write_preview_is_bounded_without_changing_written_content(
    pipe, route_env, install_fake_urlopen, tmp_path, monkeypatch, approval
):
    from personal_agent.tools import workspace

    monkeypatch.setenv("NO_COLOR", "1")
    workspace.configure_workspace(tmp_path)
    content = "\n".join(f"line {number}" for number in range(200))
    install_fake_urlopen([_write_tool_call("note.txt", content), "done"])
    screen = StringIO()
    box = InputBox(COMMANDS, input=pipe, output=Vt100_Output(
        screen, lambda: Size(rows=24, columns=80), term="xterm"))
    pipe.send_text("create a note\r" + approval + "exit\r")
    output = StringIO()

    run_repl(runtime_config.load(), output_stream=output, input_box=box)

    assert "line 199" not in output.getvalue()
    assert "Hidden content: 188 lines" in output.getvalue()
    assert "200 lines" in output.getvalue()
    assert "Apply this change? [y/N/v=view] " in screen.getvalue()
    assert (tmp_path / "note.txt").read_text() == content


@pytest.mark.parametrize("answer", ["n\r", "\r", "\x04", "q\r", "nonsense\r"])
def test_viewing_large_write_repeatedly_never_approves_it(
    pipe, route_env, install_fake_urlopen, tmp_path, answer
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([_write_tool_call("note.txt", "line\n" * 100), "rejected"])
    pipe.send_text("create a note\rv\rqv\rq" + answer + "exit\r")
    output = StringIO()

    run_repl(runtime_config.load(), output_stream=output, input_box=_box(pipe))

    assert not (tmp_path / "note.txt").exists()
    confirmations = [item for item in _session_lines() if item.get("action") == "tool_confirmation"]
    assert [item["decision"] for item in confirmations] == ["rejected"]
    execution = next(item for item in _session_lines() if item["type"] == "tool_execution")
    assert execution["error"] == "change rejected by the user"


@pytest.mark.parametrize("key,expected", [("\x03", "Interrupted."), ("\x04", "change rejected")])
def test_full_view_cancellation_never_executes_write(
    pipe, route_env, install_fake_urlopen, tmp_path, key, expected
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    responses = [_write_tool_call("note.txt", "line\n" * 100)]
    if key == "\x04":
        responses.append("rejected")
    install_fake_urlopen(responses)
    box = _box(pipe)
    preview = box.view_preview

    def cancel_preview(text):
        pipe.send_text(key + "exit\r")
        return preview(text)

    box.view_preview = cancel_preview
    pipe.send_text("create a note\rv\r")
    output = StringIO()

    run_repl(runtime_config.load(), output_stream=output, input_box=box)

    assert not (tmp_path / "note.txt").exists()
    if key == "\x03":
        assert expected in output.getvalue()
    else:
        execution = next(item for item in _session_lines() if item["type"] == "tool_execution")
        assert expected in execution["error"]


def test_full_view_keeps_sanitized_content_read_only_and_navigation_returns_to_approval(pipe, monkeypatch):
    from prompt_toolkit.application import Application
    from personal_agent.terminal import input_box
    from personal_agent.terminal.tty import sanitize_control_chars

    screen = StringIO()
    box = InputBox(COMMANDS, input=pipe, output=Vt100_Output(
        screen, lambda: Size(rows=10, columns=80), term="xterm"))
    content = "\n".join(f"line {number}" for number in range(30)) + "\ncontrol\x1b[2K\r\tend"
    observed = []
    keys = iter(["\x1b[B", "\x1b[6~", "\x1b[5~", "\x1b[1;5F", "changedq"])

    def observe(app):
        observed.append((app.current_buffer.text, app.current_buffer.document.cursor_position_row))
        key = next(keys, None)
        if key is not None:
            pipe.send_text(key)

    def application(**kwargs):
        kwargs["after_render"] = observe
        return Application(**kwargs)

    monkeypatch.setattr(input_box, "Application", application)

    box.view_preview(content)

    assert all(text == sanitize_control_chars(content, multiline=True) for text, _ in observed)
    rows = [row for _, row in observed]
    assert rows[1] > rows[0]
    assert rows[2] > rows[1]
    assert rows[3] < rows[2]
    assert rows[4] == 30
    assert "changed" not in screen.getvalue()
    pipe.send_text("y\r")
    assert box.ask("Apply this change? [y/N] ") == "y"


def test_escape_closes_full_view_and_returns_without_approving(pipe):
    box = _box(pipe)
    pipe.send_text("\x1b")
    box.view_preview("line\n" * 100)
    pipe.send_text("n\r")
    assert box.ask("Apply this change? [y/N] ") == "n"


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
def test_hidden_preview_line_counts_use_lf_boundaries(pipe, separator):
    from personal_agent.terminal.repl import _make_confirm

    output = StringIO()
    pipe.send_text("n\r")
    confirm = _make_confirm(output, None, False, _box(pipe), iter(()))
    assert not confirm("write", "note.txt", ("content" + separator) * 1000)
    assert "Preview: 1 lines" in output.getvalue()
    assert "Hidden content: 1 lines (including a partial line)" in output.getvalue()


@pytest.mark.parametrize("tool,arguments", [
    ("edit", {"path": "note.txt", "old_string": "old", "new_string": "new", "replace_all": True}),
    ("apply_patch", {"patch": "*** Begin Patch\n*** Delete File: note.txt\n*** End Patch"}),
    ("shell", {"command": "touch marker.txt" + " " * 10000}),
])
def test_all_mutating_previews_share_view_and_rejection_without_execution(
    pipe, route_env, install_fake_urlopen, tmp_path, tool, arguments
):
    from personal_agent.tools import registry, workspace

    workspace.configure_workspace(tmp_path)
    registry.enable_shell_tool()
    (tmp_path / "note.txt").write_text("old\n" * 100)
    install_fake_urlopen([{"tool_calls": [{"id": "action", "name": tool, "arguments": arguments}]}, "rejected"])
    pipe.send_text("change things\rv\rqno\rexit\r")
    output = StringIO()

    run_repl(runtime_config.load(), output_stream=output, input_box=_box(pipe))

    assert "Hidden content" in output.getvalue()
    if tool == "shell":
        assert "Hidden content: 1 lines (including a partial line)" in output.getvalue()
    assert (tmp_path / "note.txt").read_text() == "old\n" * 100
    assert not (tmp_path / "marker.txt").exists()
    confirmation = next(item for item in _session_lines() if item.get("action") == "tool_confirmation")
    assert confirmation["decision"] == "rejected"


@pytest.mark.parametrize("approval,applied", [("y", False), ("yes", True)])
def test_viewing_dangerous_shell_keeps_warnings_and_requires_full_yes(
    pipe, route_env, install_fake_urlopen, tmp_path, approval, applied
):
    from personal_agent.tools import registry, workspace
    from personal_agent.terminal.repl import _make_confirm

    workspace.configure_workspace(tmp_path)
    registry.enable_shell_tool()
    install_fake_urlopen([{"tool_calls": [{"id": "action", "name": "shell", "arguments": {
        "command": "eval touch marker.txt" + " " * 10000}}]}, "done"])
    pipe.send_text("do work\rv\rq" + approval + "\rexit\r")
    output = StringIO()
    run_repl(runtime_config.load(), output_stream=output, input_box=_box(pipe))

    assert (tmp_path / "marker.txt").exists() is applied
    assert "Dangerous command: eval" in output.getvalue()
    warnings = StringIO()
    pipe.send_text("v\rqn\r")
    assert not _make_confirm(warnings, None, False, _box(pipe), iter(()))(
        "shell", ".", "echo " + "x" * 10000, ("eval",), ("https://example.com/\x1b[2K",))
    assert "Dangerous command: eval" in warnings.getvalue()
    assert "Warning: this turn fetched https://example.com/\\x1b[2K" in warnings.getvalue()


def test_run_repl_with_input_box_rejects_a_write_on_ctrl_d_at_the_confirmation_prompt(
    pipe, route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([_write_tool_call("note.txt", "hello"), "not written"])
    box = _box(pipe)
    pipe.send_text("create a note\r")
    pipe.send_text("\x04")
    pipe.send_text("\x04")
    output_stream = StringIO()

    run_repl(runtime_config.load(), output_stream=output_stream, input_box=box)

    assert not (tmp_path / "note.txt").exists()
    assert "error: change rejected by the user" in output_stream.getvalue()
    assert _session_lines()[-1]["reason"] == "eof"


def test_run_repl_with_input_box_ends_the_turn_interrupted_on_ctrl_c_at_the_confirmation_prompt(
    pipe, route_env, install_fake_urlopen, tmp_path
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([_write_tool_call("note.txt", "hello")])
    box = _box(pipe)
    pipe.send_text("create a note\r")
    pipe.send_text("\x03")
    pipe.send_text("exit\r")
    output_stream = StringIO()

    run_repl(runtime_config.load(), output_stream=output_stream, input_box=box)

    assert not (tmp_path / "note.txt").exists()
    assert "Interrupted.\n" in output_stream.getvalue()


def test_tab_completes_the_compress_command(pipe):
    pipe.send_text("/comp\t")
    threading.Timer(0.2, pipe.send_text, ["\r"]).start()

    assert _box(pipe).read() == "/compress"


def test_tab_completes_the_remember_command(pipe):
    pipe.send_text("/reme\t")
    threading.Timer(0.2, pipe.send_text, ["\r"]).start()

    assert _box(pipe).read() == "/remember"


def test_tab_completes_the_memory_command(pipe):
    pipe.send_text("/mem\t")
    threading.Timer(0.2, pipe.send_text, ["\r"]).start()

    assert _box(pipe).read() == "/memory"


def test_tab_completes_the_forget_command(pipe):
    pipe.send_text("/for\t")
    threading.Timer(0.2, pipe.send_text, ["\r"]).start()

    assert _box(pipe).read() == "/forget"


def test_busy_mode_switch_is_processed_before_work_finishes_and_keeps_queued_input(pipe):
    box = _box(pipe)
    toggled = threading.Event()
    box.on_mode_toggle = toggled.set
    sender = threading.Thread(target=lambda: pipe.send_text("draft\x1b[Z continued\r"))

    def blocked_work():
        sender.start()
        assert toggled.wait(2), "Shift+Tab was not processed during the operation"
        return "finished"

    assert box.run_busy(blocked_work) == "finished"
    sender.join()
    assert box.read() == "draft continued"
    assert not any(thread.name == "agent-mode-input" for thread in threading.enumerate())


def test_busy_work_renders_an_animated_loading_indicator(pipe, monkeypatch):
    from personal_agent.terminal.tty import SPINNER_FRAMES

    monkeypatch.delenv("NO_COLOR", raising=False)
    animated = threading.Event()
    frames = set()

    class Screen(StringIO):
        def write(self, text):
            result = super().write(text)
            frames.update(frame for frame in SPINNER_FRAMES if frame in text)
            if len(frames) > 1:
                animated.set()
            return result

    screen = Screen()
    box = InputBox(COMMANDS, input=pipe, output=Vt100_Output(
        screen, lambda: Size(rows=24, columns=80), term="xterm"))
    box.footer = lambda: "build mode"

    def work():
        assert animated.wait(2), "Loading indicator missing during blocked work"
        return "finished"

    assert box.run_busy(work) == "finished"
    assert "build mode" in screen.getvalue()


def test_busy_work_handles_cursor_position_responses_without_warning_or_losing_queued_input(pipe):
    import time
    from prompt_toolkit.input.typeahead import get_typeahead, store_typeahead
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.renderer import Renderer

    requested = threading.Event()
    screen = StringIO()

    class RespondingOutput(Vt100_Output):
        @property
        def responds_to_cpr(self):
            return True

        def ask_for_cpr(self):
            super().ask_for_cpr()
            pipe.send_text("\x1b[1;1R")
            requested.set()

    box = InputBox(COMMANDS, input=pipe, output=RespondingOutput(
        screen, lambda: Size(rows=24, columns=80), term="xterm"))

    def work():
        assert requested.wait(2), "Terminal did not request a cursor position"
        pipe.send_text("next task\r")
        time.sleep(Renderer.CPR_TIMEOUT + 0.3)
        return "finished"

    assert box.run_busy(work) == "finished"
    assert "doesn't support cursor position requests" not in screen.getvalue()
    queued = get_typeahead(pipe)
    assert all(key.key != Keys.CPRResponse for key in queued)
    store_typeahead(pipe, queued)
    assert box.read() == "next task"


@pytest.mark.parametrize("switch,answer,first_ok,second_ok", [
    ("\x1b[Z", "y", True, True),
    ("\x1b[Z", "n", False, True),
    ("\x1b[Z\x1b[Z", "y", False, False),
])
def test_pending_confirmation_switch_keeps_explicit_answer_and_updates_same_batch(
    pipe, route_env, install_fake_urlopen, tmp_path, switch, answer, first_ok, second_ok,
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    calls = install_fake_urlopen([{"tool_calls": [
        {"id": "1", "name": "write", "arguments": {"path": "one.txt", "content": "one"}},
        {"id": "2", "name": "write", "arguments": {"path": "two.txt", "content": "two"}},
    ]}, "done"])
    pipe.send_text("write files\r")
    box = _box(pipe)
    ask = box.ask
    def approve(question):
        pipe.send_text(switch + answer + "\r/exit\r")
        return ask(question)
    box.ask = approve
    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=box)
    assert (tmp_path / "one.txt").exists() is first_ok
    assert (tmp_path / "two.txt").exists() is second_ok
    requests = [json.loads(item["request"].data) for item in calls]
    assert ("write" in {tool["function"]["name"] for tool in requests[-1]["tools"]}) is second_ok


@pytest.mark.parametrize("answer,approved", [("y", False), ("yes", True)])
def test_switch_to_auto_during_dangerous_confirmation_still_needs_yes(
    pipe, route_env, install_fake_urlopen, tmp_path, answer, approved,
):
    from personal_agent.tools import registry as tools, workspace

    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    install_fake_urlopen([{"tool_calls": [
        {"id": "1", "name": "shell", "arguments": {"command": "eval touch marker.txt"}},
    ]}, "done"])
    pipe.send_text("do work\r")
    box = _box(pipe)
    ask = box.ask
    def approve(question):
        pipe.send_text("\x1b[Z" + answer + "\r/exit\r")
        return ask(question)
    box.ask = approve
    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=box)
    assert (tmp_path / "marker.txt").exists() is approved
    assert box.footer().startswith(" mode: auto ·")


def test_live_question_switch_preserves_answer_and_changes_later_tool_policy(
    pipe, route_env, install_fake_urlopen, tmp_path,
):
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([{"tool_calls": [
        {"id": "q", "name": "question", "arguments": {"questions": [{"text": "Which value?"}]}},
        {"id": "w", "name": "write", "arguments": {"path": "note.txt", "content": "done"}},
    ]}, "done"])
    pipe.send_text("do work\r")
    box = _box(pipe)
    ask = box.ask
    def answer(question):
        pipe.send_text("an\x1b[Zswer\r/exit\r")
        return ask(question)
    box.ask = answer
    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=box)
    result = next(item for item in _session_lines() if item.get("name") == "question" and item["type"] == "tool_execution")
    assert result["result"]["answers"] == [{"question": "Which value?", "answer": "answer"}]
    assert (tmp_path / "note.txt").read_text() == "done"


def test_busy_provider_switch_changes_requested_tool_and_next_exchange(
    pipe, route_env, install_fake_urlopen, tmp_path, monkeypatch,
):
    from personal_agent.providers import http
    from personal_agent.tools import workspace

    workspace.configure_workspace(tmp_path)
    calls = install_fake_urlopen([_write_tool_call("note.txt", "done"), "done"])
    request = http.urlopen
    box = _box(pipe)
    toggled = threading.Event()
    started = threading.Event()

    def blocked(request_arg, timeout=None):
        if not started.is_set():
            started.set()
            assert toggled.wait(2), "Shift+Tab did not run while provider was blocked"
        return request(request_arg, timeout=timeout)

    monkeypatch.setattr(http, "urlopen", blocked)
    pipe.send_text("do work\r")
    toggle = []

    def send():
        assert started.wait(10)
        original = box.on_mode_toggle
        box.on_mode_toggle = lambda: (original(), toggle.append(True), toggled.set())
        pipe.send_text("\x1b[Z/exit\r")

    sender = threading.Thread(target=send)
    sender.start()
    run_repl(runtime_config.load(), output_stream=StringIO(), input_box=box)
    sender.join()
    assert toggle == [True]
    assert (tmp_path / "note.txt").read_text() == "done"
    assert "Auto mode" in json.loads(calls[1]["request"].data)["messages"][0]["content"]


def test_busy_shell_switch_and_ctrl_c_clean_up_child_and_continue(
    pipe, route_env, install_fake_urlopen, tmp_path,
):
    import time
    from personal_agent.tools import registry as tools, shell, workspace

    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    shell.configure_shell("5", "4096", 4096)
    install_fake_urlopen([{"tool_calls": [
        {"id": "s", "name": "shell", "arguments": {"command": 'sleep 30 & printf "%s" "$!" > child.pid; wait'}},
        {"id": "w", "name": "write", "arguments": {"path": "never.txt", "content": "no"}},
    ]}])
    box = _box(pipe)
    toggled = threading.Event()
    failures = []
    pipe.send_text("do work\ry\r")

    def send():
        try:
            deadline = time.monotonic() + 10
            while not (tmp_path / "child.pid").exists():
                assert time.monotonic() < deadline, "shell did not start"
                time.sleep(0.01)
            original = box.on_mode_toggle
            box.on_mode_toggle = lambda: (original(), toggled.set())
            pipe.send_text("\x1b[Z")
            assert toggled.wait(2), "Shift+Tab did not run during shell wait"
            pipe.send_text("\x03/exit\r")
        except BaseException as exc:
            failures.append(exc)
            pipe.send_text("\x03/exit\r")

    sender = threading.Thread(target=send)
    sender.start()
    output = StringIO()
    run_repl(runtime_config.load(), output_stream=output, input_box=box)
    sender.join()
    assert not failures
    child = (tmp_path / "child.pid").read_text()
    state = Path(f"/proc/{child}/stat")
    assert not state.exists() or state.read_text().split()[2] == "Z"
    assert not (tmp_path / "never.txt").exists()
    assert "Interrupted." in output.getvalue()
    assert _session_lines()[-1]["reason"] == "exit_command"
    assert not any(thread.name == "agent-mode-input" for thread in threading.enumerate())


def test_busy_mode_callback_failure_halts_work_and_cleans_up_reader(pipe):
    import time

    box = _box(pipe)

    def fail():
        raise RuntimeError("mode audit failed")

    box.on_mode_toggle = fail

    def work():
        pipe.send_text("\x1b[Z")
        time.sleep(0.1)

    with pytest.raises(RuntimeError, match="mode audit failed"):
        box.run_busy(work)
    assert not any(thread.name == "agent-mode-input" for thread in threading.enumerate())


def test_queued_shift_tab_at_task_boundary_runs_before_busy_operation(pipe):
    box = _box(pipe)
    toggled = threading.Event()
    box.on_mode_toggle = toggled.set
    pipe.send_text("task\r\x1b[Znext task\r")
    assert box.read() == "task"
    assert box.run_busy(toggled.is_set) is True
    assert box.read() == "next task"


def test_busy_start_processes_shortcuts_after_queued_draft_without_reordering_input(pipe):
    box = _box(pipe)
    toggles = []
    box.on_mode_toggle = lambda: toggles.append(True)
    pipe.send_text("task\rdraft\x1b[Z continued\x1b[Z end\rnext task\r")
    assert box.read() == "task"

    assert box.run_busy(lambda: len(toggles)) == 2
    assert box.read() == "draft continued end"
    assert box.read() == "next task"
    assert toggles == [True, True]
    assert not any(thread.name == "agent-mode-input" for thread in threading.enumerate())


def test_streaming_busy_output_keeps_keys_and_preserves_partial_line(pipe):
    captured = StringIO()
    output = Vt100_Output(captured, lambda: Size(rows=24, columns=80), term="xterm")
    box = InputBox(COMMANDS, input=pipe, output=output)
    toggled = threading.Event()
    box.on_mode_toggle = toggled.set

    def work():
        box.start_stream()
        captured.write("llm> first")
        captured.flush()
        pipe.send_text("\x1b[Znext task\r")
        assert toggled.wait(2)
        before = captured.getvalue()
        captured.write(" second\n")
        captured.flush()
        box.end_stream()
        assert "llm> first" in before
        assert "\x1b[" not in before[before.index("llm> first") + len("llm> first"):]
        return "done"

    assert box.run_busy(work) == "done"
    assert "llm> first second\n" in captured.getvalue()
    assert box.read() == "next task"
    assert not any(thread.name == "agent-mode-input" for thread in threading.enumerate())


def test_streaming_busy_cancel_releases_output_before_next_prompt(pipe):
    box = _box(pipe)
    output = StringIO()

    def work():
        box.start_stream()
        try:
            output.write("llm> partial")
            output.flush()
            pipe.send_text("\x03")
            threading.Event().wait(2)
            pytest.fail("busy Ctrl+C was not delivered")
        finally:
            output.write("\n")
            box.end_stream()

    with pytest.raises(KeyboardInterrupt):
        box.run_busy(work)
    assert box._stream_future is None
    assert not any(thread.name == "agent-mode-input" for thread in threading.enumerate())
    pipe.send_text("yes\r")
    assert box.ask("Approve? ") == "yes"
    assert output.getvalue() == "llm> partial\n"


def test_account_picker_requires_explicit_enter_and_preserves_order(pipe):
    box = _box(pipe)
    pipe.send_text("\x1b[B\r")
    assert box.choose("Account models", ["First", "Second"]) == 1
    pipe.send_text("\x1b")
    assert box.choose("Account models", ["First", "Second"]) is None


@pytest.mark.parametrize("key", ["\x03", "\x04", "\x1b"])
def test_oauth_wait_can_be_cancelled_without_stopping_repl(pipe, key):
    box = _box(pipe)
    cancel = threading.Event()
    threading.Timer(0.1, pipe.send_text, [key]).start()
    assert box.run_busy(lambda: cancel.wait(2), cancel=cancel)
    pipe.send_text("/model\r")
    assert box.read() == "/model"


def test_oauth_wait_does_not_reuse_queued_enter_to_select_a_model(pipe):
    box = _box(pipe)
    cancel = threading.Event()
    pipe.send_text("\r")
    box.run_busy(lambda: cancel.wait(0.1), cancel=cancel)
    threading.Timer(0.1, pipe.send_text, ["\x1b[B\r"]).start()
    assert box.choose("Choose model", ["First", "Second"]) == 1
