import json
import os
import time
from io import StringIO
from pathlib import Path

import pytest

from personal_agent import call_log
from personal_agent.providers.contract import ToolCall
from personal_agent.routing import runtime_config
from personal_agent.terminal.repl import run_repl
from personal_agent.tools import jobs, registry as tools, shell as shell_tool, workspace


def _call(name, arguments, call_id="1"):
    return ToolCall(id=call_id, name=name, arguments=arguments)


def _start(command, confirm=lambda *_args: True, mode="build"):
    return tools.execute_batch([_call("shell", {"command": command, "background": True})], confirm=confirm,
                               mode=mode)[0]


def _status(job_id, mode="build"):
    return tools.execute_batch([_call("job_status", {"id": job_id})], mode=mode)[0]


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("condition not reached")


def _gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _pid(path):
    return int(_wait_for(lambda: path.exists() and path.read_text().strip()))


@pytest.fixture
def shell_on(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    return tmp_path


def test_background_start_returns_while_running_then_status_reports_exit_and_tail(shell_on):
    started = time.monotonic()
    result = _start("echo first; sleep 0.5; echo last; exit 3")

    assert time.monotonic() - started < 0.4
    assert result.is_error is False
    assert result.content == {"job_id": 1, "state": "running"}
    running = _status(1).content
    assert running["state"] == "running" and running["exit_code"] is None
    assert running["command"] == "echo first; sleep 0.5; echo last; exit 3"
    done = _wait_for(lambda: (content := _status(1).content)["state"] == "exited" and content)
    assert done == {"job_id": 1, "command": "echo first; sleep 0.5; echo last; exit 3", "state": "exited",
                    "exit_code": 3, "output": "first\nlast\n"}


def test_background_merges_stderr_runs_in_workspace_root_without_tavily_key(shell_on, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    _start("pwd; echo err 1>&2; echo ${TAVILY_API_KEY:-none}; cat")

    done = _wait_for(lambda: (content := _status(1).content)["state"] == "exited" and content)
    assert done["output"] == f"{shell_on.resolve()}\nerr\nnone\n"


def test_job_stop_kills_a_term_ignoring_group_and_stopping_again_is_unchanged(shell_on):
    _start("(trap '' TERM; sleep 30) & echo $! > child.pid; trap '' TERM; sleep 30")
    child = _pid(shell_on / "child.pid")

    stopped = tools.execute_batch([_call("job_stop", {"id": 1})])[0]

    assert stopped.is_error is False
    assert stopped.content["state"] == "stopped"
    assert stopped.content["exit_code"] is not None
    _wait_for(lambda: _gone(child))
    again = tools.execute_batch([_call("job_stop", {"id": 1})])[0]
    assert again.content == stopped.content


def test_fifth_start_is_refused_before_confirmation(shell_on):
    for _ in range(4):
        assert _start("sleep 30").is_error is False
    asked = []

    result = _start("touch fifth", confirm=lambda *args: asked.append(args) or True)

    assert result.is_error is True
    assert "at most 4" in result.content["error"] and "job_stop" in result.content["error"]
    assert asked == []
    assert not (shell_on / "fifth").exists()
    tools.execute_batch([_call("job_stop", {"id": 2})])
    assert _start("true").content == {"job_id": 5, "state": "running"}


def test_ring_keeps_latest_64_kib_and_status_is_capped_with_discard_marker(shell_on):
    shell_tool.configure_shell(None, "10", 10)
    _start("head -c 70000 /dev/zero | tr '\\0' a; printf 0123456789XYZ")

    done = _wait_for(lambda: (content := _status(1).content)["state"] == "exited" and content)
    assert done["output"] == jobs.DISCARD_MARKER + "3456789XYZ"
    shell_tool.configure_shell(None, "100000", 100000)
    full = _status(1).content["output"]
    assert full.startswith(jobs.DISCARD_MARKER)
    assert len(full) - len(jobs.DISCARD_MARKER) == jobs.RING_BYTES


def test_short_output_has_no_discard_marker(shell_on):
    _start("printf hi")

    done = _wait_for(lambda: (content := _status(1).content)["state"] == "exited" and content)
    assert done["output"] == "hi"


def test_only_sixteen_finished_jobs_are_retained_and_ids_are_not_reused(shell_on):
    for _ in range(17):
        assert _start("true").is_error is False
        _wait_for(lambda: all(row["state"] != "running" for row in jobs.listing()))

    assert [row["job_id"] for row in jobs.listing()] == list(range(2, 18))
    assert _status(1).content == {"error": "unknown Background Job id 1"}


def test_unknown_id_is_a_tool_error_for_status_and_stop(shell_on):
    for name in ("job_status", "job_stop"):
        result = tools.execute_batch([_call(name, {"id": 9})])[0]
        assert result.is_error is True
        assert result.content == {"error": "unknown Background Job id 9"}


def test_plan_refuses_background_shell_and_job_stop_but_allows_job_status(shell_on):
    asked = []
    refused = _start("touch planned", confirm=lambda *args: asked.append(args) or True, mode="plan")

    assert refused.is_error is True and "plan mode" in refused.content["error"]
    assert asked == [] and not (shell_on / "planned").exists()
    _start("sleep 30")
    assert _status(1, mode="plan").content["state"] == "running"
    stop = tools.execute_batch([_call("job_stop", {"id": 1})], mode="plan")[0]
    assert stop.is_error is True and "plan mode" in stop.content["error"]
    assert _status(1).content["state"] == "running"


def test_background_preview_is_marked_and_dangerous_command_needs_strong_confirmation(shell_on):
    seen = []

    def reject(*args):
        seen.append(args)
        return False

    result = _start("sudo touch danger", confirm=reject)

    assert result.is_error is True and result.content["error"] == "change rejected by the user"
    assert seen == [("shell", str(shell_on.resolve()), "[background job] sudo touch danger", ("sudo",), ())]
    assert jobs.listing() == []
    auto = _start("sudo touch danger", confirm=reject, mode="auto")
    assert auto.is_error is True
    assert len(seen) == 2 and jobs.listing() == []


def test_shell_disabled_offers_no_job_tools():
    names = {definition.name for definition in tools.TOOL_DEFS}
    assert not names & {"shell", "job_status", "job_stop"}
    result = tools.execute_batch([_call("job_status", {"id": 1})])[0]
    assert result.content == {"error": "unknown tool 'job_status'"}

    tools.enable_shell_tool()
    assert {"shell", "job_status", "job_stop"} <= {definition.name for definition in tools.TOOL_DEFS}
    assert [definition.name for definition in tools.definitions_for_mode("plan")
            if definition.name.startswith(("job_", "shell"))] == ["job_status"]


# --- REPL --------------------------------------------------------------------


def _entries():
    return [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]


def _repl(lines, install_fake_urlopen, answers=()):
    install_fake_urlopen(list(answers) or ["unused"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(lines), output_stream=output)
    return output.getvalue()


def _background_answers(command):
    return [{"tool_calls": [{"id": "c1", "name": "shell", "arguments": {"command": command, "background": True}}]},
            "started"]


def test_jobs_command_lists_stops_and_is_audited_with_arguments(route_env, install_fake_urlopen, shell_on):
    output = _repl("start it\ny\n/jobs\n/jobs stop 1\n/jobs stop 1\n/jobs stop 7\n/jobs\n/mode plan\n/jobs\nexit\n",
                   install_fake_urlopen, _background_answers("sleep 30 # \x1b[31m"))

    assert "1 running exit - sleep 30 #" in output
    assert "\x1b[31m" not in output
    assert output.count("Stopped job 1.") == 1
    assert "Job 1 already stopped" in output
    assert "Error: unknown Background Job id 7" in output
    assert output.count("1 stopped exit ") == 2
    events = [entry for entry in _entries() if entry["type"] == "audit_event" and entry.get("name") == "/jobs"]
    assert [(event["arguments"], event["outcome"]) for event in events] == [
        ([], "ok"), (["stop", "1"], "ok"), (["stop", "1"], "ok"), (["stop", "7"], "error"), ([], "ok"), ([], "ok")]
    executions = [entry for entry in _entries() if entry["type"] == "tool_execution"]
    assert executions[0]["result"] == {"job_id": 1, "state": "running"}


def test_jobs_stop_on_an_exited_job_reports_its_unchanged_final_state(route_env, install_fake_urlopen, shell_on):
    def lines():
        yield from ["start it\n", "y\n"]
        _wait_for(lambda: jobs.listing()[0]["state"] == "exited")
        yield from ["/jobs stop 1\n", "/jobs\n", "exit\n"]

    install_fake_urlopen(_background_answers("exit 4"))
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=lines(), output_stream=output)
    text = output.getvalue()

    assert "Stopped job" not in text
    assert "Job 1 already exited with exit code 4." in text
    assert "1 exited exit 4 exit 4" in text


def test_jobs_command_with_no_jobs_and_bad_usage(route_env, install_fake_urlopen):
    output = _repl("/jobs\n/jobs stop\n/jobs stop x\nexit\n", install_fake_urlopen)

    assert "No Background Jobs.\n" in output
    assert output.count("Error: usage: /jobs [stop <id>]") == 2


def test_clear_keeps_jobs_and_exit_stops_them_with_one_audit_event(route_env, install_fake_urlopen, shell_on):
    _repl("start it\ny\n/clear\n/jobs\nexit\n", install_fake_urlopen,
          _background_answers("sleep 30 & echo $! > child.pid; wait"))

    child = _pid(shell_on / "child.pid")
    _wait_for(lambda: _gone(child))
    entries = _entries()
    stopped = [entry for entry in entries if entry.get("action") == "background_jobs_stopped"]
    assert len(stopped) == 1
    assert stopped[0]["trigger"] == "exit_command" and stopped[0]["job_ids"] == [1]
    types = [entry["type"] for entry in entries]
    assert types.index("audit_coverage_end") > entries.index(stopped[0])
    assert types[-1] == "session_end"


def test_jobs_list_survives_clear(route_env, install_fake_urlopen, shell_on):
    output = _repl("start it\ny\n/clear\n/jobs\nexit\n", install_fake_urlopen, _background_answers("sleep 30"))

    assert "1 running exit - sleep 30" in output


@pytest.mark.parametrize("ending, trigger", [("/exit\n", "exit_command"), ("quit\n", "exit_command"), ("", "eof")])
def test_exit_paths_leave_no_live_group(route_env, install_fake_urlopen, shell_on, ending, trigger):
    _repl("start it\ny\n" + ending, install_fake_urlopen,
          _background_answers("(trap '' TERM; sleep 30) & echo $! > child.pid; wait"))

    child = _pid(shell_on / "child.pid")
    _wait_for(lambda: _gone(child))
    assert [entry["trigger"] for entry in _entries() if entry.get("action") == "background_jobs_stopped"] == [trigger]


class _ThenRaise:
    def __init__(self, lines, error):
        self.lines = iter(lines)
        self.error = error

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self.lines)
        except StopIteration:
            raise self.error from None


@pytest.mark.parametrize("error, trigger", [(ValueError("boom"), "error"), (KeyboardInterrupt(), "interrupt")])
def test_exception_and_ctrl_c_at_prompt_stop_jobs(route_env, install_fake_urlopen, shell_on, error, trigger):
    install_fake_urlopen(_background_answers("sleep 30 & echo $! > child.pid; wait"))
    stream = _ThenRaise(["start it\n", "y\n"], error)

    if isinstance(error, ValueError):
        with pytest.raises(ValueError):
            run_repl(runtime_config.load(), input_stream=stream, output_stream=StringIO())
    else:
        run_repl(runtime_config.load(), input_stream=stream, output_stream=StringIO())

    child = _pid(shell_on / "child.pid")
    _wait_for(lambda: _gone(child))
    assert jobs.listing()[0]["state"] == "stopped"
    entries = _entries()
    assert [entry["trigger"] for entry in entries if entry.get("action") == "background_jobs_stopped"] == [trigger]
    assert entries[-1]["type"] == "session_end"


def test_fatal_persistence_error_still_stops_jobs(route_env, install_fake_urlopen, shell_on):
    install_fake_urlopen(_background_answers("sleep 30 & echo $! > child.pid; wait"))
    stream = _ThenRaise(["start it\n", "y\n"], call_log.PersistenceError("disk gone"))

    with pytest.raises(call_log.PersistenceError):
        run_repl(runtime_config.load(), input_stream=stream, output_stream=StringIO())

    child = _pid(shell_on / "child.pid")
    _wait_for(lambda: _gone(child))
    assert not [entry for entry in _entries() if entry.get("action") == "background_jobs_stopped"]


def test_no_audit_event_when_no_job_was_live(route_env, install_fake_urlopen, shell_on):
    _repl("start it\ny\n/jobs stop 1\nexit\n", install_fake_urlopen, _background_answers("sleep 30"))

    assert not [entry for entry in _entries() if entry.get("action") == "background_jobs_stopped"]
