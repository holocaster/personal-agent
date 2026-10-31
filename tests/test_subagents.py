import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from personal_agent import call_log, session_report, subagents
from personal_agent.routing.router import route
from personal_agent.routing.runtime_config import load
from personal_agent.tools import jobs, registry, shell
from personal_agent.tools.workspace import configure_workspace
from tests.subagent_worker import install_provider, install_scripted_provider


def role(root, name="researcher", tools="Read"):
    directory = root / ".agents" / "agents"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.md"
    target.write_text(f"---\nname: {name}\ndescription: Research a task\ntools: {tools}\n---\nIndependent role instructions.\n")
    return target


def delegate(install_fake_urlopen, name="researcher", task="Inspect the workspace"):
    return install_fake_urlopen([
        {"tool_calls": [{"id": "delegate", "name": "agent", "arguments": {"name": name, "task": task}}]},
        "Parent completed",
    ])


def test_native_child_has_fresh_process_context_route_and_linked_session(tmp_path, monkeypatch, route_env,
                                                                       install_fake_urlopen):
    from personal_agent import subagents
    monkeypatch.setattr(subagents, "worker_bootstrap", install_provider)
    configure_workspace(tmp_path)
    role(tmp_path)
    config = load()
    parent = call_log.start_session(config)
    call_log.write_routed_task(1, "Parent task", config)
    calls = delegate(install_fake_urlopen)
    results = []
    result = route("Parent task", config, history=[{"role": "user", "content": "PRIVATE HISTORY"}],
                   summary="PRIVATE SUMMARY", memory_notes=[{"text": "PRIVATE MEMORY"}],
                   on_tool_result=results.append, project_instructions="Project rules")
    assert result.ok
    child = results[0].content
    assert child["status"] == "completed"
    assert child["name"] == "researcher"
    assert child["session_id"] != parent
    evidence = json.loads(child["answer"])
    assert evidence["pid"] != os.getpid()
    request = evidence["request"]
    text = json.dumps(request)
    assert "Independent role instructions" in text
    assert "Project rules" in text
    assert all(secret not in text for secret in ("PRIVATE HISTORY", "PRIVATE SUMMARY", "PRIVATE MEMORY"))
    assert request["model"] == config.model
    assert {item["function"]["name"] for item in request["tools"]} == {"read_file"}
    assert len(calls) == 2
    entries = call_log._read_entries(child["session_id"])
    assert entries[0]["session_kind"] == "subagent"
    assert entries[0]["parent_session_id"] == parent
    assert entries[0]["parent_tool_call_id"] == "delegate"
    assert len([entry for entry in entries if entry["type"] == "attempt"]) == 1
    assert len([entry for entry in entries if entry["type"] == "turn_end"]) == 1
    assert entries[-1]["type"] == "session_end"

    assert call_log.total_cost() == 0.25
    parent_entries = call_log._read_entries(parent)
    assert len([entry for entry in parent_entries if entry["type"] == "attempt"]) == 2
    assert [entry["type"] for entry in parent_entries if entry["type"].startswith("delegation_")] == [
        "delegation_started", "delegation_receipt", "delegation_finished"]


@pytest.fixture
def run_child(tmp_path, monkeypatch, route_env, install_fake_urlopen):
    configure_workspace(tmp_path)
    monkeypatch.setattr(subagents, "worker_bootstrap", install_scripted_provider)
    config = load()
    parent = call_log.start_session(config)
    ordinal = [0]
    def run(actions, *, mode="build", confirm=None, name="researcher", before_dispatch=None, change_settings=False):
        (tmp_path / "worker-script.json").write_text(json.dumps({"actions": actions, "change_settings": change_settings}))
        ordinal[0] += 1
        call_log.write_routed_task(ordinal[0], "Parent task", config)
        calls = delegate(install_fake_urlopen, name)
        if before_dispatch:
            original = subagents.Delegation.execute
            def dispatch(self, call):
                before_dispatch()
                return original(self, call)
            monkeypatch.setattr(subagents.Delegation, "execute", dispatch)
        results = []
        routed = route("Parent task", config, mode=mode, confirm=confirm, on_tool_result=lambda result: results.append(result) if result.name == "agent" else None)
        return routed, results, calls
    run.parent = parent
    run.config = config
    return run


@pytest.mark.parametrize(("allowlist", "expected"), [
    (None, {"calculator", "current_time", "session_logs", "read_file", "list_files", "search_text", "write", "edit", "apply_patch", "webfetch", "todo"}),
    ("[]", set()), ("Read, Edit, mystery", {"read_file", "edit"}), ("mystery", set()),
    ("Bash, WebSearch, mcp_read_resource, agent, question", set()),
])
def test_child_permissions_intersect_configured_parent_and_role(tmp_path, run_child, allowlist, expected):
    path = role(tmp_path, tools=allowlist or "Read")
    if allowlist is None:
        path.write_text(path.read_text().replace("tools: Read\n", ""))
    routed, results, _ = run_child([{"assert_tools": list(expected), "answer": "questions_pending: []"}])
    assert routed.ok
    assert results[0].content["status"] == "completed", results[0].content
    assert results[0].content["answer"] == "questions_pending: []"


def test_fabricated_forbidden_calls_fail_before_validation_confirmation_or_side_effect(tmp_path, run_child):
    role(tmp_path, tools="Read")
    prompts = []
    routed, results, _ = run_child([
        {"calls": [(name, {}) for name in ("write", "shell", "websearch", "mcp_read_resource", "agent", "question", "skill")]},
        {},
    ], confirm=lambda *args: prompts.append(args) or True)
    child = results[0].content
    assert child["status"] == "completed", child
    requests = json.loads(child["answer"])["requests"]
    outcomes = [json.loads(message["content"]) for message in requests[-1]["messages"] if message["role"] == "tool"]
    assert len(outcomes) == 7
    assert all("unavailable to this role" in result["error"] for result in outcomes)
    assert prompts == []


@pytest.mark.parametrize("change", ["body", "retarget", "remove"])
def test_advertised_role_change_fails_before_child_work(tmp_path, run_child, change):
    path = role(tmp_path)
    def mutate():
        if change == "body":
            path.write_text(path.read_text() + "changed")
        elif change == "remove":
            path.unlink()
        else:
            other = tmp_path / "other.md"
            other.write_text(path.read_text())
            path.unlink()
            path.symlink_to(other)
    _, results, _ = run_child([], before_dispatch=mutate)
    assert results[0].is_error
    assert "changed since" in results[0].content["error"]
    assert not any(entry["type"] == "delegation_started" for entry in call_log._read_entries(run_child.parent))


def test_discovery_precedence_invalid_fallback_ambiguity_and_literal_toml(tmp_path, monkeypatch, run_child):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    call_log.reset_session()
    call_log.initialize_storage(tmp_path)
    call_log.start_session(run_child.config)
    directory = home / ".claude" / "agents"
    directory.mkdir(parents=True)
    source = home / "roles" / "researcher.md"
    source.parent.mkdir()
    source.write_text("---\nname: researcher\ndescription: Complete global definition\ntools: Read\n---\nCOMPLETE ROLE BODY")
    (directory / "researcher.md").symlink_to(source)
    invalid = role(tmp_path, tools="Bash(git:*)")
    codex = home / ".codex" / "agents"
    codex.mkdir(parents=True)
    (codex / "researcher.toml").write_text('developer_instructions = "Read and follow /missing/role.md"')
    (directory / "pointer.toml").write_text('developer_instructions = "Read and follow /missing/role.md"')
    ambiguous = tmp_path / ".agents" / "agents"
    (ambiguous / "conflict.md").write_text("invalid")
    (ambiguous / "conflict.toml").write_text('developer_instructions = "conflict"')
    from personal_agent.subagents.definitions import discover
    roles, diagnostics = discover()
    assert roles["researcher"].instructions == "COMPLETE ROLE BODY"
    assert roles["pointer"].instructions == "Read and follow /missing/role.md"
    assert "conflict" not in roles
    assert any("parameterized" in item for item in diagnostics)
    assert any("ambiguous" in item for item in diagnostics)
    (home / "worker-script.json").write_text(json.dumps({"actions": [{"answer": "selected"}]}))
    results = []
    config = run_child.config
    call_log.write_routed_task(1, "Select role", config)
    from tests.conftest import FakeOpenRouterResponse
    from personal_agent.providers import http
    responses = iter([
        {"choices": [{"message": {"tool_calls": [{"id": "delegate", "type": "function", "function": {
            "name": "agent", "arguments": json.dumps({"name": "researcher", "task": "inspect"})}}]}}]},
        {"choices": [{"message": {"content": "done"}}]},
    ])
    captures = []
    def answer(request, timeout=None):
        captures.append(json.loads(request.data))
        response = FakeOpenRouterResponse(next(responses))
        return response.stream() if json.loads(request.data).get("stream") else response
    monkeypatch.setattr(http, "urlopen", answer)
    result = route("Select role", config, on_tool_result=results.append)
    assert result.ok and results[0].content["answer"] == "selected"
    definition = next(tool for tool in captures[0]["tools"] if tool["function"]["name"] == "agent")
    assert "Complete global definition" in definition["function"]["description"]
    assert str(invalid) not in definition["function"]["description"].split("Discovery diagnostics:")[0]


def test_delegated_receipts_deduplicate_report_and_resume(tmp_path, run_child):
    role(tmp_path)
    _, results, _ = run_child([{"calls": [("read_file", {"path": "missing"})]}, {"answer": "done"}])
    child = results[0].content
    assert child["status"] == "completed", child
    assert call_log.total_cost() == 0.5
    receipts = [entry for entry in call_log._read_entries(run_child.parent) if entry["type"] == "delegation_receipt"]
    assert len(receipts) == 2
    assert not call_log.credit_delegated_attempt(child["session_id"], receipts[0])
    assert call_log.total_cost() == 0.5
    report = session_report.render()
    assert "Delegated cost subtotal: $0.5" in report
    assert child["session_id"] in report
    call_log.resume_session(run_child.parent, run_child.config)
    assert call_log.total_cost() == 0


@pytest.mark.parametrize(("decision", "next_mode", "written"), [
    (True, "build", True), (False, "build", False), (True, "plan", False), (False, "auto", False),
])
def test_child_mutation_uses_parent_confirmation_live_mode_and_own_checkpoint(tmp_path, run_child,
                                                                          decision, next_mode, written):
    role(tmp_path, tools="Write, Read")
    mode = ["build"]
    prompts = []
    def confirm(*args):
        prompts.append(args)
        mode[0] = next_mode
        return decision
    _, results, _ = run_child([
        {"calls": [("write", {"path": "result.txt", "content": "child changed"})]},
        {"answer": "handoff"},
    ], mode=lambda: mode[0], confirm=confirm)
    child = results[0].content
    assert child["status"] == "completed", child
    assert len(prompts) == 1
    assert f"researcher / {child['session_id']}" in prompts[0][1]
    assert (tmp_path / "result.txt").exists() == written
    if written:
        from pathlib import Path
        recovery = Path(call_log.session_log_path(child["session_id"])).parent / f"recovery-{child['session_id']}" / "latest.json"
        manifest = json.loads(recovery.read_text())
        assert manifest["session_id"] == child["session_id"]
        assert manifest["outcome"] == "ok"
        assert not (recovery.parent.parent / f"recovery-{run_child.parent}").exists()


def test_child_workspace_traversal_secret_and_global_paths_are_refused(tmp_path, run_child):
    role(tmp_path, tools="Read, Write")
    (tmp_path / ".env").write_text("secret")
    _, results, _ = run_child([
        {"calls": [("read_file", {"path": path}) for path in ("../outside", ".env", "/etc/passwd")]},
        {},
    ])
    child = results[0].content
    assert child["status"] == "completed", child
    request = json.loads(child["answer"])["requests"][-1]
    outcomes = [json.loads(message["content"]) for message in request["messages"] if message["role"] == "tool"]
    assert len(outcomes) == 3 and all("error" in outcome for outcome in outcomes)


def test_repl_child_confirmation_eof_and_usage_are_parent_owned(tmp_path, monkeypatch, route_env, install_fake_urlopen):
    from io import StringIO
    from personal_agent.terminal.repl import run_repl
    role(tmp_path, tools="Write")
    (tmp_path / "worker-script.json").write_text(json.dumps({"actions": [
        {"calls": [("write", {"path": "result.txt", "content": "write"})]}, {"answer": "blocked"},
    ]}))
    monkeypatch.setattr(subagents, "worker_bootstrap", install_scripted_provider)
    delegate(install_fake_urlopen)
    output = StringIO()
    run_repl(load(), input_stream=StringIO("delegate\n"), output_stream=output)
    assert not (tmp_path / "result.txt").exists()
    text = output.getvalue()
    assert "researcher / " in text
    assert "rejected" in text
    assert call_log.total_cost() == 0.5
    assert call_log._read_entries(call_log.current_session_id())[-1]["total_cost"] == 0.5


@contextmanager
def interrupt_on_file(path):
    stopped = threading.Event()
    observed = []
    def interrupt():
        deadline = time.monotonic() + 20
        while not stopped.wait(0.02) and time.monotonic() < deadline:
            if path.exists():
                observed.append(True)
                import _thread
                _thread.interrupt_main()
                return
    thread = threading.Thread(target=interrupt, daemon=True)
    thread.start()
    try:
        yield observed
    finally:
        stopped.set()
        thread.join(timeout=1)


@pytest.mark.parametrize("operation", ["provider", "foreground", "background"])
def test_interrupt_reaps_worker_and_child_groups_preserving_parent_jobs(tmp_path, run_child, operation):
    registry.enable_shell_tool()
    role(tmp_path, tools="Bash")
    parent_job = jobs.start(shell._resolve_shell(), "sleep 60")
    ready = tmp_path / "child-ready"
    child_pid = tmp_path / "child-pid"
    if operation == "provider":
        actions = [{"wait": str(ready)}]
    elif operation == "foreground":
        actions = [{"calls": [("shell", {"command": f"echo $$ > '{child_pid}'; touch '{ready}'; sleep 60"})]}]
    else:
        actions = [{"calls": [("shell", {"command": f"echo $$ > '{child_pid}'; sleep 60", "background": True})]},
                   {"wait": str(ready)}]
    try:
        with interrupt_on_file(ready) as observed:
            with pytest.raises(KeyboardInterrupt) as interrupted:
                run_child(actions, mode="auto")
        assert observed
        state = interrupted.value.continuation
        outcomes = [message for message in state["messages"] if message["role"] == "tool_result"]
        assert len(outcomes) == 1 and outcomes[0]["content"]["error"] == "Subagent interrupted"
        child = outcomes[0]["content"]["session_id"]
        finished = [entry for entry in call_log._read_entries(run_child.parent) if entry["type"] == "delegation_finished"]
        assert finished[-1]["status"] == "interrupted"
        entries = call_log._read_entries(child)
        assert any(entry["type"] == "turn_end" and entry["status"] == "interrupted" for entry in entries)
        assert entries[-1]["type"] == "session_end"
        if child_pid.exists():
            with pytest.raises(ProcessLookupError):
                os.kill(int(child_pid.read_text()), 0)
        assert jobs.status(parent_job)["state"] == "running"
        _, results, _ = run_child([{"answer": "fresh after interrupt"}])
        assert results[0].content["session_id"] != child
        assert results[0].content["answer"] == "fresh after interrupt"
    finally:
        jobs.stop(parent_job)


def test_crashed_worker_cleans_known_background_groups_and_releases_guard(tmp_path, run_child):
    registry.enable_shell_tool()
    role(tmp_path, tools="Bash")
    pid_file = tmp_path / "job-pid"
    _, results, _ = run_child([
        {"calls": [("shell", {"command": f"echo $$ > '{pid_file}'; sleep 60", "background": True})]},
        {"crash": 7},
    ], mode="auto")
    failed = results[0].content
    assert failed["status"] == "error"
    assert failed["session_id"]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(int(pid_file.read_text()), 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail("child Background Job survived worker crash")
    finish = [entry for entry in call_log._read_entries(run_child.parent) if entry["type"] == "delegation_finished"][-1]
    assert finish["coverage"] == "incomplete"
    assert call_log.total_cost() == 0.25
    _, results, _ = run_child([{"answer": "fresh after failure"}])
    assert results[0].content["status"] == "completed"
    assert results[0].content["session_id"] != failed["session_id"]


@pytest.mark.parametrize(("name", "skills", "allowed", "handoff"), [
    ("sdd-planner", ["sdd-codebase-design", "sdd-to-spec", "sdd-to-tickets"],
     {"read_file", "write", "edit", "search_text", "list_files", "shell", "job_status", "job_stop", "skill", "todo", "webfetch"},
     "status: ready\nfeature: smoke\ncoverage_ok: true"),
    ("sdd-implementer", ["sdd-implement", "tdd"],
     {"read_file", "write", "edit", "search_text", "list_files", "shell", "job_status", "job_stop", "skill", "todo"},
     "status: ready_for_review\nbase_sha: abc\nhead_sha: def"),
    ("sdd-reviewer", ["sdd-security-review", "sdd-code-review", "sdd-diagnosing-bugs"],
     {"read_file", "search_text", "list_files", "shell", "job_status", "job_stop", "skill", "todo"},
     "status: approved\nreviewed_range: abc..def\nfindings: []"),
])
def test_three_sdd_roles_load_skills_and_resources_in_real_fresh_worker(tmp_path, monkeypatch, route_env,
                                                                     install_fake_urlopen, name, skills, allowed, handoff):
    home = tmp_path / "home"
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("HOME", str(home))
    configure_workspace(root)
    global_roles = home / ".claude" / "agents"
    global_roles.mkdir(parents=True)
    definitions = home / "roles"
    definitions.mkdir()
    fixture = Path(__file__).parent / "fixtures" / "subagents" / f"{name}.md"
    target = definitions / f"{name}.md"
    target.write_bytes(fixture.read_bytes())
    (global_roles / target.name).symlink_to(target)
    pointers = home / ".codex" / "agents"
    pointers.mkdir(parents=True)
    (pointers / f"{name}.toml").write_text('developer_instructions = "Read and follow /unavailable/role.md"')
    directory = home / ".agents" / "skills"
    directory.mkdir(parents=True)
    for skill_name in skills:
        source = home / ".codex" / "skills" / skill_name
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text(f"---\nname: {skill_name}\ndescription: Required dependency\n---\n"
                                           f"Instructions for {skill_name}; read support/rules.md.")
        (source / "support").mkdir()
        (source / "support" / "rules.md").write_text(f"Bounded supporting rules for {skill_name}")
        (directory / skill_name).symlink_to(source)
    actions = [{"assert_tools": list(allowed), "assert_system": [f"# SDD {name[4:].title()}"],
                "calls": [("skill", {"names": skills})]},
               {"calls": [("skill", {"name": skill, "path": "support/rules.md"}) for skill in skills]},
               {"answer": handoff}]
    (home / "worker-script.json").write_text(json.dumps({"actions": actions}))
    monkeypatch.setattr(subagents, "worker_bootstrap", install_scripted_provider)
    registry.enable_shell_tool()
    call_log.reset_session()
    call_log.initialize_storage(root)
    config = load()
    parent = call_log.start_session(config)
    call_log.write_routed_task(1, "SDD smoke", config)
    delegate(install_fake_urlopen, name)
    results = []
    from personal_agent.workspace_skills import Skill
    routed = route("SDD smoke", config, skills=(Skill("sdd-main", "parent orchestrator", "PARENT ORCHESTRATOR", b"test"),),
                   on_tool_result=lambda result: results.append(result) if result.name == "agent" else None)
    child = results[0].content
    assert routed.ok and child["status"] == "completed", child
    assert child["answer"] == handoff
    entries = call_log._read_entries(child["session_id"])
    attempts = [entry for entry in entries if entry["type"] == "attempt"]
    assert len(attempts) == 3
    results = [entry["result"] for entry in entries if entry["type"] == "tool_execution" and entry["ok"]]
    assert len(results) == len(skills) + 1
    assert all(f"Bounded supporting rules for {skill}" in json.dumps(results) for skill in skills)
    assert call_log.current_session_id() == parent
    assert call_log.total_cost() == 0.75


@pytest.mark.parametrize("source", ["oversized", "nul", "encoding", "directory", "fifo", "escape", "loop", "name", "yaml"])
def test_invalid_definitions_are_diagnostic_and_never_start_workers(tmp_path, run_child, source):
    path = role(tmp_path)
    original = path.read_bytes()
    if source == "oversized":
        path.write_bytes(original + b"x" * (32 * 1024))
    elif source == "nul":
        path.write_bytes(original + b"\x00")
    elif source == "encoding":
        path.write_bytes(original + b"\xff")
    elif source == "directory":
        path.unlink()
        path.mkdir()
    elif source == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif source == "escape":
        path.unlink()
        path.symlink_to("/etc/passwd")
    elif source == "loop":
        path.unlink()
        path.symlink_to(path)
    elif source == "name":
        path.write_bytes(original.replace(b"name: researcher", b"name: mismatch"))
    else:
        path.write_text("---\n[bad yaml\n---\nrole")
    _, results, calls = run_child([])
    assert results[0].is_error
    assert "unavailable" in results[0].content["error"]
    advertised = json.loads(calls[0]["request"].data)["tools"]
    definition = next(item["function"] for item in advertised if item["function"]["name"] == "agent")
    assert "Discovery diagnostics:" in definition["description"]
    assert not any(entry["type"] == "delegation_started" for entry in call_log._read_entries(run_child.parent))


def test_child_route_and_resolved_capacity_survive_changed_settings_and_retry(tmp_path, run_child):
    registry.enable_shell_tool()
    role(tmp_path, tools="Bash")
    _, results, _ = run_child([
        {"error": "temporary connection failure"},
        {"assert_output": 16000, "assert_tools": ["shell", "job_status", "job_stop"],
         "calls": [("job_status", {"id": 999})]},
        {"assert_output": 16000, "answer": "immutable route"},
    ], change_settings=True)
    child = results[0].content
    assert child["status"] == "completed", child
    attempts = [entry for entry in call_log._read_entries(child["session_id"]) if entry["type"] == "attempt"]
    assert len(attempts) == 3 and all(entry["model"] == "vendor/test-model" for entry in attempts)
    assert call_log.total_cost() == 0.5
    assert "coverage: 2/3 known, 1 missing" in session_report.render()


def test_interrupted_child_confirmation_keeps_terminal_outcome(tmp_path, run_child):
    role(tmp_path, tools="Write")
    def interrupt(*args):
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt) as interrupted:
        run_child([{"calls": [("write", {"path": "result.txt", "content": "no"})]}], confirm=interrupt)
    results = [message for message in interrupted.value.continuation["messages"] if message["role"] == "tool_result"]
    assert results[0]["content"]["error"] == "Subagent interrupted"
    assert not (tmp_path / "result.txt").exists()


def test_spawn_failure_is_explicit_and_next_delegation_starts_fresh(tmp_path, run_child, monkeypatch):
    import multiprocessing
    role(tmp_path)
    def fail(process):
        raise OSError("spawn refused")
    with monkeypatch.context() as patch:
        patch.setattr(multiprocessing.get_context("spawn").Process, "start", fail)
        _, results, _ = run_child([])
    failed = results[0].content
    assert failed["status"] == "error" and "spawn refused" in failed["error"]
    _, results, _ = run_child([{"answer": "after spawn failure"}])
    assert results[0].content["status"] == "completed"
    assert results[0].content["session_id"] != failed["session_id"]


def test_parent_channel_loss_stops_worker_and_owned_jobs(tmp_path, run_child, monkeypatch):
    import multiprocessing
    context = multiprocessing.get_context("spawn")
    original = context.Pipe
    connections = []
    def pipe(*args, **kwargs):
        pair = original(*args, **kwargs)
        connections.append(pair)
        return pair
    monkeypatch.setattr(context, "Pipe", pipe)
    registry.enable_shell_tool()
    role(tmp_path, tools="Bash")
    ready = tmp_path / "ready"
    child_pid = tmp_path / "owned-job"
    stopped = threading.Event()
    def disconnect():
        deadline = time.monotonic() + 20
        while not stopped.wait(0.02) and time.monotonic() < deadline:
            if ready.exists() and len(connections) == 2:
                connections[1][0].close()
                return
    thread = threading.Thread(target=disconnect, daemon=True)
    thread.start()
    try:
        _, results, _ = run_child([
            {"calls": [("shell", {"command": f"echo $$ > '{child_pid}'; sleep 60", "background": True})]},
            {"wait": str(ready)},
        ], mode="auto")
        child = results[0].content
        assert child["status"] == "error", child
        with pytest.raises(ProcessLookupError):
            os.kill(int(child_pid.read_text()), 0)
        assert any(entry["type"] == "turn_end" and entry["status"] == "interrupted"
                   for entry in call_log._read_entries(child["session_id"]))
    finally:
        stopped.set()
        thread.join(timeout=1)


def test_batch_delegations_finish_in_order_with_fresh_todo_and_process_state(tmp_path, monkeypatch, route_env,
                                                                          install_fake_urlopen):
    configure_workspace(tmp_path)
    role(tmp_path, tools="TodoWrite")
    actions = [{"calls": [("todo", {"todos": [{"content": "CHILD TODO", "status": "pending"}]})]}, {}]
    (tmp_path / "worker-script.json").write_text(json.dumps({"actions": actions}))
    monkeypatch.setattr(subagents, "worker_bootstrap", install_scripted_provider)
    config = load()
    call_log.start_session(config)
    call_log.write_routed_task(1, "two delegates", config)
    install_fake_urlopen([{"tool_calls": [
        {"id": f"delegate-{index}", "name": "agent", "arguments": {"name": "researcher", "task": f"task {index}"}}
        for index in (1, 2)]}, "parent done"])
    results = []
    routed = route("two delegates", config, todos=[{"content": "PARENT TODO", "status": "pending"}],
                   on_tool_result=lambda result: results.append(result) if result.name == "agent" else None)
    assert routed.ok
    assert [result.id for result in results] == ["delegate-1", "delegate-2"]
    assert len({result.content["session_id"] for result in results}) == 2
    for result in results:
        child = json.loads(result.content["answer"])
        assert child["pid"] != os.getpid()
        initial = json.dumps(child["requests"][0])
        assert "CHILD TODO" not in initial and "PARENT TODO" not in initial
        assert "CHILD TODO" in json.dumps(child["requests"][1])
    records = [entry["type"] for entry in call_log._read_entries(call_log.current_session_id())
               if entry["type"] in {"delegation_started", "delegation_finished"}]
    assert records == ["delegation_started", "delegation_finished", "delegation_started", "delegation_finished"]


@pytest.mark.parametrize("cost", [None, "invalid", -1, float("nan"), float("inf")])
def test_unknown_or_invalid_child_cost_never_becomes_zero_coverage(tmp_path, run_child, cost):
    role(tmp_path)
    _, results, _ = run_child([{"answer": "done", "usage": {"cost": cost}}])
    child = results[0].content
    assert child["status"] == "completed", child
    assert call_log.total_cost() == 0
    report = session_report.render()
    expected = "1 missing, 0 invalid" if cost is None else "0 missing, 1 invalid"
    assert "coverage: 0/1 known, " + expected in report


def test_handoff_truncation_preserves_full_child_conversation_and_rejects_bad_origin_metadata(tmp_path, run_child):
    role(tmp_path)
    answer = "x" * (40 * 1024)
    _, results, _ = run_child([{"answer": answer}])
    child = results[0].content
    assert child["status"] == "completed"
    assert len(child["answer"].encode()) <= 32 * 1024
    assert f"full answer in child Session {child['session_id']}" in child["answer"]
    entries = call_log._read_entries(child["session_id"])
    assert next(entry for entry in entries if entry["type"] == "attempt")["answer"] == answer
    turns, _, _, _ = call_log.load_conversation(child["session_id"])
    assert turns[-1][-1]["content"] == answer
    target = Path(call_log.session_log_path(child["session_id"]))
    original = target.read_text()
    for key, value in (("session_kind", "fork"), ("parent_session_id", child["session_id"]),
                       ("parent_execution", {}), ("parent_tool_call_id", ""), ("agent_name", "../escape")):
        changed = [dict(entry) for entry in entries]
        changed[0][key] = value
        target.write_text("".join(json.dumps(entry) + "\n" for entry in changed))
        with pytest.raises(call_log.ResumeError):
            call_log.load_conversation(child["session_id"])
        target.write_text(original)


def test_child_evidence_failure_stops_dependent_parent_dispatch(tmp_path, monkeypatch, route_env, install_fake_urlopen):
    configure_workspace(tmp_path)
    role(tmp_path)
    (tmp_path / "worker-script.json").write_text(json.dumps({"actions": [{"answer": "not accepted"}],
                                                           "fail_evidence": "turn_end"}))
    monkeypatch.setattr(subagents, "worker_bootstrap", install_scripted_provider)
    config = load()
    parent = call_log.start_session(config)
    call_log.write_routed_task(1, "delegate", config)
    calls = delegate(install_fake_urlopen)
    with pytest.raises(call_log.PersistenceError, match="evidence persistence failed"):
        route("delegate", config)
    assert len(calls) == 1
    finish = [entry for entry in call_log._read_entries(parent) if entry["type"] == "delegation_finished"][-1]
    assert finish["coverage"] == "incomplete" and finish["status"] == "error"
    import multiprocessing
    assert not multiprocessing.active_children()


def test_parent_receipt_failure_stops_child_jobs_and_dependent_dispatch(tmp_path, monkeypatch, route_env,
                                                                     install_fake_urlopen):
    configure_workspace(tmp_path)
    registry.enable_shell_tool()
    role(tmp_path, tools="Bash")
    pidfile = tmp_path / "job-pid"
    (tmp_path / "worker-script.json").write_text(json.dumps({"actions": [
        {"calls": [("shell", {"command": f"echo $$ > '{pidfile}'; sleep 60", "background": True})]},
        {"answer": "not accepted"},
    ]}))
    monkeypatch.setattr(subagents, "worker_bootstrap", install_scripted_provider)
    config = load()
    call_log.start_session(config)
    call_log.write_routed_task(1, "delegate", config)
    original = call_log._write_line
    receipts = [0]
    def write(entry, **kwargs):
        if entry["type"] == "delegation_receipt":
            receipts[0] += 1
            if receipts[0] > 1:
                raise OSError("injected parent receipt failure")
        return original(entry, **kwargs)
    monkeypatch.setattr(call_log, "_write_line", write)
    calls = delegate(install_fake_urlopen)
    with pytest.raises(call_log.PersistenceError, match="delegated evidence"):
        route("delegate", config, mode="auto")
    assert len(calls) == 1
    import signal
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)
    import multiprocessing
    assert not multiprocessing.active_children()


def test_real_child_audit_is_distinct_and_redacts_credentials(tmp_path, monkeypatch, route_env, install_fake_urlopen):
    from io import StringIO
    from personal_agent.terminal.repl import run_repl
    role(tmp_path, tools="Read")
    (tmp_path / "worker-script.json").write_text(json.dumps({"actions": [{"answer": "test-key"}]}))
    monkeypatch.setattr(subagents, "worker_bootstrap", install_scripted_provider)
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    delegate(install_fake_urlopen)
    output = StringIO()
    run_repl(load(), input_stream=StringIO("delegate\n/exit\n"), output_stream=output)
    parent = call_log.current_session_id()
    entries = call_log._read_entries(parent)
    child = next(entry["child_session_id"] for entry in entries if entry["type"] == "delegation_started")
    for sid in (parent, child):
        detail = Path(call_log.detail_path(sid)).read_text()
        assert "test-key" not in detail
        rows = [json.loads(line) for line in detail.splitlines()]
        assert len([entry for entry in rows if entry["type"] == "run_start"]) == 1
        assert len([entry for entry in rows if entry["type"] == "run_end"]) == 1
        assert all(entry["session_id"] == sid for entry in rows)
    assert "test-key" not in output.getvalue()


def test_repl_worker_waits_release_busy_input_before_strong_confirmation(tmp_path, monkeypatch, route_env,
                                                                      install_fake_urlopen):
    from io import StringIO
    from personal_agent.terminal.repl import run_repl
    registry.enable_shell_tool()
    role(tmp_path, tools="Bash")
    (tmp_path / "worker-script.json").write_text(json.dumps({"actions": [
        {"calls": [("shell", {"command": "printf 'printf safe' | bash"})]}, {"answer": "done"},
    ]}))
    monkeypatch.setattr(subagents, "worker_bootstrap", install_scripted_provider)
    class Box:
        def __init__(self):
            self.lines = iter(["/mode auto", "first", "second", "/exit"])
            self.answers = iter(["y", "yes"])
            self.busy = False
            self.waits = 0
        def read(self):
            return next(self.lines)
        def terminal_size(self):
            from types import SimpleNamespace
            return SimpleNamespace(columns=120, rows=40)
        def ask(self, prompt):
            assert not self.busy
            assert "Type 'yes'" in prompt
            return next(self.answers)
        def run_busy(self, operation):
            assert not self.busy
            self.waits += 1
            self.busy = True
            try:
                return operation()
            finally:
                self.busy = False
    box = Box()
    tool = {"tool_calls": [{"id": "delegate", "name": "agent", "arguments": {"name": "researcher", "task": "inspect"}}]}
    install_fake_urlopen([tool, "done", tool, "done"])
    output = StringIO()
    run_repl(load(), input_box=box, output_stream=output)
    children = [entry["child_session_id"] for entry in call_log._read_entries(call_log.current_session_id())
                if entry["type"] == "delegation_started"]
    first, second = [[entry for entry in call_log._read_entries(sid) if entry["type"] == "tool_execution"][0]
                     for sid in children]
    assert first["ok"] is False
    assert second["ok"] is True and second["result"]["stdout"] == "safe"
    assert box.waits > 4
    assert output.getvalue().count("Dangerous command:") == 2


def test_resume_last_and_previous_select_parent_sessions_not_children(tmp_path, monkeypatch, route_env,
                                                                     install_fake_urlopen):
    from io import StringIO
    from personal_agent import session_logs
    from personal_agent.terminal.repl import run_repl
    role(tmp_path)
    (tmp_path / "worker-script.json").write_text(json.dumps({"actions": [{"answer": "child handoff"}]}))
    monkeypatch.setattr(subagents, "worker_bootstrap", install_scripted_provider)
    install_fake_urlopen(["first answer", {"tool_calls": [
        {"id": "delegate", "name": "agent", "arguments": {"name": "researcher", "task": "inspect"}}]}, "parent done"])
    run_repl(load(), input_stream=StringIO("hello\n/exit\n"), output_stream=StringIO())
    first = call_log.current_session_id()
    run_repl(load(), input_stream=StringIO("delegate\n/exit\n"), output_stream=StringIO())
    parent = call_log.current_session_id()
    child = next(entry["child_session_id"] for entry in call_log._read_entries(parent)
                 if entry["type"] == "delegation_started")
    assert call_log._read_entries(child)[0]["session_kind"] == "subagent"
    assert call_log.resolve_resume_session("last") == parent
    assert call_log.resolve_resume_session(child) == child
    previous = json.dumps(session_logs.execute({"action": "read", "session": "previous"}, max_bytes=65536))
    assert f"session={first}" in previous and child not in previous


def test_child_change_to_parent_file_refuses_parent_recovery_without_merging_images(tmp_path, monkeypatch, route_env,
                                                                                   install_fake_urlopen):
    from io import StringIO
    from personal_agent.terminal.repl import run_repl
    role(tmp_path, tools="Write")
    (tmp_path / "worker-script.json").write_text(json.dumps({"actions": [
        {"calls": [("write", {"path": "shared.txt", "content": "child"})]}, {"answer": "handoff"}]}))
    monkeypatch.setattr(subagents, "worker_bootstrap", install_scripted_provider)
    install_fake_urlopen([
        {"tool_calls": [{"id": "change", "name": "write", "arguments": {"path": "shared.txt", "content": "parent"}}]},
        "parent wrote",
        {"tool_calls": [{"id": "delegate", "name": "agent", "arguments": {"name": "researcher", "task": "edit"}}]},
        "parent done",
    ])
    output = StringIO()
    run_repl(load(), input_stream=StringIO("change\ny\ndelegate\ny\n/recover\n/exit\n"), output_stream=output)
    assert (tmp_path / "shared.txt").read_text() == "child"
    assert "conflicts; nothing restored" in output.getvalue()
    parent = call_log.current_session_id()
    assert not any(entry["type"] == "file_recovery_started" for entry in call_log._read_entries(parent))
    child = next(entry["child_session_id"] for entry in call_log._read_entries(parent)
                 if entry["type"] == "delegation_started")
    storage = Path(call_log.session_log_path(parent)).parent
    images = {}
    for sid in (parent, child):
        manifest = json.loads((storage / f"recovery-{sid}" / "latest.json").read_text())
        assert manifest["session_id"] == sid and len(manifest["entries"]) == 1
        images[sid] = manifest["entries"][0]
    assert images[parent]["before"]["exists"] is False
    assert images[child]["before"] == images[parent]["after"]


@contextmanager
def interrupt_twice_on_file(path, delay):
    stopped = threading.Event()
    def interrupt():
        import _thread
        deadline = time.monotonic() + 20
        while not stopped.wait(0.02) and time.monotonic() < deadline:
            if path.exists():
                _thread.interrupt_main()
                if not stopped.wait(delay):
                    _thread.interrupt_main()
                return
    thread = threading.Thread(target=interrupt, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1)


@pytest.mark.parametrize("second_interrupt", [False, True])
def test_forced_shutdown_kills_interrupt_immune_worker_and_completes_cleanup(tmp_path, run_child, monkeypatch,
                                                                            second_interrupt):
    monkeypatch.setattr(subagents, "GRACE_SECONDS", 30 if second_interrupt else 0.5)
    registry.enable_shell_tool()
    role(tmp_path, tools="Bash")
    ready = tmp_path / "worker-pid"
    job = tmp_path / "job-pid"
    actions = [{"calls": [("shell", {"command": f"echo $$ > '{job}'; sleep 60", "background": True})]},
               {"wait": str(ready), "ignore_sigint": True}]
    started = time.monotonic()
    with interrupt_twice_on_file(ready, 0.5 if second_interrupt else 60):
        with pytest.raises(KeyboardInterrupt) as interrupted:
            run_child(actions, mode="auto")
    assert time.monotonic() - started < 20
    import signal
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
    outcomes = [message for message in interrupted.value.continuation["messages"] if message["role"] == "tool_result"]
    assert len(outcomes) == 1 and outcomes[0]["content"]["error"] == "Subagent interrupted"
    for pid in (ready, job):
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid.read_text()), 0)
    finished = [entry for entry in call_log._read_entries(run_child.parent) if entry["type"] == "delegation_finished"]
    assert finished[-1]["status"] == "interrupted" and finished[-1]["coverage"] == "incomplete"
    import multiprocessing
    assert not multiprocessing.active_children()
    _, results, _ = run_child([{"answer": "fresh after forced shutdown"}])
    assert results[0].content["answer"] == "fresh after forced shutdown"


def test_concurrent_and_reentrant_delegation_is_rejected_and_guard_released(tmp_path, run_child, monkeypatch):
    from personal_agent.providers.contract import ToolCall
    from personal_agent.tools.builtins import ToolExecutionError
    role(tmp_path, tools="Write")
    active = []
    original = subagents.Delegation.execute
    def execute(self, call):
        active.append(self)
        return original(self, call)
    monkeypatch.setattr(subagents.Delegation, "execute", execute)
    nested = []
    def confirm(*args):
        try:
            active[0].execute(ToolCall("nested", "agent", {"name": "researcher", "task": "nested"}))
        except ToolExecutionError as exc:
            nested.append(str(exc))
        return False
    _, results, _ = run_child([{"calls": [("write", {"path": "x.txt", "content": "x"})]}, {"answer": "done"}],
                              confirm=confirm)
    assert nested == ["another Subagent is already active"]
    assert results[0].content["status"] == "completed"
    held, release = threading.Event(), threading.Event()
    def hold():
        with subagents._guard:
            held.set()
            release.wait(20)
    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert held.wait(5)
        _, results, _ = run_child([])
    finally:
        release.set()
        holder.join()
    assert results[0].is_error and "already active" in results[0].content["error"]
    started = [entry for entry in call_log._read_entries(run_child.parent) if entry["type"] == "delegation_started"]
    assert len(started) == 1
    _, results, _ = run_child([{"answer": "after concurrent rejection"}])
    assert results[0].content["answer"] == "after concurrent rejection"


@pytest.mark.parametrize("suffix", ["md", "toml"])
def test_role_model_metadata_never_changes_child_route(tmp_path, run_child, suffix):
    if suffix == "md":
        path = role(tmp_path)
        path.write_text(path.read_text().replace("tools: Read\n", "tools: Read\nmodel: other-vendor/other-model\n"))
    else:
        directory = tmp_path / ".agents" / "agents"
        directory.mkdir(parents=True)
        (directory / "researcher.toml").write_text(
            'name = "researcher"\ndescription = "Research"\nmodel = "other-vendor/other-model"\n'
            'model_provider = "other-provider"\ndeveloper_instructions = "Independent role instructions."\n')
    _, results, _ = run_child([{}])
    child = results[0].content
    assert child["status"] == "completed", child
    assert json.loads(child["answer"])["requests"][0]["model"] == run_child.config.model
    attempts = [entry for entry in call_log._read_entries(child["session_id"]) if entry["type"] == "attempt"]
    assert attempts and all(entry["model"] == run_child.config.model and entry["provider"] == run_child.config.provider
                            for entry in attempts)


def test_parent_disabled_capabilities_refuse_forged_calls_even_when_role_allows_them(tmp_path, run_child):
    role(tmp_path, tools="Bash, WebSearch, mcp_list_resources, mcp_read_resource, agent, question")
    marker = tmp_path / "marker"
    prompts = []
    calls = [("shell", {"command": f"touch '{marker}'"}), ("websearch", {"query": "x"}),
             ("mcp_list_resources", {}), ("mcp_read_resource", {"uri": "file:///x"}),
             ("agent", {"name": "researcher", "task": "nested"}), ("question", {"questions": []})]
    _, results, _ = run_child([{"assert_tools": [], "calls": calls}, {}], mode="auto",
                              confirm=lambda *args: prompts.append(args) or True)
    child = results[0].content
    assert child["status"] == "completed", child
    request = json.loads(child["answer"])["requests"][-1]
    outcomes = [json.loads(message["content"]) for message in request["messages"] if message["role"] == "tool"]
    assert len(outcomes) == len(calls)
    assert all("unavailable to this role" in outcome["error"] for outcome in outcomes)
    assert prompts == [] and not marker.exists()
    executions = [entry for entry in call_log._read_entries(child["session_id"]) if entry["type"] == "tool_execution"]
    assert all(not entry["ok"] for entry in executions)


def test_child_prompt_mentions_shell_and_questions_only_when_offered():
    from personal_agent.routing import router
    tool = lambda name: type("T", (), {"name": name})()
    child = router._build_system_prompt(tools=[tool("write")], mode="auto")
    assert "shell" not in child and "Ask only" not in child
    assert child.count("do it with your Tools: write the files. Do not hand code back") == 1
    parent = router._build_system_prompt(tools=[tool("write"), tool("shell"), tool("question")], mode="auto")
    assert "verify them with shell when possible" in parent and "Ask only when" in parent
    assert "Dangerous Command rules" in parent


@pytest.mark.parametrize("finish_fails", [False, True])
def test_reconcile_persistence_failure_records_incomplete_finish_and_releases_state(tmp_path, run_child, monkeypatch,
                                                                                    finish_fails):
    import multiprocessing
    import signal
    role(tmp_path)
    def fail(self, sid, attribution):
        raise call_log.PersistenceError("injected reconcile failure")
    monkeypatch.setattr(subagents.Delegation, "_reconcile", fail)
    if finish_fails:
        original = call_log.write_delegation
        def write(phase, **fields):
            if phase == "finished":
                raise call_log.PersistenceError("injected finish failure")
            return original(phase, **fields)
        monkeypatch.setattr(call_log, "write_delegation", write)
    with pytest.raises(call_log.PersistenceError, match="injected reconcile failure"):
        run_child([{"answer": "done"}])
    finished = [entry for entry in call_log._read_entries(run_child.parent) if entry["type"] == "delegation_finished"]
    if finish_fails:
        assert finished == []
    else:
        assert finished[-1]["coverage"] == "incomplete" and finished[-1]["status"] == "completed"
    assert subagents._guard.acquire(blocking=False)
    subagents._guard.release()
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
    assert not multiprocessing.active_children()


@pytest.mark.parametrize("moment", ["join", "cleanup"])
def test_interrupt_after_completed_handoff_keeps_the_answer_as_interrupted_partial_result(tmp_path, run_child,
                                                                                          monkeypatch, moment):
    import multiprocessing
    import multiprocessing.process
    import signal
    role(tmp_path)
    if moment == "join":
        original_join = multiprocessing.process.BaseProcess.join
        raised = []
        def join(self, timeout=None):
            if timeout == 3 and not raised:
                raised.append(True)
                raise KeyboardInterrupt()
            return original_join(self, timeout)
        monkeypatch.setattr(multiprocessing.process.BaseProcess, "join", join)
    else:
        original_stop = subagents.Delegation._stop_groups
        def stop(groups):
            os.kill(os.getpid(), signal.SIGINT)
            time.sleep(0.05)
            original_stop(groups)
        monkeypatch.setattr(subagents.Delegation, "_stop_groups", staticmethod(stop))
    with pytest.raises(KeyboardInterrupt) as interrupted:
        run_child([{"answer": "finished before interrupt"}])
    outcomes = [message for message in interrupted.value.continuation["messages"] if message["role"] == "tool_result"]
    assert len(outcomes) == 1 and outcomes[0]["is_error"]
    assert outcomes[0]["content"]["error"] == "Subagent interrupted after completing its handoff"
    assert outcomes[0]["content"]["answer"] == "finished before interrupt"
    finished = [entry for entry in call_log._read_entries(run_child.parent) if entry["type"] == "delegation_finished"]
    assert finished[-1]["status"] == "interrupted"
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
    assert not multiprocessing.active_children()


def test_stale_parent_reply_is_discarded_and_child_completes_with_turn_end(tmp_path, run_child, monkeypatch):
    role(tmp_path)
    original = subagents.send
    stale = []
    def send(channel, message):
        if isinstance(message, dict) and "seq" in message and not stale:
            stale.append(True)
            original(channel, {"seq": -1, "value": "stale"})
        return original(channel, message)
    monkeypatch.setattr(subagents, "send", send)
    _, results, _ = run_child([{"answer": "survived stale reply"}])
    child = results[0].content
    assert stale and child["status"] == "completed" and child["answer"] == "survived stale reply"
    types = [entry["type"] for entry in call_log._read_entries(child["session_id"])]
    assert "turn_end" in types and types[-1] == "session_end"
    assert call_log.total_cost() == 0.25


def test_failed_worker_cleanup_step_still_writes_turn_end_and_session_end(tmp_path, monkeypatch, route_env,
                                                                          install_fake_urlopen):
    import multiprocessing
    configure_workspace(tmp_path)
    role(tmp_path)
    (tmp_path / "worker-script.json").write_text(json.dumps({"actions": [{"answer": "done"}], "fail_stop_all": True}))
    monkeypatch.setattr(subagents, "worker_bootstrap", install_scripted_provider)
    config = load()
    parent = call_log.start_session(config)
    call_log.write_routed_task(1, "delegate", config)
    delegate(install_fake_urlopen)
    with pytest.raises(call_log.PersistenceError, match="evidence persistence failed"):
        route("delegate", config)
    started = next(entry for entry in call_log._read_entries(parent) if entry["type"] == "delegation_started")
    types = [entry["type"] for entry in call_log._read_entries(started["child_session_id"])]
    assert "turn_end" in types and types[-1] == "session_end"
    assert not multiprocessing.active_children()


def test_agent_tool_is_not_offered_without_roles_or_diagnostics(tmp_path, run_child):
    _, results, calls = run_child([])
    advertised = {item["function"]["name"] for item in json.loads(calls[0]["request"].data)["tools"]}
    assert "agent" not in advertised
    assert results[0].is_error and "unavailable" in results[0].content["error"]


def test_invalid_yaml_diagnostic_names_file_and_line_without_definition_content(tmp_path, run_child):
    path = role(tmp_path)
    path.write_text("---\nname: researcher\ndescription: SNIPPET_MARKER: broken: yaml\n---\nrole body\n")
    _, _, calls = run_child([])
    advertised = json.loads(calls[0]["request"].data)["tools"]
    description = next(item["function"] for item in advertised if item["function"]["name"] == "agent")["description"]
    assert "researcher.md: invalid YAML (ScannerError at line" in description
    assert "SNIPPET_MARKER" not in description


@pytest.mark.parametrize("origin", ["workspace", "global"])
@pytest.mark.parametrize("location", [".claude", ".codex"])
def test_inaccessible_agent_location_is_diagnostic_without_blocking_tasks(
    tmp_path, route_env, install_fake_urlopen, origin, location
):
    from io import StringIO
    from personal_agent.terminal.repl import run_repl

    root = tmp_path / "workspace"
    root.mkdir()
    blocked = (root if origin == "workspace" else Path.home()) / location
    blocked.mkdir()
    calls = install_fake_urlopen("Task completed")
    output = StringIO()
    blocked.chmod(0)
    try:
        run_repl(load(), workspace_root=root, input_stream=StringIO("Hello\nexit\n"), output_stream=output)
    finally:
        blocked.chmod(0o700)

    assert "Task completed" in output.getvalue()
    assert len(calls) == 1
    advertised = json.loads(calls[0]["request"].data)["tools"]
    description = next(item["function"]["description"] for item in advertised if item["function"]["name"] == "agent")
    assert f"{origin}/{location}/agents:" in description
    assert "Permission denied" in description
