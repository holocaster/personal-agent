import json
from dataclasses import replace
from io import BytesIO, StringIO
from pathlib import Path

from personal_agent import call_log
from personal_agent.routing import runtime_config
from personal_agent.terminal.repl import run_repl
from personal_agent.tools import registry as tools, webfetch, workspace
from personal_agent.tools.builtins import ToolExecutionError


def entries():
    return [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]


def test_piped_commands_record_safe_outcomes_and_resume(route_env, install_fake_urlopen, monkeypatch, tmp_path):
    monkeypatch.setenv("PA_MEMORY_PATH", str(tmp_path / "memory.jsonl"))
    calls = install_fake_urlopen(["first", "second"])
    config = runtime_config.load()
    run_repl(config, input_stream=StringIO(
        "/mode plan\n/mode invalid\n/model\n/model bad\n/remember private note\n"
        "/forget 1\n/forget 1\n/unknown secret\n/config\nsummarize this line\nexit\n"
    ), output_stream=StringIO())
    first = entries()
    events = [entry for entry in first if entry["type"] == "audit_event"]
    assert [(e["name"], e["outcome"]) for e in events] == [
        ("/mode", "ok"), ("/mode", "error"), ("/model", "ok"), ("/model", "error"),
        ("/remember", "ok"), ("/forget", "ok"), ("/forget", "error"),
        ("/unknown", "error"), ("/config", "error"),
    ]
    assert events[0]["old"] == "build" and events[0]["new"] == "plan"
    assert "old" not in events[2] and events[3]["arguments_omitted"] is True
    assert events[5]["arguments"] == {"index": 1}
    assert "private note" not in json.dumps(events)
    assert "secret" not in json.dumps(events)
    assert len(calls) == 1
    session_id = call_log.current_session_id()
    turns, summary, todos, _ = call_log.load_conversation(session_id)
    assert len(turns) == 1
    run_repl(config, input_stream=StringIO("/mode\nsummarize this again\nexit\n"), output_stream=StringIO(),
             resumed=(session_id, turns, summary, todos, call_log.load_conversation(session_id)[3]))
    assert len(call_log.load_conversation(session_id)[0]) == 2
    assert [e for e in entries() if e["type"] == "audit_event"][-1]["outcome"] == "ok"
    assert len(calls) == 2


def test_tool_confirmations_precede_apply_and_auto_is_not_human_approval(route_env, install_fake_urlopen, tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()
    calls = install_fake_urlopen([
        {"tool_calls": [
            {"id": "yes", "name": "write", "arguments": {"path": "ok.txt", "content": "ok"}},
            {"id": "no", "name": "write", "arguments": {"path": "no.txt", "content": "no"}},
            {"id": "sh", "name": "shell", "arguments": {"command": "printf hi"}},
        ]}, "done",
        {"tool_calls": [{"id": "auto", "name": "write", "arguments": {"path": "auto.txt", "content": "auto"}}]},
        "done",
    ])
    run_repl(runtime_config.load(), input_stream=StringIO(
        "/mode build\nsummarize this line\ny\nn\ny\n/mode auto\nsummarize this again\nexit\n"
    ), output_stream=StringIO())
    data = entries()
    decisions = [e for e in data if e["type"] == "audit_event" and e["action"] == "tool_confirmation"]
    assert [(e["tool_call_id"], e["decision"]) for e in decisions] == [
        ("yes", "approved"), ("no", "rejected"), ("sh", "approved")
    ]
    for decision in decisions:
        result = next(i for i, e in enumerate(data) if e["type"] == "tool_execution" and
                      e["tool_call_id"] == decision["tool_call_id"])
        assert data.index(decision) < result
    assert (tmp_path / "ok.txt").read_text() == "ok"
    assert not (tmp_path / "no.txt").exists()
    assert (tmp_path / "auto.txt").read_text() == "auto"
    assert len(calls) == 4


def test_interactive_config_and_mode_toggle_redact_current_and_previous_keys(route_env, install_fake_urlopen):
    class Box:
        def __init__(self):
            self.reads = iter(["/config", "/mode invalid", "/remember private note", "/exit"])
            self.answers = iter(["key", "openrouter", "key", "openrouter", "context", "budget",
                                 "350000", "done"])
            self.keys = iter(["key-one", "key-two"])

        def read(self):
            if self.on_mode_toggle is not None:
                self.on_mode_toggle()
            return next(self.reads)

        def ask(self, question):
            return next(self.answers)

        def ask_secret(self, question):
            return next(self.keys)

    install_fake_urlopen([])
    box = Box()
    run_repl(runtime_config.load(), input_box=box, output_stream=StringIO())
    events = [e for e in entries() if e["type"] == "audit_event"]
    settings = [e for e in events if e["action"] == "config_setting"]
    assert [(e["setting"], e["outcome"]) for e in settings] == [
        ("key", "ok"), ("key", "ok"), ("context", "ok")
    ]
    assert (settings[-1]["old"], settings[-1]["new"]) == ("250000", "350000")
    assert [(e["old"], e["new"]) for e in events if e["action"] == "mode_toggle"] == [
        ("build", "auto"), ("auto", "plan"), ("plan", "build"), ("build", "auto")
    ]
    assert "key-one" not in json.dumps(events) and "key-two" not in json.dumps(events)
    assert "private note" not in json.dumps(events)


def test_accepted_key_matching_event_field_preserves_schema(route_env, install_fake_urlopen):
    class Box:
        def __init__(self):
            self.reads = iter(["/config", "/mode plan", "/exit"])
            self.answers = iter(["key", "openrouter", "done"])

        def read(self):
            return next(self.reads)

        def ask(self, question):
            return next(self.answers)

        def ask_secret(self, question):
            return "name"

    install_fake_urlopen([])
    run_repl(runtime_config.load(), input_box=Box(), output_stream=StringIO())
    events = [e for e in entries() if e["type"] == "audit_event"]
    assert [(e["action"], e.get("name"), e["outcome"]) for e in events] == [
        ("config_setting", None, "ok"), ("command", "/config", "ok"),
        ("command", "/mode", "ok"), ("command", "/exit", "ok"),
    ]
    assert events[1]["arguments_omitted"] is True
    assert events[2]["arguments"] == ["plan"]
    assert all("[redacted]" not in e for e in events)


def test_nested_audit_values_redact_without_renaming_fields(route_env):
    call_log.start_session(runtime_config.load())
    call_log.write_audit_event(action="command", name="/sample", secrets=("name",),
                               arguments={"name": "name", "nested": [{"name": "before-name-after"}]})
    event = entries()[-1]
    assert event["name"] == "/sample"
    assert event["arguments"] == {"name": "[redacted]", "nested": [{"name": "before-[redacted]-after"}]}


def test_fixed_outcomes_and_modes_survive_colliding_keys_but_user_values_do_not(
    route_env, install_fake_urlopen,
):
    class Box:
        def __init__(self):
            self.reads = iter(["/config", "/mode auto", "/model auto", "/exit"])
            self.answers = iter(["key", "openrouter", "key", "openrouter", "key", "openrouter",
                                 "context", "budget", "350000", "done"])
            self.keys = iter(["ok", "auto", "350000"])

        def read(self):
            return next(self.reads)

        def ask(self, question):
            return next(self.answers)

        def ask_secret(self, question):
            return next(self.keys)

    install_fake_urlopen([])
    run_repl(runtime_config.load(), input_box=Box(), output_stream=StringIO())
    events = [e for e in entries() if e["type"] == "audit_event"]
    settings = [e for e in events if e["action"] == "config_setting"]
    assert [(e["setting"], e["outcome"]) for e in settings] == [
        ("key", "ok"), ("key", "ok"), ("key", "ok"), ("context", "ok")
    ]
    assert settings[3]["new"] == "[redacted]"
    mode = next(e for e in events if e.get("name") == "/mode")
    assert (mode["outcome"], mode["old"], mode["new"]) == ("ok", "build", "auto")
    assert mode["arguments"] == ["[redacted]"]
    model = next(e for e in events if e.get("name") == "/model")
    assert model["outcome"] == "error" and "old" not in model and model["arguments_omitted"] is True


def test_fixed_confirmation_values_survive_colliding_keys_but_tool_identity_does_not(route_env):
    call_log.start_session(runtime_config.load())
    call_log.write_audit_event(
        action="tool_confirmation", tool_call_id="approved", name="eval", decision="approved",
        dangerous_rules=["eval"], secrets=("approved", "eval"),
    )
    event = entries()[-1]
    assert (event["decision"], event["dangerous_rules"]) == ("approved", ["eval"])
    assert (event["tool_call_id"], event["name"]) == ("[redacted]", "[redacted]")


def test_failed_apply_and_strong_confirmation_keep_distinct_decisions(route_env, install_fake_urlopen, monkeypatch, tmp_path):
    workspace.configure_workspace(tmp_path)
    tools.enable_shell_tool()

    def fail_apply(prepared):
        raise ToolExecutionError("apply failed")

    monkeypatch.setitem(tools._REGISTRY, "write", replace(tools._REGISTRY["write"], apply=fail_apply))
    install_fake_urlopen([
        {"tool_calls": [{"id": "fail", "name": "write", "arguments": {"path": "no.txt", "content": "no"}}]},
        "done",
        {"tool_calls": [{"id": "strong", "name": "shell", "arguments": {"command": "eval ':'"}}]},
        "done",
    ])
    run_repl(runtime_config.load(), input_stream=StringIO(
        "summarize this line\ny\n/mode auto\nsummarize this again\ny\nexit\n"
    ), output_stream=StringIO())
    events = [e for e in entries() if e["type"] == "audit_event" and e["action"] == "tool_confirmation"]
    assert [(e["tool_call_id"], e["decision"], e["dangerous_rules"]) for e in events] == [
        ("fail", "approved", []), ("strong", "rejected", ["eval"])
    ]
    results = [e for e in entries() if e["type"] == "tool_execution"]
    assert results[0]["error"] == "apply failed"
    assert results[1]["error"] == "change rejected by the user"
    assert not (tmp_path / "no.txt").exists()


def test_plan_network_confirmation_and_batch_correlation_error(route_env, install_fake_urlopen, monkeypatch):
    class Response(BytesIO):
        status = 200
        headers = {"Content-Type": "text/plain"}

        def geturl(self):
            return "https://example.com/"

    class Opener:
        def open(self, request, timeout):
            return Response(b"safe")

    monkeypatch.setattr(webfetch, "build_opener", lambda *handlers: Opener())
    install_fake_urlopen([
        {"tool_calls": [{"id": "fetch", "name": "webfetch", "arguments": {"url": "https://example.com/"}}]},
        "done",
        {"tool_calls": [{"id": "same", "name": "calculator", "arguments": {"expression": "1+1"}},
                        {"id": "same", "name": "calculator", "arguments": {"expression": "2+2"}}]},
    ])
    run_repl(runtime_config.load(), input_stream=StringIO(
        "/mode plan\nsummarize this line\ny\nsummarize this again\nexit\n"
    ), output_stream=StringIO())
    data = entries()
    assert [(e["name"], e["decision"]) for e in data if e["type"] == "audit_event" and
            e["action"] == "tool_confirmation"] == [("webfetch", "approved")]
    assert [e["error"] for e in data if e["type"] == "turn_end" and e["status"] == "error"] == [
        "malformed Tool call batch: duplicate Tool call ids"
    ]
    assert [e["name"] for e in data if e["type"] == "tool_execution"] == ["webfetch"]


def test_interrupted_confirmation_does_not_claim_approval(route_env, install_fake_urlopen, tmp_path):
    workspace.configure_workspace(tmp_path)
    install_fake_urlopen([{"tool_calls": [{"id": "interrupt", "name": "write", "arguments": {
        "path": "no.txt", "content": "no"}}]}])

    class InterruptingInput:
        def __iter__(self):
            yield "summarize this line"
            raise KeyboardInterrupt

    run_repl(runtime_config.load(), input_stream=InterruptingInput(), output_stream=StringIO())
    data = entries()
    assert [(e["decision"], e["tool_call_id"]) for e in data if e["type"] == "audit_event"] == [
        ("interrupted", "interrupt")
    ]
    assert [e["status"] for e in data if e["type"] == "turn_end"] == ["interrupted"]
    assert not (tmp_path / "no.txt").exists()


def test_oversized_forget_index_is_a_recorded_error(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    run_repl(runtime_config.load(), input_stream=StringIO(
        "/remember fact\n/forget " + "9" * 5000 + "\n/exit\n"
    ), output_stream=StringIO())
    events = [e for e in entries() if e["type"] == "audit_event"]
    assert [(e["name"], e["outcome"]) for e in events] == [
        ("/remember", "ok"), ("/forget", "error"), ("/exit", "ok")
    ]
    assert len(json.dumps(events)) < 3000


def test_forget_last_two_digit_index_records_successful_index(route_env, install_fake_urlopen):
    install_fake_urlopen([])
    run_repl(runtime_config.load(), input_stream=StringIO(
        "/remember fact\n" * 10 + "/forget 10\n/exit\n"
    ), output_stream=StringIO())
    event = next(e for e in entries() if e.get("name") == "/forget")
    assert event["outcome"] == "ok"
    assert event["arguments"] == {"index": 10}
    assert event["old"] == 10 and event["new"] == 9
    assert "arguments_omitted" not in event


def test_retry_interruption_is_recorded_as_cancelled(route_env, install_fake_urlopen):
    install_fake_urlopen(["first", KeyboardInterrupt()])
    run_repl(runtime_config.load(), input_stream=StringIO(
        "summarize this line\n/retry\n/exit\n"
    ), output_stream=StringIO())
    data = entries()
    assert [e["status"] for e in data if e["type"] == "turn_end"] == ["ok", "interrupted"]
    assert next(e for e in data if e.get("name") == "/retry")["outcome"] == "cancelled"


def test_compress_interruption_is_recorded_as_cancelled(route_env, install_fake_urlopen):
    install_fake_urlopen(["first", "second", "third", KeyboardInterrupt()])
    run_repl(runtime_config.load(), input_stream=StringIO(
        "summarize first\nsummarize second\nsummarize third\n/compress\n/exit\n"
    ), output_stream=StringIO())
    data = entries()
    assert next(e for e in data if e.get("name") == "/compress")["outcome"] == "cancelled"
    assert not any(e["type"] == "conversation_compressed" for e in data)
    assert len(call_log.load_conversation(call_log.current_session_id())[0]) == 3


def test_interactive_config_rejection_is_recorded_on_disk(route_env, install_fake_urlopen):
    class Box:
        def __init__(self):
            self.reads = iter(["/config", "/exit"])
            self.answers = iter(["easy", "done"])

        def read(self):
            return next(self.reads)

        def ask(self, question):
            return next(self.answers)

    install_fake_urlopen([])
    run_repl(runtime_config.load(), input_box=Box(), output_stream=StringIO())
    settings = [e for e in entries() if e.get("action") == "config_setting"]
    assert [(e["setting"], e["outcome"]) for e in settings] == [("menu", "error")]
    assert "tier" not in settings[0]
    assert "old" not in settings[0] and "new" not in settings[0]


def test_skill_changes_and_failed_commands_have_no_false_transition(route_env, install_fake_urlopen, tmp_path):
    workspace.configure_workspace(tmp_path)
    skill = tmp_path / ".agents" / "skills" / "alpha"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: alpha\ndescription: Test skill\n---\nUseful instructions.\n")
    install_fake_urlopen([])
    run_repl(runtime_config.load(), input_stream=StringIO(
        "/skill alpha\n/skill missing\n/skill off alpha\n/skill off alpha\n"
        "/remember\n/undo\n/compress\n/exit\n"
    ), output_stream=StringIO())
    events = [e for e in entries() if e["type"] == "audit_event"]
    assert [(e["name"], e["outcome"]) for e in events] == [
        ("/skill", "ok"), ("/skill", "error"), ("/skill", "ok"), ("/skill", "error"),
        ("/remember", "error"), ("/undo", "error"), ("/compress", "error"), ("/exit", "ok")
    ]
    assert [(e["old"], e["new"]) for e in events if "new" in e] == [
        ([], ["alpha"]), (["alpha"], [])
    ]
