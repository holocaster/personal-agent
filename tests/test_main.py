import json
import os
import time
from io import StringIO
from pathlib import Path

import pytest

from personal_agent import call_log, memory
from personal_agent.__main__ import main
from personal_agent.routing import runtime_config
from personal_agent.terminal.repl import COMMANDS, run_repl


def test_main_opens_setup_repl_with_missing_pair(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", StringIO("/exit\n"))
    main()
    message = capsys.readouterr().err
    assert "PA_PROVIDER is required" in message and "PA_MODEL is required" in message
    files = list(Path.home().glob(".personal_agent/logs/*/*.jsonl"))
    entry = json.loads(files[0].read_text().splitlines()[0])
    assert entry["provider"] is None and entry["model"] is None


def test_main_gives_new_setting_guidance_for_an_old_tier_only_setup(monkeypatch, tmp_path, capsys):
    home_env = tmp_path / ".personal_agent" / ".env"
    home_env.parent.mkdir()
    original = "OPENROUTER_API_KEY=old-key\nTIER_EASY_MODEL=old\nTIER_EASY_PROVIDER=openrouter\n"
    home_env.write_text(original)
    monkeypatch.setattr("sys.stdin", StringIO("/exit\n"))
    main()
    message = capsys.readouterr().err
    assert "- PA_PROVIDER is required" in message and "- PA_MODEL is required" in message
    assert "- TIER_* settings are no longer read; set PA_PROVIDER and PA_MODEL instead" in message
    assert "old-key" not in message and home_env.read_text() == original


def test_main_opens_setup_repl_for_unknown_provider(monkeypatch, route_env, capsys):
    monkeypatch.setenv("PA_PROVIDER", "antropic")
    monkeypatch.setattr("sys.stdin", StringIO("/exit\n"))
    main()
    message = capsys.readouterr().err
    assert "Configuration error:" in message and "PA_PROVIDER" in message
    assert "antropic" in message and "openrouter" in message


def test_main_enters_repl_with_the_pair_and_only_the_selected_key(route_env, monkeypatch):
    monkeypatch.setattr("sys.stdin", StringIO(""))

    main()


@pytest.mark.parametrize("source", ["exported", "cwd_dotenv", "home_dotenv"])
def test_main_loads_tool_round_limit(route_env, monkeypatch, tmp_path, source):
    if source == "exported":
        monkeypatch.setenv("PA_MAX_TOOL_ROUNDS", "75")
    else:
        path = tmp_path / ".env" if source == "cwd_dotenv" else tmp_path / ".personal_agent" / ".env"
        path.parent.mkdir(exist_ok=True)
        path.write_text("PA_MAX_TOOL_ROUNDS=75\n")
    configs = []
    monkeypatch.setattr("personal_agent.__main__.run_repl", lambda config, **kwargs: configs.append(config))

    main()

    assert configs[0].max_tool_rounds == 75


@pytest.mark.parametrize("value", ["", "0", "-1", "1.5", "abc"])
@pytest.mark.parametrize("source", ["exported", "dotenv"])
def test_main_rejects_invalid_tool_round_limit_before_repl(route_env, monkeypatch, tmp_path, capsys, value, source):
    if source == "exported":
        monkeypatch.setenv("PA_MAX_TOOL_ROUNDS", value)
    else:
        (tmp_path / ".env").write_text(f"PA_MAX_TOOL_ROUNDS={value}\n")
    monkeypatch.setattr("personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start"))

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    assert "Configuration error: PA_MAX_TOOL_ROUNDS must be a positive decimal integer" in capsys.readouterr().err


@pytest.mark.parametrize("value", [None, "", "2.50", "not-a-number", "-1"])
@pytest.mark.parametrize("source", ["exported", "dotenv"])
def test_main_ignores_obsolete_monetary_budget(route_env, monkeypatch, tmp_path, capsys, value, source):
    if value is not None:
        if source == "exported":
            monkeypatch.setenv("PA_BUDGET_USD", value)
        else:
            (tmp_path / ".env").write_text(f"PA_BUDGET_USD={value}\n")
    monkeypatch.setattr("sys.stdin", StringIO("exit\n"))

    main()

    assert capsys.readouterr().err == ""
    assert call_log.current_session_id() is not None


def test_main_loads_home_dotenv_after_cwd_dotenv(route_env, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PA_BUDGET_USD", raising=False)
    (tmp_path / ".personal_agent").mkdir()
    (tmp_path / ".personal_agent" / ".env").write_text("PA_BUDGET_USD=from-home\nPA_MAX_WRITE_BYTES=from-home\n")
    (tmp_path / ".env").write_text("PA_BUDGET_USD=from-cwd\n")
    monkeypatch.setattr("personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start"))

    with pytest.raises(SystemExit):
        main()

    assert "PA_MAX_WRITE_BYTES" in capsys.readouterr().err
    assert os.environ["PA_BUDGET_USD"] == "from-cwd"


@pytest.mark.parametrize("winner", ["exported", "cwd", "home"])
def test_main_preserves_pair_source_precedence_and_passes_source_provenance(
    route_env, tmp_path, monkeypatch, winner
):
    monkeypatch.delenv("PA_PROVIDER")
    monkeypatch.delenv("PA_MODEL")
    if winner == "exported":
        monkeypatch.setenv("PA_MODEL", "from-export")
    if winner in ("exported", "cwd"):
        (tmp_path / ".env").write_text("PA_MODEL=from-cwd\nPA_PROVIDER=openrouter\n")
    home_env = tmp_path / ".personal_agent" / ".env"
    home_env.parent.mkdir()
    home_env.write_text("PA_MODEL=from-home\nPA_PROVIDER=openrouter\nTIER_EASY_MODEL=ignored\n")
    captured = {}
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl",
        lambda config, *args, **kwargs: captured.update(config=config, **kwargs),
    )
    monkeypatch.setattr("sys.stdin", StringIO(""))

    main()

    source = {"exported": "exported environment", "cwd": "current-directory .env", "home": "home .env"}
    assert captured["config"].model == {"exported": "from-export", "cwd": "from-cwd", "home": "from-home"}[winner]
    assert captured["config"].provider == "openrouter"
    assert captured["config_sources"] == {
        "OPENROUTER_API_KEY": "exported environment",
        "PA_MODEL": source[winner],
        "PA_PROVIDER": source["home" if winner == "home" else "cwd"],
    }


def test_main_tracks_provider_key_source_precedence_without_exposing_key_values(
    route_env, tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "exported-openai-secret")
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=current-anthropic-secret\n")
    home_env = tmp_path / ".personal_agent" / ".env"
    home_env.parent.mkdir()
    home_env.write_text(
        "OPENAI_API_KEY=home-openai-secret\n"
        "ANTHROPIC_API_KEY=home-anthropic-secret\n"
        "GEMINI_API_KEY=home-gemini-secret\n"
    )
    captured = {}
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl",
        lambda config, *args, **kwargs: captured.update(config=config, **kwargs),
    )
    monkeypatch.setattr("sys.stdin", StringIO(""))

    main()

    assert captured["config_sources"] == {
        "OPENROUTER_API_KEY": "exported environment",
        "OPENAI_API_KEY": "exported environment",
        "ANTHROPIC_API_KEY": "current-directory .env",
        "GEMINI_API_KEY": "home .env",
        "PA_PROVIDER": "exported environment",
        "PA_MODEL": "exported environment",
    }
    assert captured["config"].api_keys == {
        "openrouter": "test-key",
        "anthropic": "current-anthropic-secret",
        "openai": "exported-openai-secret",
        "gemini": "home-gemini-secret",
    }
    assert "exported-openai-secret" not in repr(captured["config_sources"])
    assert "home-openai-secret" not in repr(captured["config_sources"])
    assert "current-anthropic-secret" not in repr(captured["config_sources"])
    assert "home-anthropic-secret" not in repr(captured["config_sources"])
    assert "home-gemini-secret" not in repr(captured["config_sources"])


def test_main_ignores_obsolete_workspace_configuration(route_env, monkeypatch, tmp_path):
    monkeypatch.setenv("PA_WORKSPACE", "missing-workspace")
    captured = {}
    monkeypatch.setattr("personal_agent.__main__.run_repl", lambda *args, **kwargs: captured.update(kwargs))
    main()
    assert captured["workspace_root"] == tmp_path


def test_main_exits_before_repl_for_invalid_workspace_read_limit(route_env, monkeypatch, capsys):
    monkeypatch.setenv("PA_MAX_READ_BYTES", "not-a-number")
    monkeypatch.setattr("personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start"))

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code != 0
    assert "PA_MAX_READ_BYTES" in capsys.readouterr().err


def test_main_exits_before_repl_for_invalid_workspace_write_limit(route_env, monkeypatch, capsys):
    monkeypatch.setenv("PA_MAX_WRITE_BYTES", "not-a-number")
    monkeypatch.setattr("personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start"))

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code != 0
    assert "PA_MAX_WRITE_BYTES" in capsys.readouterr().err


def test_main_enters_repl_with_a_valid_workspace_write_limit(route_env, monkeypatch):
    monkeypatch.setenv("PA_MAX_WRITE_BYTES", "128")
    monkeypatch.setattr("sys.stdin", StringIO(""))

    main()


def test_main_exits_nonzero_for_an_unrecognized_router_enable_shell_value(route_env, monkeypatch, capsys):
    monkeypatch.setenv("PA_ENABLE_SHELL", "true")
    monkeypatch.setattr("personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start"))

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code != 0
    message = capsys.readouterr().err
    assert "Configuration error:" in message
    assert "PA_ENABLE_SHELL" in message


def test_main_leaves_shell_unregistered_when_zero(route_env, monkeypatch):
    from personal_agent.tools import registry as tools_registry

    monkeypatch.setenv("PA_ENABLE_SHELL", "0")
    monkeypatch.setattr("sys.stdin", StringIO(""))

    main()

    assert not {"shell", "job_status", "job_stop"} & {definition.name for definition in tools_registry.TOOL_DEFS}


@pytest.mark.parametrize("value", [None, "", "1"])
def test_main_registers_shell_for_unset_empty_or_one(route_env, monkeypatch, value):
    from personal_agent.tools import registry as tools_registry

    if value is None:
        monkeypatch.delenv("PA_ENABLE_SHELL", raising=False)
    else:
        monkeypatch.setenv("PA_ENABLE_SHELL", value)
    monkeypatch.setattr("sys.stdin", StringIO(""))

    main()

    assert {"shell", "job_status", "job_stop"} <= {definition.name for definition in tools_registry.TOOL_DEFS}


def test_main_configures_shell_timeout_and_output_cap_from_the_effective_read_limit_default(route_env, monkeypatch):
    from personal_agent.providers.contract import ToolCall
    from personal_agent.tools import registry as tools_registry

    monkeypatch.setenv("PA_ENABLE_SHELL", "1")
    monkeypatch.setenv("PA_MAX_READ_BYTES", "2048")
    monkeypatch.setattr("sys.stdin", StringIO(""))

    main()

    call = ToolCall(id="1", name="shell", arguments={"command": "printf 'a%.0s' {1..3000}"})
    result = tools_registry.execute_batch([call], confirm=lambda *_args: True)[0]

    assert result.is_error is False
    assert result.content["stdout"] == "a" * 2048 + "[...truncated]"


def test_main_configures_shell_timeout_and_output_cap_from_explicit_settings(route_env, monkeypatch):
    from personal_agent.providers.contract import ToolCall
    from personal_agent.tools import registry as tools_registry

    monkeypatch.setenv("PA_ENABLE_SHELL", "1")
    monkeypatch.setenv("PA_SHELL_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("PA_SHELL_MAX_OUTPUT_BYTES", "512")
    monkeypatch.setattr("sys.stdin", StringIO(""))

    main()

    cap_call = ToolCall(id="1", name="shell", arguments={"command": "printf 'a%.0s' {1..1000}"})
    cap_result = tools_registry.execute_batch([cap_call], confirm=lambda *_args: True)[0]
    assert cap_result.is_error is False
    assert cap_result.content["stdout"] == "a" * 512 + "[...truncated]"

    timeout_call = ToolCall(id="2", name="shell", arguments={"command": "sleep 5"})
    timeout_result = tools_registry.execute_batch([timeout_call], confirm=lambda *_args: True)[0]
    assert timeout_result.is_error is True
    assert timeout_result.content["error"].startswith("command timed out after 1 seconds;")
    assert "background: true" in timeout_result.content["error"]


def test_main_exits_nonzero_for_invalid_router_shell_timeout_seconds_when_enabled(route_env, monkeypatch, capsys):
    monkeypatch.setenv("PA_ENABLE_SHELL", "1")
    monkeypatch.setenv("PA_SHELL_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.setattr("personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start"))

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code != 0
    message = capsys.readouterr().err
    assert "Configuration error:" in message
    assert "PA_SHELL_TIMEOUT_SECONDS" in message


def test_main_exits_nonzero_for_invalid_router_shell_max_output_bytes_when_enabled(route_env, monkeypatch, capsys):
    monkeypatch.setenv("PA_ENABLE_SHELL", "1")
    monkeypatch.setenv("PA_SHELL_MAX_OUTPUT_BYTES", "0")
    monkeypatch.setattr("personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start"))

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code != 0
    message = capsys.readouterr().err
    assert "Configuration error:" in message
    assert "PA_SHELL_MAX_OUTPUT_BYTES" in message


def test_main_ignores_invalid_shell_timeout_and_output_settings_when_shell_is_disabled(route_env, monkeypatch):
    monkeypatch.setenv("PA_ENABLE_SHELL", "0")
    monkeypatch.setenv("PA_SHELL_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.setenv("PA_SHELL_MAX_OUTPUT_BYTES", "not-a-number")
    monkeypatch.setattr("sys.stdin", StringIO(""))

    main()


def test_main_exits_before_repl_for_a_malformed_memory_file(route_env, monkeypatch, tmp_path, capsys):
    memory_path = tmp_path / "memory.jsonl"
    memory_path.write_text("not json\n")
    monkeypatch.setenv(memory.MEMORY_PATH_ENV_VAR, str(memory_path))
    monkeypatch.setattr("personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start"))

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code != 0
    message = capsys.readouterr().err
    assert "Configuration error" in message
    assert str(memory_path) in message


def test_main_default_memory_path_resolves_under_home(route_env, monkeypatch, tmp_path):
    monkeypatch.delenv(memory.MEMORY_PATH_ENV_VAR, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    default_path = tmp_path / ".personal_agent" / "memory.jsonl"
    default_path.parent.mkdir()
    default_path.write_text('{"text": "home note", "added": "2026-09-22T00:00:00.000Z"}\n')
    captured = {}
    monkeypatch.setattr("personal_agent.__main__.run_repl", lambda *args, **kwargs: captured.update(kwargs))
    monkeypatch.setattr("sys.stdin", StringIO(""))

    main()

    assert captured["memory_notes"] == [{"text": "home note", "added": "2026-09-22T00:00:00.000Z"}]


class _TTYStream(StringIO):
    def isatty(self):
        return True


def _capture_run_repl(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl",
        lambda *args, input_box=None, **kwargs: captured.update(input_box=input_box),
    )
    monkeypatch.setattr("personal_agent.__main__.InputBox", lambda commands: ("input box", commands))
    return captured


@pytest.mark.parametrize(
    ("stdin", "stdout", "expects_box"),
    [
        (_TTYStream(), _TTYStream(), True),
        (StringIO(), _TTYStream(), False),
        (_TTYStream(), StringIO(), False),
        (StringIO(), StringIO(), False),
    ],
)
def test_main_builds_the_input_box_only_when_stdin_and_stdout_are_ttys(
    route_env, monkeypatch, stdin, stdout, expects_box
):
    captured = _capture_run_repl(monkeypatch)
    monkeypatch.setattr("sys.stdin", stdin)
    monkeypatch.setattr("sys.stdout", stdout)

    main()

    if expects_box:
        assert captured["input_box"] == ("input box", COMMANDS)
    else:
        assert captured["input_box"] is None


# --- --resume ---------------------------------------------------------------


def _build_resumable_session(route_env, install_fake_urlopen):
    install_fake_urlopen(["first answer"])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("summarize this line\nexit\n"),
        output_stream=StringIO(),
    )
    session_id = call_log.current_session_id()
    call_log.reset_session()
    return session_id


def test_main_resume_by_id_prints_resumed_line_and_reopens_the_same_session(
    route_env, monkeypatch, install_fake_urlopen
):
    session_id = _build_resumable_session(route_env, install_fake_urlopen)
    monkeypatch.setattr("sys.stdin", StringIO("exit\n"))
    install_fake_urlopen([])
    output_stream = StringIO()
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl",
        lambda *args, **kwargs: run_repl(*args, output_stream=output_stream, **kwargs),
    )

    main(["--resume", session_id])

    assert f"Resumed session {session_id}: 1 turns." in output_stream.getvalue()
    lines = [json.loads(line) for line in Path(call_log.session_log_path(session_id)).read_text().splitlines()]
    assert [entry["type"] for entry in lines[-4:]] == [
        "session_resumed", "audit_coverage_start", "audit_coverage_end", "session_end"]
    assert call_log.current_session_id() == session_id


def test_main_resume_carries_the_conversation_summary_into_the_repl(route_env, monkeypatch, install_fake_urlopen):
    install_fake_urlopen(["a1", "a2", "a3", "THE SUMMARY"])
    run_repl(
        runtime_config.load(),
        input_stream=StringIO("refactor task one\nrefactor task two\nrefactor task three\n/compress\nexit\n"),
        output_stream=StringIO(),
    )
    session_id = call_log.current_session_id()
    call_log.reset_session()
    monkeypatch.setattr("sys.stdin", StringIO("/history\nexit\n"))
    install_fake_urlopen([])
    output_stream = StringIO()
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl",
        lambda *args, **kwargs: run_repl(*args, output_stream=output_stream, **kwargs),
    )

    main(["--resume", session_id])

    output = output_stream.getvalue()
    assert f"Resumed session {session_id}: 2 turns." in output
    assert "summary: THE SUMMARY" in output
    assert "refactor task one" not in output


def test_main_resume_last_picks_the_most_recently_started_session(route_env, monkeypatch, install_fake_urlopen):
    _build_resumable_session(route_env, install_fake_urlopen)
    # The Session Id's timestamp component has 1-second resolution (see
    # test_call_log.py); sleep past a second boundary so the second Session
    # Id sorts after the first regardless of its random suffix.
    time.sleep(1.1)
    latest_session_id = _build_resumable_session(route_env, install_fake_urlopen)
    monkeypatch.setattr("sys.stdin", StringIO("exit\n"))
    install_fake_urlopen([])

    main(["--resume", "last"])

    assert call_log.current_session_id() == latest_session_id


def test_main_without_resume_behaves_exactly_as_today(route_env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", StringIO(""))

    main([])

    captured = capsys.readouterr()
    assert "Resumed session" not in captured.out
    assert captured.err == ""
    lines = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    assert lines[0]["type"] == "session_start"
    assert lines[-1]["type"] == "session_end"
    assert not any(entry["type"] == "session_resumed" for entry in lines)


def test_main_resume_unknown_session_id_exits_nonzero_before_the_repl_and_writes_nothing(
    route_env, monkeypatch, capsys
):
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start")
    )
    session_id = "20260101T000000Z-abcdef"

    with pytest.raises(SystemExit) as exc_info:
        main(["--resume", session_id])

    assert exc_info.value.code == 1
    assert capsys.readouterr().err.strip()
    assert not Path(call_log.session_log_path(session_id)).exists()


def test_main_resume_bad_shape_session_id_is_reported_as_unknown_and_never_used_to_build_a_path(
    route_env, monkeypatch, capsys
):
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start")
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["--resume", "../../etc/passwd"])

    assert exc_info.value.code == 1
    assert "unknown session" in capsys.readouterr().err


def test_main_resume_empty_string_is_reported_as_unknown_rather_than_starting_a_new_session(
    route_env, monkeypatch, capsys
):
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start")
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["--resume", ""])

    assert exc_info.value.code == 1
    assert "unknown session" in capsys.readouterr().err


def test_main_resume_last_with_no_sessions_exits_nonzero(route_env, monkeypatch, capsys):
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start")
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["--resume", "last"])

    assert exc_info.value.code == 1
    assert capsys.readouterr().err.strip()


def test_main_resume_legacy_log_without_log_version_3_exits_nonzero_and_writes_nothing(
    route_env, monkeypatch, capsys
):
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start")
    )
    session_id = "20260101T000000Z-abcdef"
    original = json.dumps({"timestamp": "t", "session_id": session_id, "type": "session_start", "tiers": {}}) + "\n"
    log_path = Path(call_log.session_log_path(session_id))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(original)

    with pytest.raises(SystemExit) as exc_info:
        main(["--resume", session_id])

    assert exc_info.value.code == 1
    assert capsys.readouterr().err.strip()
    assert log_path.read_text() == original


def test_main_resume_malformed_json_line_exits_nonzero_and_writes_nothing(route_env, monkeypatch, capsys):
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start")
    )
    session_id = "20260101T000000Z-abcdef"
    original = (
        json.dumps(
            {"timestamp": "t", "session_id": session_id, "type": "session_start", "log_version": 3, "provider": "openrouter", "model": "m",
             **call_log.storage_identity(), "run_id": "0" * 32}
        )
        + "\n"
        + "not json\n"
    )
    log_path = Path(call_log.session_log_path(session_id))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(original)

    with pytest.raises(SystemExit) as exc_info:
        main(["--resume", session_id])

    assert exc_info.value.code == 1
    assert capsys.readouterr().err.strip()
    assert log_path.read_text() == original


def test_main_resume_non_object_json_line_exits_nonzero_and_writes_nothing(route_env, monkeypatch, capsys):
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start")
    )
    session_id = "20260101T000000Z-abcdef"
    original = (
        json.dumps(
            {"timestamp": "t", "session_id": session_id, "type": "session_start", "log_version": 3, "provider": "openrouter", "model": "m",
             **call_log.storage_identity(), "run_id": "0" * 32}
        )
        + "\n"
        + "[1, 2, 3]\n"
    )
    log_path = Path(call_log.session_log_path(session_id))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(original)

    with pytest.raises(SystemExit) as exc_info:
        main(["--resume", session_id])

    assert exc_info.value.code == 1
    assert capsys.readouterr().err.strip()
    assert log_path.read_text() == original


def test_main_resume_ok_turn_end_missing_messages_exits_nonzero_and_writes_nothing(route_env, monkeypatch, capsys):
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start")
    )
    session_id = "20260101T000000Z-abcdef"
    original = (
        json.dumps(
            {"timestamp": "t", "session_id": session_id, "type": "session_start", "log_version": 3, "provider": "openrouter", "model": "m",
             **call_log.storage_identity(), "run_id": "0" * 32}
        )
        + "\n"
        + json.dumps({"timestamp": "t", "session_id": session_id, "type": "turn_end", "status": "ok"})
        + "\n"
    )
    log_path = Path(call_log.session_log_path(session_id))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(original)

    with pytest.raises(SystemExit) as exc_info:
        main(["--resume", session_id])

    assert exc_info.value.code == 1
    assert capsys.readouterr().err.strip()
    assert log_path.read_text() == original


def test_main_resume_compressed_entry_without_a_summary_exits_nonzero_and_writes_nothing(
    route_env, monkeypatch, capsys
):
    monkeypatch.setattr(
        "personal_agent.__main__.run_repl", lambda *args, **kwargs: pytest.fail("REPL should not start")
    )
    session_id = "20260101T000000Z-abcdef"
    original = (
        json.dumps(
            {"timestamp": "t", "session_id": session_id, "type": "session_start", "log_version": 3, "provider": "openrouter", "model": "m",
             **call_log.storage_identity(), "run_id": "0" * 32}
        )
        + "\n"
        + json.dumps({"timestamp": "t", "session_id": session_id, "type": "conversation_compressed"})
        + "\n"
    )
    log_path = Path(call_log.session_log_path(session_id))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(original)

    with pytest.raises(SystemExit) as exc_info:
        main(["--resume", session_id])

    assert exc_info.value.code == 1
    assert capsys.readouterr().err.strip()
    assert log_path.read_text() == original


@pytest.mark.parametrize(
    "error, line",
    [
        (call_log.AuditError("audit down"), "Fatal audit error: audit down"),
        (call_log.PersistenceError("restore failed"), "Fatal persistence error: restore failed"),
        (OSError("disk full"), "Fatal persistence error: disk full"),
    ],
)
def test_main_reports_fatal_run_repl_failures_without_a_traceback(route_env, monkeypatch, capsys, error, line):
    def failing_run_repl(*args, **kwargs):
        raise error

    monkeypatch.setattr("personal_agent.__main__.run_repl", failing_run_repl)

    with pytest.raises(SystemExit) as exit_info:
        main()

    captured = capsys.readouterr()
    assert exit_info.value.code == 1
    assert captured.err == line + "\n"
    assert "Traceback" not in captured.err
