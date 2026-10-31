import json
import os
import stat
from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from personal_agent import call_log, project_instructions
from personal_agent import file_recovery
from personal_agent.__main__ import main
from personal_agent.terminal.repl import run_repl
from personal_agent.routing import runtime_config
from personal_agent.tools import registry, workspace
from personal_agent.providers.contract import ToolCall
from tests.fakes import FakeOpenRouterResponse


def tool(name, arguments, identifier="change"):
    return {"tool_calls": [{"id": identifier, "name": name, "arguments": arguments}]}


def entries():
    return [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]


def test_recover_created_file_without_changing_conversation(route_env, tmp_path, install_fake_urlopen):
    calls = install_fake_urlopen([tool("write", {"path": "created.txt", "content": "new\r\n"}), "done"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=["create", "yes", "/recover", "yes", "exit"], output_stream=output)

    assert not (tmp_path / "created.txt").exists()
    assert len(calls) == 2
    assert len(call_log.load_conversation(call_log.current_session_id())[0]) == 1
    assert "Recovered" in output.getvalue()
    assert [row["type"] for row in entries() if row["type"].startswith("file_recovery_")] == [
        "file_recovery_started", "file_recovery_finished"]


def test_patch_and_repeated_edit_restore_exact_bytes_modes_after_resume(
    route_env, tmp_path, monkeypatch, install_fake_urlopen
):
    edited = tmp_path / "edited.txt"
    deleted = tmp_path / "deleted.txt"
    edited.write_bytes(b"original\r\n")
    deleted.write_bytes(b"gone\r\n")
    edited.chmod(0o751)
    deleted.chmod(0o640)
    calls = install_fake_urlopen([
        tool("edit", {"path": "edited.txt", "old_string": "original", "new_string": "middle"}),
        tool("apply_patch", {"patch": "*** Begin Patch\n*** Update File: edited.txt\n@@\n-middle\n+final\n*** Delete File: deleted.txt\n*** Add File: created.txt\n+new\n*** End Patch"}),
        "done", "read only done"])
    run_repl(runtime_config.load(), input_stream=["change files", "yes", "yes", "read only", "exit"], output_stream=StringIO())
    assert edited.read_bytes() == b"final\r\n"
    assert not deleted.exists()
    assert (tmp_path / "created.txt").read_bytes() == b"new\n"
    before = call_log.load_conversation(call_log.current_session_id())
    monkeypatch.setattr("sys.stdin", StringIO("/recover\nyes\n/recover\nexit\n"))
    main(["--resume", call_log.current_session_id()])
    assert edited.read_bytes() == b"original\r\n"
    assert deleted.read_bytes() == b"gone\r\n"
    assert stat.S_IMODE(edited.stat().st_mode) == 0o751
    assert stat.S_IMODE(deleted.stat().st_mode) == 0o640
    assert not (tmp_path / "created.txt").exists()
    assert call_log.load_conversation(call_log.current_session_id()) == before
    assert len(calls) == 4


@pytest.mark.parametrize("conflict", ["content", "mode", "absent", "symlink", "parent"])
def test_recover_refuses_whole_set_when_one_file_conflicts(
    route_env, tmp_path, install_fake_urlopen, conflict
):
    (tmp_path / "folder").mkdir()
    target = tmp_path / "folder/edited.txt"
    target.write_bytes(b"original")
    install_fake_urlopen([tool("apply_patch", {"patch": "*** Begin Patch\n*** Add File: created.txt\n+new\n*** Update File: folder/edited.txt\n@@\n-original\n+changed\n*** End Patch"}), "done"])

    def commands():
        yield "change"
        yield "yes"
        if conflict == "content":
            target.write_bytes(b"external")
        elif conflict == "mode":
            target.chmod(0o700)
        elif conflict == "absent":
            target.unlink()
        elif conflict == "symlink":
            target.unlink()
            target.symlink_to(tmp_path / "created.txt")
        else:
            (tmp_path / "folder").rename(tmp_path / "old-folder")
            (tmp_path / "folder").mkdir()
            target.write_bytes(b"changed\n")
        yield "/recover"
        yield "exit"

    output = StringIO()
    run_repl(runtime_config.load(), input_stream=commands(), output_stream=output)
    assert (tmp_path / "created.txt").read_bytes() == b"new\n"
    assert "conflicts; nothing restored" in output.getvalue()
    assert not any(row["type"] == "file_recovery_started" for row in entries())


@pytest.mark.parametrize("provider", ["openrouter", "gemini"])
@pytest.mark.parametrize("restart", [False, True])
def test_recovery_discards_matching_pending_tools_todo_urls_and_replay_before_fresh_retry(
    route_env, tmp_path, monkeypatch, install_fake_urlopen, provider, restart
):
    monkeypatch.setenv("PA_PROVIDER", provider)
    monkeypatch.setenv(runtime_config.API_KEY_ENV_VARS[provider], "test-key")
    target = tmp_path / "note.txt"
    target.write_bytes(b"original\r\n")
    fetch = registry._REGISTRY["webfetch"]
    prepared = SimpleNamespace(display_path="https://example.com/page", preview="fetch")
    monkeypatch.setitem(registry._REGISTRY, "webfetch", replace(fetch, prepare=lambda args: prepared,
                        apply=lambda item: {"url": "https://example.com/page", "content": "external", "status": 200}))
    first = {"tool_calls": [
        {"id": "fetch", "name": "webfetch", "arguments": {"url": "https://example.com/page"}},
        {"id": "todos", "name": "todo", "arguments": {"todos": [{"content": "obsolete pending todo", "status": "in_progress"}]}},
        {"id": "write", "name": "write", "arguments": {"path": "note.txt", "content": "changed"}}]}
    if provider == "gemini":
        first = FakeOpenRouterResponse({"candidates": [{"content": {"parts": [
            {"functionCall": {"id": call["id"], "name": call["name"], "args": call["arguments"]},
             "thoughtSignature": "obsolete-signature"} for call in first["tool_calls"]]}}]})
    calls = install_fake_urlopen([first, ValueError("provider failed"), "fresh done"])
    output = StringIO()
    commands = ["change it", "yes", "yes", "exit"] if restart else ["change it", "yes", "yes", "/recover", "yes", "/retry", "exit"]
    run_repl(runtime_config.load(), input_stream=commands, output_stream=output)
    if restart:
        assert call_log.load_pending_turn(call_log.current_session_id())[1]["fetched_urls"] == ["https://example.com/page"]
        monkeypatch.setattr("sys.stdin", StringIO("/recover\nyes\nexit\n"))
        main(["--resume", call_log.current_session_id()])
        pending = call_log.load_pending_turn(call_log.current_session_id())
        assert pending[1]["messages"] == [{"role": "user", "content": "change it"}]
        assert pending[1]["replay"] is None and pending[1]["fetched_urls"] == []
        monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))
        main(["--resume", call_log.current_session_id()])
    assert target.read_bytes() == b"original\r\n"
    assert len(calls) == 3
    fresh = calls[-1]["request"].data.decode()
    assert "obsolete pending todo" not in fresh
    assert "obsolete-signature" not in fresh
    payload = json.loads(fresh)
    if provider == "gemini":
        assert payload["contents"] == [{"role": "user", "parts": [{"text": "change it"}]}]
    else:
        assert [row for row in payload["messages"] if row["role"] != "system"] == [{"role": "user", "content": "change it"}]
    openings = [row for row in entries() if row["type"] in {"routed_task_submitted", "routed_task_retried"}]
    assert [row["ordinal"] for row in openings] == [1, 1]


@pytest.mark.parametrize("answer", ["no", "y", "YES", None, KeyboardInterrupt()])
def test_recover_requires_literal_yes_even_in_auto(route_env, tmp_path, install_fake_urlopen, answer):
    from tests.test_continuation import Box
    install_fake_urlopen([tool("write", {"path": "created.txt", "content": "new"}), "done"])
    response = EOFError() if answer is None else answer
    output = StringIO()
    run_repl(runtime_config.load(), input_box=Box(["/mode auto", "create", "/recover", "exit"], [response]), output_stream=output)
    assert (tmp_path / "created.txt").read_bytes() == b"new"
    assert "File recovery cancelled" in output.getvalue()


@pytest.mark.parametrize("switch", [False, True])
def test_plan_recovery_preview_never_restores_including_live_mode_change(
    route_env, tmp_path, install_fake_urlopen, switch
):
    from tests.test_continuation import Box

    class ModeBox(Box):
        def ask(self, question):
            if "restore these files" in question and switch:
                self.on_mode_toggle()
            return super().ask(question)

    calls = install_fake_urlopen([tool("write", {"path": "created.txt", "content": "new"}), "done"])
    commands = ["/mode auto", "create", "/recover", "exit"] if switch else ["/mode auto", "create", "/mode plan", "/recover", "exit"]
    output = StringIO()
    run_repl(runtime_config.load(), input_box=ModeBox(commands, ["yes"]), output_stream=output)
    assert (tmp_path / "created.txt").exists()
    assert len(calls) == 2
    assert "Plan mode" in output.getvalue()


def test_unclosed_mutation_recovery_retains_request_for_fresh_retry_after_resume(
    route_env, tmp_path, monkeypatch, install_fake_urlopen
):
    calls = install_fake_urlopen([tool("write", {"path": "note.txt", "content": "changed"}), "done", "fresh done"])
    run_repl(runtime_config.load(), input_stream=["original request", "yes", "exit"], output_stream=StringIO())
    rows = entries()
    path = Path(call_log.session_log_path())
    cut = next(i for i, row in enumerate(rows) if row["type"] == "turn_end")
    path.write_text("".join(json.dumps(row) + "\n" for row in rows[:cut]))
    monkeypatch.setattr("sys.stdin", StringIO("/recover\nyes\nexit\n"))
    main(["--resume", call_log.current_session_id()])
    assert not (tmp_path / "note.txt").exists()
    pending = call_log.load_pending_turn(call_log.current_session_id())
    assert pending is not None
    assert pending[0] == 1 and pending[1]["messages"] == [{"role": "user", "content": "original request"}]
    monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))
    main(["--resume", call_log.current_session_id()])
    assert len(calls) == 3


@pytest.mark.parametrize("boundary", ["before_intent", "after_intent", "before_write", "after_write", "before_promotion", "after_promotion"])
def test_process_death_at_capture_boundaries_reconciles_without_running_tools(
    route_env, tmp_path, monkeypatch, install_fake_urlopen, boundary
):
    sid = "20261015T000000Z-abc123"
    monkeypatch.setattr(call_log, "_mint_session_id", lambda: sid)
    install_fake_urlopen([tool("write", {"path": "note.txt", "content": "changed\r\n"}), "done"])
    original_save = file_recovery.FileRecovery._save
    original_put = file_recovery.put
    original_replace = os.replace

    def save(self, manifest, name="active.json"):
        if manifest["state"] == "capturing" and boundary == "before_intent":
            os._exit(79)
        original_save(self, manifest, name)
        if manifest["state"] == "capturing" and boundary == "after_intent":
            os._exit(79)

    def put(identity, state):
        if boundary == "before_write":
            os._exit(79)
        original_put(identity, state)
        if boundary == "after_write":
            os._exit(79)

    def replace(source, destination, **kwargs):
        promotion = source == "active.json" and destination == "latest.json"
        if promotion and boundary == "before_promotion":
            os._exit(79)
        original_replace(source, destination, **kwargs)
        if promotion and boundary == "after_promotion":
            os._exit(79)

    child = os.fork()
    if child == 0:
        file_recovery.FileRecovery._save = save
        file_recovery.put = put
        os.replace = replace
        run_repl(runtime_config.load(), input_stream=["request", "yes", "exit"], output_stream=StringIO())
        os._exit(80)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 79
    call_log.initialize_storage(tmp_path)
    restored = call_log.load_conversation(sid)
    output = StringIO()
    run_repl(runtime_config.load(), resumed=(sid, *restored), input_stream=["/recover", "no", "exit"], output_stream=output)
    changed = boundary in {"after_write", "before_promotion", "after_promotion"}
    assert (tmp_path / "note.txt").exists() == changed
    if changed:
        assert (tmp_path / "note.txt").read_bytes() == b"changed\r\n"
        assert "File recovery: Session" in output.getvalue()
        assert "outcome unknown" in output.getvalue()
    else:
        assert "no available file checkpoint" in output.getvalue()


@pytest.mark.parametrize("stage", ["intent", "observed", "promotion"])
def test_capture_persistence_failures_stop_before_dependent_dispatch(
    route_env, tmp_path, monkeypatch, install_fake_urlopen, stage
):
    calls = install_fake_urlopen([tool("write", {"path": "note.txt", "content": "changed"}), "done"])
    original_save = file_recovery.FileRecovery._save
    original_replace = os.replace

    def save(self, manifest, name="active.json"):
        if (stage == "intent" and manifest["state"] == "capturing"
                or stage == "observed" and manifest["state"] == "ready"):
            raise OSError("injected manifest failure")
        return original_save(self, manifest, name)

    def replace(source, destination, **kwargs):
        if stage == "promotion" and source == "active.json" and destination == "latest.json":
            raise OSError("injected promotion failure")
        return original_replace(source, destination, **kwargs)

    monkeypatch.setattr(file_recovery.FileRecovery, "_save", save)
    monkeypatch.setattr(os, "replace", replace)
    if stage == "intent":
        output = StringIO()
        run_repl(runtime_config.load(), input_stream=["request", "yes", "exit"], output_stream=output)
        assert not (tmp_path / "note.txt").exists()
        assert "cannot capture file recovery before mutation" in output.getvalue()
    else:
        with pytest.raises(call_log.PersistenceError, match="unresolved file mutation after write"):
            run_repl(runtime_config.load(), input_stream=["request", "yes", "exit"], output_stream=StringIO())
        assert (tmp_path / "note.txt").read_bytes() == b"changed"
        assert len(calls) == 1


def test_failed_single_write_with_real_partial_bytes_rolls_back_exactly(
    route_env, tmp_path, monkeypatch, install_fake_urlopen
):
    target = tmp_path / "note.txt"
    target.write_bytes(b"original\r\n")
    target.chmod(0o751)
    original_put = file_recovery.put
    failed = False

    def partial(identity, state):
        nonlocal failed
        if not failed:
            failed = True
            target.write_bytes(b"partial")
            target.chmod(0o600)
            raise OSError("injected real partial write")
        return original_put(identity, state)

    monkeypatch.setattr(file_recovery, "put", partial)
    install_fake_urlopen([tool("write", {"path": "note.txt", "content": "changed"}), "done"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=["request", "yes", "/recover", "exit"], output_stream=output)
    assert target.read_bytes() == b"original\r\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o751
    assert "no available file checkpoint" in output.getvalue()


@pytest.mark.parametrize("failure", ["restore", "rollback", "completion", "promotion"])
def test_restore_failure_rolls_back_or_halts_with_durable_uncertainty(
    route_env, tmp_path, monkeypatch, install_fake_urlopen, failure
):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_bytes((name + " original\r\n").encode())
    calls = install_fake_urlopen([tool("apply_patch", {"patch": "*** Begin Patch\n*** Update File: a.txt\n@@\n-a.txt original\n+A\n*** Update File: b.txt\n@@\n-b.txt original\n+B\n*** End Patch"}), "done"])
    original_put = file_recovery.put
    original_log = call_log.write_file_recovery
    original_replace = os.replace
    recovering = False
    failed = False

    def put(identity, state):
        nonlocal failed
        if recovering and failure in {"restore", "rollback"}:
            if identity["supplied"] == "b.txt" and not failed:
                failed = True
                (tmp_path / "b.txt").write_bytes(b"partial restore")
                raise OSError("injected partial restore")
            if failure == "rollback" and failed and identity["supplied"] == "a.txt":
                raise OSError("injected failed rollback")
        return original_put(identity, state)

    def log(phase, reference, outcome=None):
        nonlocal failed
        if failure == "completion" and phase == "finished" and outcome == "ok" and not failed:
            failed = True
            raise call_log.PersistenceError("injected completion failure")
        return original_log(phase, reference, outcome)

    def replace(source, destination, **kwargs):
        nonlocal failed
        if (recovering and failure == "promotion" and source == "active.json"
                and destination == "latest.json" and not failed):
            failed = True
            raise OSError("injected recovered promotion failure")
        return original_replace(source, destination, **kwargs)

    monkeypatch.setattr(file_recovery, "put", put)
    monkeypatch.setattr(call_log, "write_file_recovery", log)
    monkeypatch.setattr(os, "replace", replace)

    def commands():
        nonlocal recovering
        yield "change"
        yield "yes"
        recovering = True
        yield "/recover"
        yield "yes"
        yield "exit"

    output = StringIO()
    if failure == "restore":
        run_repl(runtime_config.load(), input_stream=commands(), output_stream=output)
        assert "restored known after-states" in output.getvalue()
    else:
        with pytest.raises(call_log.PersistenceError):
            run_repl(runtime_config.load(), input_stream=commands(), output_stream=output)
    assert len(calls) == 2
    assert "Recovered files" not in output.getvalue()
    if failure == "promotion":
        assert (tmp_path / "a.txt").read_bytes() == b"a.txt original\r\n"
        assert (tmp_path / "b.txt").read_bytes() == b"b.txt original\r\n"
        monkeypatch.setattr("sys.stdin", StringIO("/recover\nexit\n"))
        main(["--resume", call_log.current_session_id()])
    else:
        assert (tmp_path / "b.txt").read_bytes() == b"B\r\n"
        assert (tmp_path / "a.txt").read_bytes() == (b"a.txt original\r\n" if failure == "rollback" else b"A\r\n")
        assert not any(row["type"] == "file_recovery_finished" and row.get("outcome") == "ok" for row in entries())


@pytest.mark.parametrize("boundary", ["intent", "first_file", "first_progress", "all_files", "completion"])
def test_process_death_during_restore_never_replays_obsolete_pending_results(
    route_env, tmp_path, monkeypatch, install_fake_urlopen, boundary
):
    sid = "20261015T000000Z-abc123"
    monkeypatch.setattr(call_log, "_mint_session_id", lambda: sid)
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_bytes((name + " original\r\n").encode())
    install_fake_urlopen([tool("apply_patch", {"patch": "*** Begin Patch\n*** Update File: a.txt\n@@\n-a.txt original\n+A\n*** Update File: b.txt\n@@\n-b.txt original\n+B\n*** End Patch"}), ValueError("failed provider")])
    original_save = file_recovery.FileRecovery._save
    original_put = file_recovery.put
    original_log = call_log.write_file_recovery
    restoring = False

    def save(self, manifest, name="active.json"):
        original_save(self, manifest, name)
        if restoring and manifest["state"] == "restoring" and manifest["progress"] == [0] and boundary == "first_progress":
            os._exit(79)
        if restoring and manifest["state"] == "recovered" and boundary == "all_files":
            os._exit(79)

    def put(identity, state):
        original_put(identity, state)
        if restoring and identity["supplied"] == "a.txt" and boundary == "first_file":
            os._exit(79)

    def log(phase, reference, outcome=None):
        original_log(phase, reference, outcome)
        if restoring and phase == "started" and boundary == "intent":
            os._exit(79)
        if restoring and phase == "finished" and outcome == "ok" and boundary == "completion":
            os._exit(79)

    def commands():
        nonlocal restoring
        yield "request"
        yield "yes"
        restoring = True
        yield "/recover"
        yield "yes"

    child = os.fork()
    if child == 0:
        file_recovery.FileRecovery._save = save
        file_recovery.put = put
        call_log.write_file_recovery = log
        run_repl(runtime_config.load(), input_stream=commands(), output_stream=StringIO())
        os._exit(80)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 79
    call_log.initialize_storage(tmp_path)
    pending = call_log.load_pending_turn(sid)
    assert pending is not None and pending[1]["messages"] == [{"role": "user", "content": "request"}]
    first_restored = boundary != "intent"
    second_restored = boundary in {"all_files", "completion"}
    before = [(tmp_path / name).read_bytes() for name in ("a.txt", "b.txt")]
    assert before == [b"a.txt original\r\n" if first_restored else b"A\r\n",
                      b"b.txt original\r\n" if second_restored else b"B\r\n"]
    output = StringIO()
    run_repl(runtime_config.load(), resumed=(sid, *call_log.load_conversation(sid)),
             input_stream=["/recover", "exit"], output_stream=output)
    assert [(tmp_path / name).read_bytes() for name in ("a.txt", "b.txt")] == before
    if boundary == "completion":
        assert "no available file checkpoint" in output.getvalue()
    else:
        assert "unresolved" in output.getvalue()
    assert "Recovered files" not in output.getvalue()


def test_recovery_preserves_unrelated_later_pending_execution(route_env, tmp_path, monkeypatch, install_fake_urlopen):
    calls = install_fake_urlopen([
        tool("write", {"path": "created.txt", "content": "created"}), "first done",
        tool("calculator", {"expression": "2+2"}, "later-result"), ValueError("later failed"), "later done"])
    run_repl(runtime_config.load(), input_stream=["first task", "yes", "later task", "/recover", "yes", "exit"], output_stream=StringIO())
    pending = call_log.load_pending_turn(call_log.current_session_id())
    assert pending[0] == 2 and len(pending[1]["messages"]) == 3
    assert not (tmp_path / "created.txt").exists()
    monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))
    main(["--resume", call_log.current_session_id()])
    fresh = json.loads(calls[-1]["request"].data)["messages"]
    assert any(message.get("tool_call_id") == "later-result" for message in fresh)
    assert len(calls) == 5


@pytest.mark.parametrize("fault", ["mode", "link", "nonregular", "hash", "identity", "version", "base64", "oversize", "state_shape", "owner", "directory_mode", "hardlink"])
def test_unsafe_or_corrupt_companion_is_refused_before_recovery_or_dispatch(
    route_env, tmp_path, monkeypatch, install_fake_urlopen, fault
):
    calls = install_fake_urlopen([tool("write", {"path": "created.txt", "content": "created"}), "done"])
    run_repl(runtime_config.load(), input_stream=["request", "yes", "exit"], output_stream=StringIO())
    manifest = Path(call_log.session_log_path()).parent / f"recovery-{call_log.current_session_id()}" / "latest.json"
    if fault == "mode":
        manifest.chmod(0o644)
    elif fault == "owner":
        uid = os.getuid()
        monkeypatch.setattr(os, "getuid", lambda: uid + 1)
    elif fault == "directory_mode":
        manifest.parent.chmod(0o755)
    elif fault == "hardlink":
        os.link(manifest, tmp_path / "hardlink.json")
    elif fault == "link":
        manifest.rename(manifest.with_suffix(".saved"))
        manifest.symlink_to(manifest.with_suffix(".saved"))
    elif fault == "nonregular":
        manifest.unlink()
        os.mkfifo(manifest, 0o600)
    elif fault == "oversize":
        with manifest.open("r+b") as stream:
            stream.truncate(file_recovery.MANIFEST_LIMIT + 1)
    else:
        document = json.loads(manifest.read_bytes())
        if fault == "hash":
            document["entries"][0]["after"]["sha256"] = "0" * 64
        elif fault == "identity":
            document["workspace_root"] = "/other-project"
        elif fault == "version":
            document["version"] = True
        elif fault == "state_shape":
            document["state"] = []
        else:
            document["entries"][0]["after"]["data"] = "!invalid!"
        manifest.write_text(json.dumps(document))
    output = StringIO()
    run_repl(runtime_config.load(), resumed=(call_log.current_session_id(), *call_log.load_conversation(call_log.current_session_id())),
             input_stream=["/recover", "exit"], output_stream=output)
    assert "unresolved file recovery" in output.getvalue()
    with pytest.raises(call_log.PersistenceError):
        run_repl(runtime_config.load(), resumed=(call_log.current_session_id(), *call_log.load_conversation(call_log.current_session_id())),
                 input_stream=["new request"], output_stream=StringIO())
    assert (tmp_path / "created.txt").read_bytes() == b"created"
    assert len(calls) == 2


def test_repeated_canonical_and_leaf_alias_mutations_coalesce_and_keep_link(
    route_env, tmp_path, install_fake_urlopen
):
    target = tmp_path / "original.txt"
    target.write_bytes(b"original")
    link = tmp_path / "alias.txt"
    link.symlink_to("original.txt")
    calls = install_fake_urlopen([
        tool("write", {"path": "original.txt", "content": "middle"}),
        tool("edit", {"path": "alias.txt", "old_string": "middle", "new_string": "final"}), "done"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=["change", "yes", "yes", "/recover", "yes", "exit"], output_stream=output)
    assert target.read_bytes() == b"original"
    assert link.is_symlink() and os.readlink(link) == "original.txt"
    assert len(calls) == 3
    results = [row for row in entries() if row["type"] == "tool_execution"]
    assert all(row["ok"] for row in results)


def test_exact_snapshot_bytes_stay_private_and_preview_redacts_credentials(
    route_env, tmp_path, monkeypatch, install_fake_urlopen
):
    secret = "test-key"
    original = b"original secret=test-key\r\n\x1b[31m"
    (tmp_path / "note.txt").write_bytes(original)
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    calls = install_fake_urlopen([tool("write", {"path": "note.txt", "content": "changed"}), "done"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=["request", "yes", "/recover", "yes", "/report", "exit"], output_stream=output)
    assert (tmp_path / "note.txt").read_bytes() == original
    assert secret not in output.getvalue()
    assert "\x1b" not in output.getvalue()
    log_path = Path(call_log.session_log_path())
    assert secret not in log_path.read_text()
    assert secret not in log_path.with_suffix(".audit.jsonl").read_text()
    assert all(secret not in call["request"].data.decode() for call in calls)
    storage = log_path.parent / f"recovery-{call_log.current_session_id()}"
    assert stat.S_IMODE(storage.stat().st_mode) == 0o700
    for path in storage.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    manifest = json.loads((storage / "latest.json").read_text())
    assert manifest["entries"][0]["before"]["data"] == "b3JpZ2luYWwgc2VjcmV0PXRlc3Qta2V5DQobWzMxbQ=="


@pytest.mark.parametrize("unsafe", ["hardlink", "excluded", "resolved_excluded", "storage"])
def test_unsafe_mutation_never_reaches_confirmation_or_changes_targets(
    route_env, tmp_path, install_fake_urlopen, unsafe
):
    original = tmp_path / "original.txt"
    original.write_bytes(b"original")

    def commands():
        if unsafe == "hardlink":
            os.link(original, tmp_path / "target.txt")
            target = "target.txt"
        elif unsafe == "excluded":
            target = ".env"
        elif unsafe == "resolved_excluded":
            (tmp_path / "private.key").write_bytes(b"secret")
            (tmp_path / "target.txt").symlink_to("private.key")
            target = "target.txt"
        else:
            target = str(Path(call_log.session_log_path()).relative_to(tmp_path))
        install_fake_urlopen([tool("write", {"path": target, "content": "changed"}), "done"])
        yield "request"
        yield "exit"

    output = StringIO()
    run_repl(runtime_config.load(), input_stream=commands(), output_stream=output)
    assert "Apply this change?" not in output.getvalue()
    assert original.read_bytes() == b"original"
    if unsafe == "hardlink":
        assert (tmp_path / "target.txt").read_bytes() == b"original"


@pytest.mark.parametrize("bound", ["image", "configured_image", "paths", "snapshots", "manifest", "session"])
def test_recovery_bounds_reject_before_the_would_exceed_write(
    route_env, tmp_path, monkeypatch, install_fake_urlopen, bound
):
    if bound == "image":
        monkeypatch.setenv("PA_MAX_WRITE_BYTES", str(8 * 1024 * 1024))
        monkeypatch.setattr(file_recovery, "IMAGE_LIMIT", 4)
        responses = [tool("write", {"path": "too-large.txt", "content": "12345"}), "done"]
    elif bound == "configured_image":
        monkeypatch.setenv("PA_MAX_WRITE_BYTES", "4")
        responses = [tool("write", {"path": "too-large.txt", "content": "12345"}), "done"]
    elif bound == "paths":
        monkeypatch.setenv("PA_MAX_TOOL_ROUNDS", "100")
        responses = [tool("write", {"path": f"file-{index}.txt", "content": "x"}, str(index)) for index in range(65)] + ["done"]
    else:
        if bound == "snapshots":
            monkeypatch.setattr(file_recovery, "SNAPSHOT_LIMIT", 6)
        elif bound == "manifest":
            monkeypatch.setattr(file_recovery, "MANIFEST_LIMIT", 500)
        else:
            monkeypatch.setattr(file_recovery, "STORAGE_LIMIT", 1000)
        responses = [tool("write", {"path": "too-large.txt", "content": "1234567"}), "done"]
    install_fake_urlopen(responses)
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=["/mode auto", "request", "exit"], output_stream=output)
    if bound == "paths":
        assert len(list(tmp_path.glob("file-*.txt"))) == 64
        assert not (tmp_path / "file-64.txt").exists()
    else:
        assert not (tmp_path / "too-large.txt").exists()
    errors = [row["error"] for row in entries() if row["type"] == "tool_execution" and not row["ok"]]
    assert any("exceed" in error for error in errors)


@pytest.mark.parametrize("phase", ["started", "finished"])
@pytest.mark.parametrize("rollback_fails", [False, True])
def test_recovery_log_partial_append_restores_prefix_or_halts_without_false_success(
    route_env, tmp_path, monkeypatch, install_fake_urlopen, phase, rollback_fails
):
    target = tmp_path / "note.txt"
    target.write_bytes(b"original\r\n")
    calls = install_fake_urlopen([tool("write", {"path": "note.txt", "content": "changed"}), ValueError("failed")])
    original_open = call_log.open_session_file
    failed = False

    class PartialWriter:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def write(self, line):
            nonlocal failed
            entry = json.loads(line)
            if (not failed and entry.get("type") == f"file_recovery_{phase}"
                    and (phase == "started" or entry.get("outcome") == "ok")):
                failed = True
                self.stream.write(line[:17])
                self.stream.flush()
                raise OSError("injected partial recovery append")
            return self.stream.write(line)

        def truncate(self, size):
            if failed and rollback_fails:
                raise OSError("injected prefix restoration failure")
            return self.stream.truncate(size)

    def open_file(*args, **kwargs):
        stream = original_open(*args, **kwargs)
        return PartialWriter(stream) if len(args) > 1 and args[1] == "a" else stream

    monkeypatch.setattr(call_log, "open_session_file", open_file)
    with pytest.raises(call_log.PersistenceError):
        run_repl(runtime_config.load(), input_stream=["request", "yes", "/recover", "yes", "exit"], output_stream=StringIO())
    assert len(calls) == 2
    assert target.read_bytes() == b"changed"
    if rollback_fails:
        with pytest.raises(call_log.ResumeError, match="invalid Call Log line"):
            call_log.load_conversation(call_log.current_session_id())
    else:
        pending = call_log.load_pending_turn(call_log.current_session_id())
        assert len(pending[1]["messages"]) == (3 if phase == "started" else 1)
        assert not any(row["type"] == "file_recovery_finished" and row.get("outcome") == "ok" for row in entries())


def test_explicit_retry_has_its_own_file_set_and_recovery_never_walks_older_changes(
    route_env, tmp_path, install_fake_urlopen
):
    calls = install_fake_urlopen([
        tool("write", {"path": "first.txt", "content": "first"}), ValueError("failed first"),
        tool("write", {"path": "retry.txt", "content": "retry"}), ValueError("failed retry")])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=["request", "yes", "/retry", "yes", "/recover", "yes", "/recover", "exit"], output_stream=output)
    assert (tmp_path / "first.txt").read_bytes() == b"first"
    assert not (tmp_path / "retry.txt").exists()
    assert len(calls) == 4
    recovery = next(row for row in entries() if row["type"] == "file_recovery_started")
    retry_position = next(i for i, row in enumerate(entries(), 1) if row["type"] == "routed_task_retried")
    assert recovery["execution"]["opening"] == retry_position
    assert recovery["ordinal"] == 1
    assert "no available file checkpoint" in output.getvalue()


@pytest.mark.parametrize("later", ["read_only", "noop", "reject", "clear", "undo", "rolled_back", "compress"])
def test_later_unchanged_execution_and_conversation_commands_retain_latest_checkpoint(
    route_env, tmp_path, monkeypatch, install_fake_urlopen, later
):
    responses = [tool("write", {"path": "first.txt", "content": "first"}), "done"]
    commands = ["request", "yes"]
    if later == "read_only":
        responses.append("read only done")
        commands.append("read only")
    elif later == "noop":
        responses.extend([tool("write", {"path": "first.txt", "content": "first"}), "done"])
        commands.extend(["same bytes", "yes"])
    elif later == "reject":
        responses.extend([tool("write", {"path": "second.txt", "content": "second"}), "done"])
        commands.extend(["reject", "no"])
    elif later == "rolled_back":
        original_put = file_recovery.put
        failed = False

        def partial(identity, state):
            nonlocal failed
            if identity["supplied"] == "second.txt" and not failed:
                failed = True
                (tmp_path / "second.txt").write_bytes(b"partial")
                raise OSError("injected partial write")
            return original_put(identity, state)

        monkeypatch.setattr(file_recovery, "put", partial)
        responses.extend([tool("write", {"path": "second.txt", "content": "second"}), "done"])
        commands.extend(["failed mutation", "yes"])
    elif later == "compress":
        responses.extend(["second done", "third done", "summary"])
        commands.extend(["second", "third", "/compress"])
    else:
        commands.append("/" + later)
    install_fake_urlopen(responses)
    run_repl(runtime_config.load(), input_stream=[*commands, "/recover", "yes", "exit"], output_stream=StringIO())
    assert not (tmp_path / "first.txt").exists()
    recovery = next(row for row in entries() if row["type"] == "file_recovery_started")
    assert recovery["ordinal"] == 1


def test_actual_four_mebibyte_limit_rejects_tool_before_confirmation(tmp_path):
    workspace.configure_workspace(tmp_path, max_write_bytes_value=8 * 1024 * 1024)
    content = "x" * (4 * 1024 * 1024 + 1)
    result = registry.execute_batch([ToolCall(id="large", name="write", arguments={"path": "large.txt", "content": content})],
                                    confirm=lambda *args: pytest.fail("oversized image reached confirmation"))[0]
    assert result.is_error and "4194304" in result.content["error"]
    assert not (tmp_path / "large.txt").exists()


def test_recovery_preview_is_bounded_after_control_character_sanitization(
    route_env, tmp_path, install_fake_urlopen
):
    (tmp_path / "note.txt").write_bytes(b"\x1b" * 50000)
    calls = install_fake_urlopen([tool("write", {"path": "note.txt", "content": "changed"}), "done"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=["/mode auto", "request", "/recover", "no", "exit"], output_stream=output)
    assert len(output.getvalue()) < 65000
    assert "omitted" in output.getvalue()
    assert len(calls) == 2


def test_unresolved_journal_blocks_manual_compression_dispatch_on_resume(
    route_env, tmp_path, install_fake_urlopen
):
    calls = install_fake_urlopen([tool("write", {"path": "note.txt", "content": "new"}), "done", "second done", "third done", "summary"])
    run_repl(runtime_config.load(), input_stream=["first", "yes", "second", "third", "exit"], output_stream=StringIO())
    manifest = Path(call_log.session_log_path()).parent / f"recovery-{call_log.current_session_id()}" / "latest.json"
    document = json.loads(manifest.read_text())
    document["entries"][0]["after"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(document))
    with pytest.raises(call_log.PersistenceError, match="unresolved file recovery"):
        run_repl(runtime_config.load(), resumed=(call_log.current_session_id(), *call_log.load_conversation(call_log.current_session_id())),
                 input_stream=["/compress", "exit"], output_stream=StringIO())
    assert len(calls) == 4


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("provider", ["openrouter", "gemini"])
def test_recover_invalidates_prefix_inherited_by_retry_without_new_file_changes(
    route_env, tmp_path, monkeypatch, install_fake_urlopen, restart, provider
):
    monkeypatch.setenv("PA_PROVIDER", provider)
    monkeypatch.setenv(runtime_config.API_KEY_ENV_VARS[provider], "test-key")
    calls = install_fake_urlopen([
        tool("write", {"path": "note.txt", "content": "changed"}, "old-write"), ValueError("failed first"),
        tool("calculator", {"expression": "2+2"}, "retry-calculator"), ValueError("failed retry"), "fresh done"])
    commands = ["request", "yes", "/retry", "exit"] if restart else ["request", "yes", "/retry", "/recover", "yes", "/retry", "exit"]
    run_repl(runtime_config.load(), input_stream=commands, output_stream=StringIO())
    if restart:
        monkeypatch.setattr("sys.stdin", StringIO("/recover\nyes\nexit\n"))
        main(["--resume", call_log.current_session_id()])
        pending = call_log.load_pending_turn(call_log.current_session_id())
        assert pending[1]["messages"] == [{"role": "user", "content": "request"}]
        assert pending[1]["fetched_urls"] == [] and pending[1]["replay"] is None
        monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))
        main(["--resume", call_log.current_session_id()])
    assert not (tmp_path / "note.txt").exists()
    assert len(calls) == 5
    payload = json.loads(calls[-1]["request"].data)
    if provider == "gemini":
        assert payload["contents"] == [{"role": "user", "parts": [{"text": "request"}]}]
    else:
        assert [message for message in payload["messages"] if message["role"] != "system"] == [{"role": "user", "content": "request"}]


def test_recover_preserves_same_ordinal_retry_without_inherited_target_prefix(
    route_env, tmp_path, monkeypatch, install_fake_urlopen
):
    calls = install_fake_urlopen([
        tool("write", {"path": "note.txt", "content": "changed"}, "old-write"), "first done",
        tool("calculator", {"expression": "2+2"}, "independent-calculator"), ValueError("failed retry"), "continued"])
    run_repl(runtime_config.load(), input_stream=["request", "yes", "/retry", "/recover", "yes", "exit"], output_stream=StringIO())
    pending = call_log.load_pending_turn(call_log.current_session_id())
    assert pending[0] == 1 and len(pending[1]["messages"]) == 3
    assert pending[1]["messages"][2]["id"] == "independent-calculator"
    assert not (tmp_path / "note.txt").exists()
    monkeypatch.setattr("sys.stdin", StringIO("/retry\nexit\n"))
    main(["--resume", call_log.current_session_id()])
    assert len(calls) == 5
    assert "independent-calculator" in calls[-1]["request"].data.decode()


def test_recovery_invalidates_inherited_prefix_when_retry_has_no_turn_end(
    route_env, tmp_path, monkeypatch, install_fake_urlopen
):
    calls = install_fake_urlopen([
        tool("write", {"path": "note.txt", "content": "changed"}, "old-write"), ValueError("failed first"),
        tool("calculator", {"expression": "2+2"}, "unfinished-retry"), ValueError("failed retry"), "fresh done"])
    run_repl(runtime_config.load(), input_stream=["request", "yes", "/retry", "exit"], output_stream=StringIO())
    rows = entries()
    cut = max(i for i, row in enumerate(rows) if row["type"] == "turn_end")
    Path(call_log.session_log_path()).write_text("".join(json.dumps(row) + "\n" for row in rows[:cut]))
    monkeypatch.setattr("sys.stdin", StringIO("/recover\nyes\n/retry\nexit\n"))
    main(["--resume", call_log.current_session_id()])
    assert not (tmp_path / "note.txt").exists()
    assert len(calls) == 5
    payload = json.loads(calls[-1]["request"].data)
    assert [message for message in payload["messages"] if message["role"] != "system"] == [{"role": "user", "content": "request"}]


@pytest.mark.parametrize("read", ["read_file", "read_alias", "search_file", "search_walk", "list_directory", "list_walk", "cross_project"])
def test_workspace_reads_cannot_send_private_checkpoint_images_to_provider(
    route_env, tmp_path, install_fake_urlopen, read
):
    (tmp_path / "note.txt").write_bytes(b"private original")
    install_fake_urlopen([tool("write", {"path": "note.txt", "content": "changed"}), "done"])
    run_repl(runtime_config.load(), input_stream=["request", "yes", "exit"], output_stream=StringIO())
    sid = call_log.current_session_id()
    manifest = Path(call_log.session_log_path()).parent / f"recovery-{sid}" / "latest.json"
    path = str(manifest.relative_to(tmp_path))
    if read == "read_alias":
        (tmp_path / "alias.json").symlink_to(manifest)
        name, arguments = "read_file", {"path": "alias.json"}
    elif read == "cross_project":
        other = manifest.parent.parent.parent / "other-project--0123456789ab"
        other.mkdir(mode=0o700)
        companion = other / manifest.parent.name
        companion.mkdir(mode=0o700)
        copied = companion / manifest.name
        copied.write_bytes(manifest.read_bytes())
        copied.chmod(0o600)
        name, arguments = "read_file", {"path": str(copied.relative_to(tmp_path))}
    elif read == "read_file":
        name, arguments = read, {"path": path}
    elif read.startswith("search"):
        name, arguments = "search_text", {"path": path if read == "search_file" else ".", "text": "sha256"}
    else:
        name, arguments = "list_files", {"path": str(manifest.parent.relative_to(tmp_path)) if read == "list_directory" else "."}
    calls = install_fake_urlopen([tool(name, arguments), "read done"])
    run_repl(runtime_config.load(), resumed=(sid, *call_log.load_conversation(sid)),
             input_stream=["read snapshot", "exit"], output_stream=StringIO())
    assert len(calls) == 2
    assert "cHJpdmF0ZSBvcmlnaW5hbA==" not in calls[-1]["request"].data.decode()
    read = next(row for row in reversed(entries()) if row["type"] == "tool_execution")
    if not arguments["path"] == ".":
        assert not read["ok"] and "excluded" in read["error"]
    else:
        assert read["ok"]
        assert str(manifest.relative_to(tmp_path)) not in json.dumps(read["result"])


@pytest.mark.parametrize("cross_project", [False, True])
@pytest.mark.parametrize("scope", ["project", "catalog"])
@pytest.mark.parametrize("operation", ["search_before", "search_after", "list"])
def test_recursive_workspace_aliases_keep_recovery_images_out_of_provider_and_logs(
    route_env, tmp_path, monkeypatch, install_fake_urlopen, cross_project, scope, operation
):
    monkeypatch.setenv("PA_DETAILED_AUDIT", "1")
    (tmp_path / "note.txt").write_bytes(b"private original")
    install_fake_urlopen([tool("write", {"path": "note.txt", "content": "changed"}), "done"])
    run_repl(runtime_config.load(), input_stream=["change", "yes", "exit"], output_stream=StringIO())
    sid = call_log.current_session_id()
    log_path = Path(call_log.session_log_path())
    manifest = log_path.parent / f"recovery-{sid}" / "latest.json"
    project = log_path.parent
    if cross_project:
        project = project.parent / "other-project--0123456789ab"
        companion = project / manifest.parent.name
        companion.mkdir(parents=True, mode=0o700)
        copied = companion / manifest.name
        copied.write_bytes(manifest.read_bytes())
        copied.chmod(0o600)
    (project / "visible.txt").write_text("visible before after")
    (tmp_path / "logs-alias").symlink_to(project.parent, target_is_directory=True)
    (tmp_path / "home-alias").symlink_to(tmp_path, target_is_directory=True)
    path = f"logs-alias/{project.name}" if scope == "project" else "home-alias/.personal_agent"
    visible = f"{path}/visible.txt" if scope == "project" else f"{path}/logs/{project.name}/visible.txt"
    if operation == "list":
        name, arguments = "list_files", {"path": path}
    else:
        name, arguments = "search_text", {"path": path, "text": operation.removeprefix("search_")}
    calls = install_fake_urlopen([tool(name, arguments), "read done"])
    run_repl(runtime_config.load(), resumed=(sid, *call_log.load_conversation(sid)),
             input_stream=["inspect files", "exit"], output_stream=StringIO())

    assert len(calls) == 2
    result = next(row for row in reversed(entries()) if row["type"] == "tool_execution")
    assert result["ok"]
    assert visible in json.dumps(result["result"])
    assert "recovery-" not in json.dumps(result["result"])
    surfaces = [json.dumps(result), log_path.read_text(), log_path.with_suffix(".audit.jsonl").read_text()]
    surfaces.extend(call["request"].data.decode() for call in calls)
    for surface in surfaces:
        assert "cHJpdmF0ZSBvcmlnaW5hbA==" not in surface
        assert "Y2hhbmdlZA==" not in surface


@pytest.mark.parametrize("alias", [False, True])
def test_project_instruction_references_cannot_inject_private_checkpoint_images(
    route_env, tmp_path, install_fake_urlopen, alias
):
    (tmp_path / "note.txt").write_bytes(b"private original")
    calls = install_fake_urlopen([tool("write", {"path": "note.txt", "content": "changed"}), "done"])
    run_repl(runtime_config.load(), input_stream=["request", "yes", "exit"], output_stream=StringIO())
    sid = call_log.current_session_id()
    manifest = Path(call_log.session_log_path()).parent / f"recovery-{sid}" / "latest.json"
    if alias:
        (tmp_path / "alias.md").symlink_to(manifest)
    reference = "alias.md" if alias else str(manifest.relative_to(tmp_path))
    (tmp_path / "AGENTS.md").write_text("@" + reference + "\n")
    with pytest.raises(project_instructions.LoadError, match="excluded instruction file"):
        run_repl(runtime_config.load(), resumed=(sid, *call_log.load_conversation(sid)),
                 input_stream=["new request"], output_stream=StringIO())
    assert len(calls) == 2


@pytest.mark.parametrize("name", ["write", "edit", "apply_patch"])
def test_mutation_revalidates_prepared_before_state_after_confirmation(
    route_env, tmp_path, install_fake_urlopen, name
):
    from tests.test_continuation import Box
    target = tmp_path / "note.txt"
    target.write_bytes(b"original\n")

    class EditingBox(Box):
        def ask(self, question):
            target.write_bytes(b"external\n")
            return "yes"

    arguments = ({"path": "note.txt", "content": "changed"} if name == "write" else
                 {"path": "note.txt", "old_string": "original", "new_string": "changed"} if name == "edit" else
                 {"patch": "*** Begin Patch\n*** Update File: note.txt\n@@\n-original\n+changed\n*** End Patch"})
    install_fake_urlopen([tool(name, arguments), "done"])
    run_repl(runtime_config.load(), input_box=EditingBox(["request", "exit"]), output_stream=StringIO())
    assert target.read_bytes() == b"external\n"
    result = next(row for row in entries() if row["type"] == "tool_execution")
    assert not result["ok"] and "file changed after preparation" in result["error"]


def test_recovery_revalidates_whole_set_after_confirmation(route_env, tmp_path, install_fake_urlopen):
    from tests.test_continuation import Box
    target = tmp_path / "note.txt"
    target.write_bytes(b"original\n")

    class EditingBox(Box):
        def ask(self, question):
            if "restore these files" in question:
                target.write_bytes(b"external\n")
            return "yes"

    install_fake_urlopen([tool("apply_patch", {"patch": "*** Begin Patch\n*** Add File: created.txt\n+created\n*** Update File: note.txt\n@@\n-original\n+changed\n*** End Patch"}), "done"])
    output = StringIO()
    run_repl(runtime_config.load(), input_box=EditingBox(["request", "/recover", "exit"]), output_stream=output)
    assert target.read_bytes() == b"external\n"
    assert (tmp_path / "created.txt").read_bytes() == b"created\n"
    assert "conflicts; nothing restored" in output.getvalue()
    assert not any(row["type"] == "file_recovery_started" for row in entries())


def test_earlier_mutation_remains_recoverable_after_later_confirmation_interrupt(
    route_env, tmp_path, install_fake_urlopen
):
    from tests.test_continuation import Box
    calls = install_fake_urlopen([tool("write", {"path": "first.txt", "content": "first"}),
                                 tool("write", {"path": "second.txt", "content": "second"})])
    output = StringIO()
    run_repl(runtime_config.load(), input_box=Box(["request", "/recover", "exit"], ["yes", KeyboardInterrupt(), "yes"]), output_stream=output)
    assert not (tmp_path / "first.txt").exists() and not (tmp_path / "second.txt").exists()
    assert len(calls) == 2
    assert "outcome interrupted" in output.getvalue()
    pending = call_log.load_pending_turn(call_log.current_session_id())
    assert pending[1]["messages"] == [{"role": "user", "content": "request"}]


def test_recover_rejects_unexpected_arguments_without_dispatch(route_env, install_fake_urlopen):
    calls = install_fake_urlopen([])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=["/recover extra", "exit"], output_stream=output)
    assert "takes no arguments" in output.getvalue()
    assert calls == []


def test_recovery_excludes_actual_shell_effects(route_env, tmp_path, install_fake_urlopen):
    registry.enable_shell_tool()
    calls = install_fake_urlopen([
        tool("write", {"path": "file-tool.txt", "content": "file tool"}),
        tool("shell", {"command": "printf shell > shell.txt"}), "done"])
    run_repl(runtime_config.load(), input_stream=["/mode auto", "request", "/recover", "yes", "exit"], output_stream=StringIO())
    assert not (tmp_path / "file-tool.txt").exists()
    assert (tmp_path / "shell.txt").read_bytes() == b"shell"
    assert len(calls) == 3
