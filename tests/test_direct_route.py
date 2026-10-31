import builtins
import json
from dataclasses import replace
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from personal_agent import call_log
from personal_agent.__main__ import main
from personal_agent.routing import router, runtime_config
from personal_agent.terminal import repl
from personal_agent.terminal.repl import run_repl

_REAL_OPEN = builtins.open
MODEL = "vendor/test-model"


def _http_error(code):
    return HTTPError("https://openrouter.ai", code, "err", None, None)


def _bodies(calls):
    return [json.loads(call["request"].data) for call in calls]


def _entries(session_id=None):
    path = Path(call_log.session_log_path(session_id))
    return [json.loads(line) for line in path.read_text().splitlines()]


def _run(text, config=None, resumed=None, **kwargs):
    output = StringIO()
    run_repl(config or runtime_config.load(), input_stream=StringIO(text), output_stream=output,
             resumed=resumed, **kwargs)
    return output.getvalue()


def _resume_args():
    session_id = call_log.current_session_id()
    call_log.reset_session()
    return (session_id, *call_log.load_conversation(session_id))


def _rewrite_log(transform):
    path = Path(call_log.session_log_path())
    entries = transform([json.loads(line) for line in path.read_text().splitlines()])
    path.write_text("".join(json.dumps(item) + "\n" for item in entries))


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(router, "_sleep", lambda seconds: None)


def test_first_fifth_and_fifteenth_tasks_dispatch_only_the_configured_pair(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([f"answer {index}" for index in range(1, 16)])
    tasks = [f"task {index}" for index in range(1, 16)]

    output = _run("\n".join(tasks) + "\nexit\n")

    bodies = _bodies(calls)
    assert len(bodies) == 15
    assert {body["model"] for body in bodies} == {MODEL}
    assert [bodies[index]["messages"][-1]["content"] for index in (0, 4, 14)] == ["task 1", "task 5", "task 15"]
    assert output.startswith("Provider/model: openrouter vendor/test-model\n")
    assert output.count("[openrouter] vendor/test-model\n") == 15
    entries = _entries()
    assert {entry["purpose"] for entry in entries if entry["type"] == "attempt"} == {"execution"}
    assert not any("tier" in json.dumps(entry) or "routing_policy" in entry for entry in entries)
    assert call_log.load_conversation(call_log.current_session_id())[3] == 15


def test_new_call_log_is_version_three_with_direct_routes_at_runs_and_openings(route_env, install_fake_urlopen):
    install_fake_urlopen([ValueError("failed"), "retried"])

    _run("task\n/retry\nexit\n")

    start, *rest = _entries()
    assert set(start) == {"timestamp", "session_id", "type", "log_version", "workspace_root", "project_id",
                          "run_id", "provider", "model", "access_method"}
    assert (start["log_version"], start["provider"], start["model"]) == (3, "openrouter", MODEL)
    openings = [entry for entry in rest if entry["type"] in {"routed_task_submitted", "routed_task_retried"}]
    assert [{key: entry[key] for key in entry if key not in {"timestamp", "session_id"}} for entry in openings] == [
        {"type": "routed_task_submitted", "ordinal": 1, "task": "task", "provider": "openrouter", "model": MODEL,
         "access_method": "api_key"},
        {"type": "routed_task_retried", "ordinal": 1, "provider": "openrouter", "model": MODEL, "access_method": "api_key"},
    ]
    attempts = [entry for entry in rest if entry["type"] == "attempt"]
    assert [(entry["provider"], entry["model"], entry["outcome"]) for entry in attempts] == [
        ("openrouter", MODEL, "error"), ("openrouter", MODEL, "ok")]
    assert not any('"api_key":' in json.dumps(entry) or "test-key" in json.dumps(entry) for entry in _entries())


def test_submission_identity_survives_failure_interrupt_retry_and_identical_text(route_env, install_fake_urlopen):
    install_fake_urlopen([ValueError("ordinary failure"), "retried", KeyboardInterrupt(), "retried again",
                          "answer 3"])

    _run("same\n/retry\nsame\n/retry\nthird\nexit\n")

    openings = [(entry["type"], entry["ordinal"], entry.get("task")) for entry in _entries()
                if entry["type"] in {"routed_task_submitted", "routed_task_retried"}]
    assert openings == [("routed_task_submitted", 1, "same"), ("routed_task_retried", 1, None),
                        ("routed_task_submitted", 2, "same"), ("routed_task_retried", 2, None),
                        ("routed_task_submitted", 3, "third")]
    executions = []
    run_id = None
    for position, entry in enumerate(_entries(), 1):
        if entry["type"] == "session_start":
            run_id = entry["run_id"]
        elif entry["type"] in {"routed_task_submitted", "routed_task_retried"}:
            executions.append((run_id, position, entry["ordinal"]))
    assert len(set(executions)) == 5
    assert call_log.latest_execution() == dict(zip(("run_id", "opening", "ordinal"), executions[-1]))


@pytest.mark.parametrize("edit", ["/undo", "/clear", "/compress"])
def test_clear_undo_and_compression_preserve_count_across_resume(route_env, install_fake_urlopen, edit):
    install_fake_urlopen(["a1", "a2", "a3", "summary", "a4"])

    _run(f"one\ntwo\nthree\n{edit}\nfour\nexit\n")

    resumed = _resume_args()
    assert resumed[4] == 4
    install_fake_urlopen(["a5"])
    _run("five\nexit\n", resumed=resumed)
    assert [entry["ordinal"] for entry in _entries() if entry["type"] == "routed_task_submitted"] == [1, 2, 3, 4, 5]


def test_clear_discards_input_but_keeps_count_configuration_and_spend(route_env, install_fake_urlopen):
    install_fake_urlopen([{"content": "a1", "usage": {"cost": 0.25}}])

    output = _run("one\n/clear\nexit\n")

    assert "Conversation cleared. Submission count, configuration and spend preserved.\n" in output
    assert call_log.total_cost() == 0.25
    assert call_log.load_conversation(call_log.current_session_id())[0] == ()
    assert call_log.load_conversation(call_log.current_session_id())[3] == 1


def test_retry_after_resume_adopts_a_changed_pair_and_keeps_normalized_pending_messages(
    route_env, install_fake_urlopen, monkeypatch
):
    calls = install_fake_urlopen([
        {"content": None, "tool_calls": [{"id": "c1", "name": "calculator", "arguments": {"expression": "2+2"}}]},
        _http_error(400),
    ])
    _run("compute\nexit\n")
    resumed = _resume_args()
    monkeypatch.setenv("PA_MODEL", "vendor/changed-model")
    calls = install_fake_urlopen(["done"])

    output = _run("/retry\nexit\n", resumed=resumed)

    body = _bodies(calls)[0]
    assert body["model"] == "vendor/changed-model"
    assert [message["role"] for message in body["messages"][1:]] == ["user", "assistant", "tool"]
    assert "[openrouter] vendor/changed-model\n" in output
    entries = _entries()
    resumed_entry = next(entry for entry in entries if entry["type"] == "session_resumed")
    retried = next(entry for entry in entries if entry["type"] == "routed_task_retried")
    assert (resumed_entry["model"], retried["model"], retried["ordinal"]) == ("vendor/changed-model",) * 2 + (1,)
    first_attempt = next(entry for entry in entries if entry["type"] == "attempt")
    assert first_attempt["model"] == MODEL


def test_resume_keeps_session_id_uses_current_configuration_and_resets_run_spend(
    route_env, install_fake_urlopen, monkeypatch
):
    install_fake_urlopen([{"content": "answer", "usage": {"cost": 0.2}}])
    _run("task\nexit\n")
    session_id = call_log.current_session_id()
    resumed = _resume_args()
    monkeypatch.setenv("PA_PROVIDER", "anthropic")
    monkeypatch.setenv("PA_MODEL", "claude-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    output = _run("/model\nexit\n", resumed=resumed)

    assert call_log.current_session_id() == session_id
    assert call_log.total_cost() == 0.0
    assert output.count("Provider/model: anthropic claude-test\n") == 2
    assert "Change with /model <provider> <model-id>" in output
    assert _entries()[-1]["type"] == "session_end"


def test_old_selector_values_are_rejected_and_help_is_current(route_env, install_fake_urlopen):
    install_fake_urlopen([])

    output = _run("/model complex\n/model auto\n/help\nexit\n")

    assert output.count("Error: usage: /model [<provider> <model-id>]\n") == 2
    assert {"/model", "/models", "/models refresh"} <= set(repl.COMMANDS)
    assert "/model auto" not in repl.COMMANDS
    for stale in ("easy", "medium", "complex", "evaluat", "tier"):
        assert stale not in repl.HELP_TEXT
    assert not any("tier" in json.dumps(entry) for entry in _entries())


def test_footer_shows_the_configured_pair(route_env, install_fake_urlopen):
    class Box:
        def __init__(self):
            self.lines = iter(["/exit"])
            self.footer = None
            self.snapshots = []

        def read(self):
            self.snapshots.append(self.footer())
            return next(self.lines)

    box = Box()
    install_fake_urlopen([])
    run_repl(runtime_config.load(), input_box=box, output_stream=StringIO())
    assert box.snapshots == [" mode: build · openrouter vendor/test-model · API key · ctx unknown · $0.0000 · /help"]


def test_manual_compression_uses_the_configured_pair_and_compression_affinity(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["a1", "a2", "a3", "summary"])

    _run("one\ntwo\nthree\n/compress\nexit\n")

    bodies = _bodies(calls)
    sid = call_log.current_session_id()
    assert [body["model"] for body in bodies] == [MODEL] * 4
    assert [body.get("session_id") for body in bodies] == [sid] * 3 + [f"{sid}:compression"]


def _write_old_log(version=2):
    _run("exit\n")
    sid = call_log.current_session_id()
    _rewrite_log(lambda entries: [{**entries[0], "log_version": version, "session_tier": "pending",
                                   "tiers": {"easy": {"provider": "openrouter", "model": MODEL}}}, *entries[1:]])
    call_log.reset_session()
    return sid


@pytest.mark.parametrize("selector", ["id", "last"])
def test_older_versions_are_refused_before_append_with_files_intact(
    route_env, install_fake_urlopen, capsys, monkeypatch, selector
):
    calls = install_fake_urlopen([])
    sid = _write_old_log()
    path = Path(call_log.session_log_path(sid))
    before = path.read_bytes()
    call_log.reset_session()
    monkeypatch.setattr("sys.stdin", StringIO("task\nexit\n"))

    with pytest.raises(SystemExit) as stopped:
        main(["--resume", sid if selector == "id" else "last"])

    assert stopped.value.code == 1
    assert capsys.readouterr().err == (f"session {sid} was not recorded with log_version 3 and cannot be resumed; "
                                       "its files were left unchanged\n")
    assert path.read_bytes() == before
    assert calls == []


def test_last_selects_a_newer_version_three_session_beside_old_files(route_env, install_fake_urlopen):
    install_fake_urlopen(["answer"])
    _write_old_log()
    _run("task\nexit\n")
    newer = call_log.current_session_id()
    call_log.reset_session()

    assert call_log.resolve_resume_session("last") == newer
    assert call_log.load_conversation(newer)[3] == 1


@pytest.mark.parametrize("change", [
    lambda e: e[:1] + [{**e[1], "ordinal": 2}] + e[2:],
    lambda e: e[:1] + [{**e[1], "task": " "}] + e[2:],
    lambda e: e[:1] + [{key: value for key, value in e[1].items() if key != "provider"}] + e[2:],
    lambda e: e[:1] + [{**e[1], "model": ""}] + e[2:],
    lambda e: e[:1] + [{**e[1], "provider": "unknown"}] + e[2:],
    lambda e: [{**e[0], "model": None}] + e[1:],
    lambda e: [{**e[0], "provider": "openrouterx"}] + e[1:],
    lambda e: e + [{**e[1], "type": "routed_task_retried", "ordinal": 2}],
    lambda e: e + [{**e[1], "type": "routed_task_retried", "ordinal": 0}],
    lambda e: e + [{**e[1], "ordinal": 1}],
    lambda e: e + [{**e[0], "type": "session_resumed", "log_version": 2}],
    lambda e: e + [{**e[0]}],
])
def test_malformed_new_records_fail_resume_instead_of_guessing(route_env, install_fake_urlopen, change):
    install_fake_urlopen(["answer"])
    _run("task\nexit\n")
    sid = call_log.current_session_id()
    _rewrite_log(lambda entries: change([entries[0], next(e for e in entries if e["type"] == "routed_task_submitted"),
                                         *[e for e in entries[1:] if e["type"] != "routed_task_submitted"]]))

    with pytest.raises(call_log.ResumeError):
        call_log.load_conversation(sid)


def test_attempts_never_open_submissions_or_routes(route_env, install_fake_urlopen):
    install_fake_urlopen(["answer"])
    _run("task\nexit\n")
    sid = call_log.current_session_id()
    _rewrite_log(lambda entries: [entry for entry in entries if entry["type"] != "routed_task_submitted"])

    assert call_log.load_conversation(sid)[3] == 0
    assert call_log.latest_execution(sid) is None


def _failing_append(monkeypatch, *, restore_fails, record_type):
    real_open = _REAL_OPEN

    class Partial:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.file.close()
            return False

        def write(self, text):
            if f'"type": "{record_type}"' in text:
                self.file.write(text[:15])
                self.file.flush()
                raise OSError("disk full")
            return self.file.write(text)

        def flush(self):
            self.file.flush()

        def __getattr__(self, name):
            return getattr(self.file, name)

        def truncate(self, offset):
            if restore_fails:
                raise OSError("restore denied")
            return self.file.truncate(offset)

    def fake_open(path, mode="r", *args, **kwargs):
        file = real_open(path, mode, *args, **kwargs)
        return Partial(file) if mode == "a" and isinstance(path, int) else file

    monkeypatch.setattr(builtins, "open", fake_open)


@pytest.mark.parametrize("restore_fails", [False, True])
@pytest.mark.parametrize("operation", ["start", "submission", "retry", "clear"])
def test_cli_fatal_partial_start_opening_and_clear_writes_prevent_dependent_actions(
    route_env, install_fake_urlopen, monkeypatch, capsys, restore_fails, operation
):
    argv = []
    if operation in ("retry", "clear"):
        install_fake_urlopen([ValueError("failed")])
        _run("old task\nexit\n")
        sid = call_log.current_session_id()
        before = call_log.load_conversation(sid)
        argv = ["--resume", sid]
        call_log.reset_session()
    calls = install_fake_urlopen(["answer"])
    record = {"start": "session_start", "submission": "routed_task_submitted", "retry": "routed_task_retried",
              "clear": "conversation_cleared"}[operation]
    script = {"clear": "/clear\nlater\n", "retry": "/retry\n"}.get(operation, "task\n")
    monkeypatch.setattr("sys.stdin", StringIO(script))
    _failing_append(monkeypatch, restore_fails=restore_fails, record_type=record)

    with pytest.raises(SystemExit) as stopped:
        main(argv)

    assert stopped.value.code == 1
    assert capsys.readouterr().err.startswith("Fatal persistence error:")
    assert calls == []
    monkeypatch.setattr(builtins, "open", _REAL_OPEN)
    if restore_fails:
        with pytest.raises(call_log.ResumeError):
            call_log.load_conversation(call_log.current_session_id())
    else:
        assert not any(entry["type"] == record for entry in _entries()[1:])
        if operation in ("retry", "clear"):
            assert call_log.load_conversation(sid) == before


def test_project_instructions_failure_before_any_attempt_records_the_opening_route(
    route_env, install_fake_urlopen, monkeypatch
):
    from personal_agent import project_instructions

    install_fake_urlopen([])
    original = project_instructions.load
    loads = [0]

    def failing(root):
        loads[0] += 1
        if loads[0] == 2:
            raise project_instructions.LoadError("AGENTS.md", None, "unreadable")
        return original(root)

    monkeypatch.setattr(project_instructions, "load", failing)
    _run("task\nexit\n")

    pending = call_log.load_pending_turn(call_log.current_session_id())
    assert pending[0] == 1
    assert (pending[1]["provider"], pending[1]["model"]) == ("openrouter", MODEL)
    assert not any(entry["type"] == "attempt" for entry in _entries())


def test_configuration_snapshot_is_shared_by_tools_follow_ups_and_retries(route_env, install_fake_urlopen, monkeypatch):
    calls = install_fake_urlopen([
        {"content": None, "tool_calls": [{"id": "c1", "name": "calculator", "arguments": {"expression": "1+1"}}]},
        _http_error(503), "done",
    ])
    config = runtime_config.load()
    seen = []
    original = router._run_exchange

    def recording(task, messages, provider_name, provider, model, *args, **kwargs):
        seen.append((provider_name, model, kwargs["context_config"]))
        return original(task, messages, provider_name, provider, model, *args, **kwargs)

    monkeypatch.setattr(router, "_run_exchange", recording)
    _run("task\nexit\n", config=replace(config, context_budget_tokens=200000))

    assert [body["model"] for body in _bodies(calls)] == [MODEL] * 3
    assert len({id(item[2]) for item in seen}) == 1
    assert {(item[0], item[1], item[2].context_budget_tokens) for item in seen} == {("openrouter", MODEL, 200000)}
