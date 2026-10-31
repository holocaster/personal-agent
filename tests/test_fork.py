import json
import os
import re
import shutil
import time
from io import StringIO
from pathlib import Path

import pytest

from personal_agent import call_log, session_logs
from personal_agent.routing import runtime_config
from personal_agent.terminal.repl import COMMANDS, HELP_TEXT, run_repl
from personal_agent.tools import jobs, registry as tools, todo as todo_module, workspace

TODOS = [{"content": "step one", "status": "in_progress"}]


def _lines(sid):
    return [json.loads(line) for line in Path(call_log.session_log_path(sid)).read_text().splitlines()]


def _session_files():
    directory = Path(call_log.session_log_path("20000101T000000Z-aaaaaa")).parent
    return sorted(path for path in directory.glob("pa_log-*.jsonl") if not path.name.endswith(".audit.jsonl"))


def _forked_ids(output):
    match = re.search(r"Forked Session (\S+) into (\S+);", output)
    return match.group(1), match.group(2)


def _skill(root, name):
    directory = root / ".agents" / "skills" / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: A skill\n---\nBody.\n")


def test_fork_continues_in_a_self_contained_child_and_leaves_the_parent_resumable(
    route_env, install_fake_urlopen, tmp_path
):
    _skill(tmp_path, "alpha")
    calls = install_fake_urlopen([
        {"tool_calls": [{"id": "t1", "name": "todo", "arguments": {"todos": TODOS}}], "usage": {"cost": 0.25}},
        {"content": "planned", "usage": {"cost": 0.25}},
        "second answer", "third answer", "the summary", "after fork",
    ])
    snapshot = []

    def stream():
        yield from ["plan it\n", "second task\n", "third task\n", "/compress\n", "/mode plan\n",
                    "/skill alpha\n", "/history\n"]
        snapshot.append(Path(call_log.session_log_path()).read_text())
        yield from ["/fork\n", "/history\n", "/usage\n", "/report\n", "/mode\n", "/skills\n", "next task\n",
                    "exit\n"]

    output = StringIO()
    run_repl(runtime_config.load(), input_stream=stream(), output_stream=output)
    text = output.getvalue()
    parent, child = _forked_ids(text)

    assert len(calls) == 6
    assert parent != child and call_log.current_session_id() == child
    assert f"Resume the parent with --resume {parent}." in text
    assert f"share the Workspace Root {tmp_path.resolve()}" in text
    before, after = text.split("Forked Session", 1)
    assert before[before.rindex("summary: "):].split("\n")[:3] == after[after.index("summary: "):].split("\n")[:3]
    assert "spend: $0.0000" in after
    assert f"Recorded Session report: {child}; inspected Runs: 1" in after
    assert "Latest opened executions" not in after
    assert "plan\n" in after and "* alpha" in after

    parent_lines = Path(call_log.session_log_path(parent)).read_text()
    assert parent_lines.startswith(snapshot[0])
    added = [json.loads(line) for line in parent_lines[len(snapshot[0]):].splitlines()]
    assert [entry["type"] for entry in added] == ["audit_event", "audit_coverage_end", "session_end"]
    assert added[0]["name"] == "/fork" and added[0]["outcome"] == "ok"
    assert added[-1]["reason"] == "fork" and added[-1]["child_session_id"] == child
    assert added[-1]["total_cost"] > 0

    parent_state = call_log.load_conversation(parent)
    assert parent_state[3] == 3 and call_log.load_pending_turn(parent) is None
    child_entries = _lines(child)
    assert child_entries[0]["type"] == "session_start" and child_entries[0]["parent_session_id"] == parent
    seed = child_entries[1]
    assert seed["type"] == "conversation_forked" and seed["parent_session_id"] == parent
    assert [tuple(turn) for turn in seed["turns"]] == list(parent_state[0])
    assert seed["summary"] == parent_state[1] == "the summary"
    assert seed["todo_baseline"] == parent_state[2] == TODOS
    submitted = [entry for entry in child_entries if entry["type"] == "routed_task_submitted"]
    assert [entry["ordinal"] for entry in submitted] == [1]
    first = child_entries.index(submitted[0])
    assert not [entry for entry in child_entries[:first] if entry["type"] in {"attempt", "tool_execution"}]
    turns, summary, baseline, submissions = call_log.load_conversation(child)
    assert turns[:-1] == parent_state[0] and summary == "the summary" and submissions == 1
    assert todo_module.current_list(turns, baseline) == todo_module.current_list(parent_state[0], parent_state[2])
    assert call_log.resolve_resume_session("last") == child


def _seeded_parent(config, turns=1):
    sid = call_log.start_session(config)
    for index in range(turns):
        call_log.write_routed_task(index + 1, f"task {index}", config)
        call_log.write_turn_end("ok", messages=({"role": "user", "content": f"task {index}"},
                                                {"role": "assistant", "content": f"answer {index}"}))
    call_log.end_session("exit_command")
    call_log.reset_session()
    return sid


def _fork_from(sid, lines="/fork\nexit\n"):
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(lines), output_stream=output,
             resumed=(sid, *call_log.load_conversation(sid)))
    return output.getvalue()


def test_child_resumes_after_the_parent_file_is_deleted(route_env, install_fake_urlopen):
    install_fake_urlopen(["unused"])
    parent = _seeded_parent(runtime_config.load(), turns=2)
    _, child = _forked_ids(_fork_from(parent))
    Path(call_log.session_log_path(parent)).unlink()
    call_log.reset_session()

    resumed = (child, *call_log.load_conversation(child))
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("/history\nexit\n"), output_stream=output, resumed=resumed)

    assert f"Resumed session {child}: 2 turns." in output.getvalue()
    assert "assistant: answer 1" in output.getvalue()


def test_session_logs_renders_the_seed_without_copied_bodies(route_env, install_fake_urlopen):
    install_fake_urlopen(["unused"])
    parent = _seeded_parent(runtime_config.load(), turns=2)
    _, child = _forked_ids(_fork_from(parent))

    result = session_logs.execute({"action": "read", "session": child, "limit": 100}, max_bytes=1_000_000)

    content = result["content"]
    line = next(line for line in content.splitlines() if "conversation_forked" in line)
    assert f'"parent_session_id": "{parent}"' in line and '"copied_turns": 2' in line
    assert "answer 0" not in content and "todo_baseline" not in content


def _start_job(tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    jobs.start(shutil.which("bash"), "sleep 30 & echo $! > child.pid; wait")
    path = tmp_path / "child.pid"
    deadline = time.monotonic() + 5
    while not (path.exists() and path.read_text().strip()) and time.monotonic() < deadline:
        time.sleep(0.02)
    return int(path.read_text())


def _gone(pid):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.02)
    return False


def test_fork_stops_jobs_and_records_the_implicit_stop_in_the_parent(route_env, install_fake_urlopen, tmp_path):
    install_fake_urlopen(["unused"])
    parent = _seeded_parent(runtime_config.load())
    pid = _start_job(tmp_path)

    _, child = _forked_ids(_fork_from(parent, "/fork\n/jobs\nexit\n"))

    assert _gone(pid)
    parent_entries = _lines(parent)
    stops = [entry for entry in parent_entries if entry.get("action") == "background_jobs_stopped"]
    assert [(entry["trigger"], entry["job_ids"]) for entry in stops] == [("fork", [1])]
    fork_event = next(entry for entry in parent_entries if entry.get("name") == "/fork")
    assert parent_entries.index(stops[0]) < parent_entries.index(fork_event)
    assert not [entry for entry in _lines(child) if entry.get("name") == "/fork"]
    assert not [entry for entry in _lines(child) if entry.get("action") == "background_jobs_stopped"]


def _refused(parent, tmp_path, message):
    pid = _start_job(tmp_path)
    files = _session_files()
    output = _fork_from(parent, "/fork\n/jobs\nexit\n")

    assert f"Error: {message}" in output
    assert "1 running" in output
    assert _session_files() == files
    entries = _lines(parent)
    assert [entry["outcome"] for entry in entries if entry.get("name") == "/fork"] == ["error"]
    assert entries[-1]["reason"] == "exit_command"
    assert _gone(pid)


def test_fork_is_refused_with_an_empty_conversation(route_env, install_fake_urlopen, tmp_path):
    install_fake_urlopen(["unused"])
    _refused(_seeded_parent(runtime_config.load(), turns=0), tmp_path, "the Conversation is empty")


@pytest.mark.parametrize("failure", [ValueError("provider down"), KeyboardInterrupt()])
def test_fork_is_refused_while_a_turn_awaits_retry_including_after_resume(
    route_env, install_fake_urlopen, tmp_path, failure
):
    install_fake_urlopen([failure])
    run_repl(runtime_config.load(), input_stream=StringIO("failing task\nexit\n"), output_stream=StringIO())
    parent = call_log.current_session_id()
    call_log.reset_session()

    _refused(parent, tmp_path, "a failed or interrupted turn awaits /retry")


def test_fork_is_refused_in_the_same_run_after_a_failed_turn(route_env, install_fake_urlopen):
    install_fake_urlopen([ValueError("provider down")])
    output = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO("failing task\n/fork\nexit\n"), output_stream=output)

    assert "Error: a failed or interrupted turn awaits /retry" in output.getvalue()
    assert len(_session_files()) == 1


def test_fork_is_refused_while_file_recovery_is_blocked(route_env, install_fake_urlopen, tmp_path):
    install_fake_urlopen(["unused"])
    parent = _seeded_parent(runtime_config.load())
    recovery = Path(call_log.session_log_path(parent)).parent / f"recovery-{parent}"
    recovery.mkdir(mode=0o700)
    (recovery / "unexpected").write_text("x")

    _refused(parent, tmp_path, "file recovery is unresolved")


def test_fork_with_arguments_is_refused(route_env, install_fake_urlopen):
    install_fake_urlopen(["unused"])
    parent = _seeded_parent(runtime_config.load())

    output = _fork_from(parent, "/fork now\nexit\n")

    assert "Error: /fork takes no arguments." in output
    assert len(_session_files()) == 1


def test_child_creation_failure_is_fatal_and_names_the_parent(route_env, install_fake_urlopen, monkeypatch):
    install_fake_urlopen(["unused"])
    parent = _seeded_parent(runtime_config.load())

    def fail():
        raise OSError("disk full")

    monkeypatch.setattr(call_log, "_validate_project_storage", fail)
    with pytest.raises(call_log.PersistenceError, match=f"parent Session {parent}.*--resume {parent}"):
        _fork_from(parent)

    assert len(_session_files()) == 1
    assert _lines(parent)[-1]["reason"] == "fork"


def test_seed_write_failure_removes_the_child_and_leaves_the_parent_resumable(
    route_env, install_fake_urlopen, monkeypatch
):
    install_fake_urlopen(["unused"])
    parent = _seeded_parent(runtime_config.load())
    original = call_log._write_line

    def write(entry, **kwargs):
        if entry["type"] == "conversation_forked":
            assert _lines(entry["session_id"])[0]["type"] == "session_start"
            raise OSError("disk full")
        return original(entry, **kwargs)

    monkeypatch.setattr(call_log, "_write_line", write)
    with pytest.raises(call_log.PersistenceError, match=f"parent Session {parent}.*--resume {parent}"):
        _fork_from(parent)
    monkeypatch.setattr(call_log, "_write_line", original)

    assert [path.name for path in _session_files()] == [f"pa_log-{parent}.jsonl"]
    call_log.reset_session()
    assert call_log.resolve_resume_session("last") == parent
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("/history\nexit\n"), output_stream=output,
             resumed=(parent, *call_log.load_conversation(parent)))
    assert f"Resumed session {parent}" in output.getvalue() and "assistant: answer 0" in output.getvalue()


def _child_file():
    parent = _seeded_parent(runtime_config.load(), turns=1)
    _, child = _forked_ids(_fork_from(parent))
    call_log.reset_session()
    return parent, child, Path(call_log.session_log_path(child))


def _rewrite(path, edit):
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    edit(entries)
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))


@pytest.mark.parametrize("edit", [
    lambda entries: entries[0].update(parent_session_id="not-an-id"),
    lambda entries: entries[0].update(parent_session_id=entries[0]["session_id"]),
    lambda entries: entries[0].update(parent_session_id=7),
    lambda entries: entries[0].pop("parent_session_id"),
    lambda entries: entries.pop(1),
    lambda entries: entries[1].update(parent_session_id="20000101T000000Z-aaaaaa"),
    lambda entries: entries[1].pop("parent_session_id"),
    lambda entries: entries[1].update(turns=[["not a message"]]),
    lambda entries: entries[1].update(turns="nope"),
    lambda entries: entries[1].update(summary=3),
    lambda entries: entries[1].update(todo_baseline={}),
    lambda entries: entries[1].update(extra=True),
    lambda entries: entries.append(dict(entries[1])),
    lambda entries: entries.insert(1, entries[2]),
])
def test_malformed_fork_seed_is_refused_before_any_append(route_env, install_fake_urlopen, edit):
    install_fake_urlopen(["unused"])
    _, child, path = _child_file()
    _rewrite(path, edit)
    content = path.read_bytes()

    with pytest.raises(call_log.ResumeError):
        call_log.load_conversation(child)
    with pytest.raises(call_log.ResumeError):
        call_log.resume_session(child, runtime_config.load())

    assert path.read_bytes() == content


def test_fork_seed_outside_line_two_of_a_plain_session_is_refused(route_env, install_fake_urlopen):
    install_fake_urlopen(["unused"])
    sid = _seeded_parent(runtime_config.load())
    path = Path(call_log.session_log_path(sid))
    _rewrite(path, lambda entries: entries.append({"timestamp": "x", "session_id": sid, "type": "conversation_forked",
                                                   "parent_session_id": "20000101T000000Z-aaaaaa", "turns": [],
                                                   "summary": None, "todo_baseline": []}))

    with pytest.raises(call_log.ResumeError):
        call_log.load_conversation(sid)


def test_fork_appears_in_help_and_completion():
    assert "/fork" in COMMANDS
    line = next(line for line in HELP_TEXT.splitlines() if line.startswith("/fork"))
    assert "new child Session" in line and "latest closed turn" in line and "Background Jobs" in line
    assert "--resume <id>" in line and "Workspace Root" in line


def test_detailed_audit_coverage_ends_in_the_parent_and_restarts_in_the_child(
    route_env, install_fake_urlopen, monkeypatch
):
    install_fake_urlopen(["unused"])
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    parent = _seeded_parent(runtime_config.load())

    _, child = _forked_ids(_fork_from(parent))

    parent_detail = [json.loads(line) for line in Path(call_log.detail_path(parent)).read_text().splitlines()]
    child_detail = [json.loads(line) for line in Path(call_log.detail_path(child)).read_text().splitlines()]
    assert [entry["type"] for entry in parent_detail][-2:] == ["action_end", "run_end"]
    assert child_detail[0]["type"] == "run_start" and child_detail[-1]["type"] == "run_end"
    assert not [entry for entry in child_detail if entry.get("name") == "/fork"]
    assert [entry["type"] for entry in _lines(child)].count("audit_coverage_start") == 1
