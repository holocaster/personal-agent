import json
import os
from io import StringIO
from pathlib import Path

import pytest

from personal_agent import call_log
from personal_agent.routing import runtime_config
from personal_agent.routing import config_store
from personal_agent.terminal.repl import run_repl


class _ScriptedInputBox:
    def __init__(self, reads, answers, secret_answers=()):
        self._reads = iter(reads)
        self._answers = iter(answers)
        self._secret_answers = iter(secret_answers)
        self.secret_questions = []

    def read(self):
        return next(self._reads)

    def ask(self, question):
        return next(self._answers)

    def ask_secret(self, question):
        self.secret_questions.append(question)
        return next(self._secret_answers)


def test_tool_round_limit_survives_runtime_edits_and_resets_per_task(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setenv("PA_MAX_TOOL_ROUNDS", "2")
    tool_call = {"tool_calls": [{"id": "call", "name": "calculator", "arguments": {"expression": "1+1"}}]}
    calls = install_fake_urlopen([tool_call] * 3 + [tool_call] * 2 + ["done"])
    box = _ScriptedInputBox(["/config", "first", "second", "exit"], ["context", "budget", "350000", "done"])
    output = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO(""), input_box=box, output_stream=output)

    assert len(calls) == 6
    assert "Tool loop exceeded the 2-round limit" in output.getvalue()
    assert "llm> done" in output.getvalue()
    assert all(json.loads(call["request"].data)["model"] == "vendor/test-model" for call in calls)


def test_context_config_persists_exact_identity_and_survives_unrelated_edits(route_env, install_fake_urlopen, tmp_path):
    calls = install_fake_urlopen(["answer"])
    box = _ScriptedInputBox(["/config", "summarize task", "/usage", "exit"], [
        "context", "budget", "350000", "context", "override", '{"total_tokens":300000,"output_tokens":12000}',
        "key", "openrouter", "done"], ["new-key"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(""), input_box=box, output_stream=output)
    payload = json.loads(calls[0]["request"].data)
    assert payload["max_tokens"] == 12000
    assert "configured context budget: 350000" in output.getvalue()
    assert "capacity: manual 300000" in output.getvalue()
    saved = config_store.read_env_values(tmp_path / ".personal_agent" / ".env")
    assert saved["PA_CONTEXT_BUDGET_TOKENS"] == "350000"
    assert json.loads(saved["PA_CONTEXT_CAPACITY_OVERRIDES"]) == [
        {"provider": "openrouter", "model": "vendor/test-model", "total_tokens": 300000, "output_tokens": 12000}]
    assert saved["OPENROUTER_API_KEY"] == "new-key"


def test_override_targets_the_current_pair_and_a_restarted_pair_keeps_inactive_identity(
    route_env, install_fake_urlopen, monkeypatch
):
    calls = install_fake_urlopen(["first", "second"])
    box = _ScriptedInputBox(["/config", "first", "exit"], [
        "context", "override", '{"total_tokens":300000,"output_tokens":4000}', "done"])
    run_repl(runtime_config.load(), input_stream=StringIO(""), input_box=box, output_stream=StringIO())
    saved = config_store.read_env_values()
    monkeypatch.setenv("PA_MODEL", "vendor/other-model")
    monkeypatch.setenv("PA_CONTEXT_CAPACITY_OVERRIDES", saved["PA_CONTEXT_CAPACITY_OVERRIDES"])
    call_log.reset_session()
    run_repl(runtime_config.load(), input_stream=StringIO("second\nexit\n"), output_stream=StringIO())
    bodies = [json.loads(call["request"].data) for call in calls]
    assert [(body["model"], body["max_tokens"]) for body in bodies] == [
        ("vendor/test-model", 4000), ("vendor/other-model", 16000)]
    assert json.loads(saved["PA_CONTEXT_CAPACITY_OVERRIDES"]) == [
        {"provider": "openrouter", "model": "vendor/test-model", "total_tokens": 300000, "output_tokens": 4000}]


@pytest.mark.parametrize("action", ["remove", "reset"])
def test_context_override_removal_preserves_other_records_or_resets_all(route_env, install_fake_urlopen, action):
    config = runtime_config.load()
    records = [{"provider": "openrouter", "model": "vendor/test-model", "total_tokens": 250000},
               {"provider": "openai", "model": "inactive", "total_tokens": 200000}]
    from dataclasses import replace
    config = replace(config, capacity_overrides=tuple(records))
    answers = ["context", action, "done"]
    install_fake_urlopen([])
    run_repl(config, input_stream=StringIO(""), input_box=_ScriptedInputBox(["/config", "exit"], answers), output_stream=StringIO())
    saved = json.loads(config_store.read_env_values()["PA_CONTEXT_CAPACITY_OVERRIDES"])
    assert saved == (records[1:] if action == "remove" else [])
    assert list(config.capacity_overrides) == records


@pytest.mark.parametrize("answers", [
    ["context", "budget", "0", "done"], ["context", "override", '{"total_tokens":true}', "done"],
    ["context", "override", '{"total_tokens":300000,"input_tokens":400000}', "done"],
    ["context", "cancel", "done"], ["context", "override", "not JSON", "done"]])
def test_invalid_or_cancelled_context_edit_changes_neither_active_nor_saved(
    route_env, install_fake_urlopen, tmp_path, answers
):
    path = tmp_path / ".personal_agent" / ".env"
    path.parent.mkdir()
    original = "UNRELATED=keep\nPA_CONTEXT_BUDGET_TOKENS=250000\n"
    path.write_text(original)
    calls = install_fake_urlopen(["answer"])
    box = _ScriptedInputBox(["/config", "summarize task", "/usage", "exit"], answers)
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(""), input_box=box, output_stream=output)
    assert len(calls) == 1
    assert "configured context budget: 250000" in output.getvalue()
    assert path.read_text() == original


def test_usage_distinguishes_new_configured_budget_from_last_task_snapshot(route_env, install_fake_urlopen):
    install_fake_urlopen(["answer"])
    box = _ScriptedInputBox(["summarize task", "/config", "/usage", "exit"], ["context", "budget", "350000", "done"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(""), input_box=box, output_stream=output)
    assert "configured context budget: 350000" in output.getvalue()
    assert "task snapshot context budget: 250000" in output.getvalue()


def test_context_save_failure_and_override_source_notice(route_env, install_fake_urlopen, tmp_path, monkeypatch):
    path = tmp_path / ".personal_agent" / ".env"
    path.parent.mkdir()
    original = 'PA_CONTEXT_BUDGET_TOKENS=300000\nPA_CONTEXT_CAPACITY_OVERRIDES=[]\n'
    path.write_text(original)
    monkeypatch.setattr(config_store.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    install_fake_urlopen([])
    box = _ScriptedInputBox(["/config", "/usage", "exit"], ["context", "budget", "350000", "done"])
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(""), input_box=box, output_stream=output,
             config_sources={"PA_CONTEXT_BUDGET_TOKENS": "exported environment",
                             "PA_CONTEXT_CAPACITY_OVERRIDES": "current-directory .env"})
    assert "configured context budget: 250000" in output.getvalue()
    assert "active configuration was not changed" in output.getvalue()
    assert "PA_CONTEXT_BUDGET_TOKENS saved in home .env is overridden by exported environment" in output.getvalue()
    assert "PA_CONTEXT_CAPACITY_OVERRIDES saved in home .env is overridden by current-directory .env" in output.getvalue()
    assert path.read_text() == original


def test_piped_config_refuses_without_mutating_and_continues_the_repl(
    route_env, install_fake_urlopen, tmp_path
):
    calls = install_fake_urlopen(["the answer"])
    home_env = tmp_path / ".personal_agent" / ".env"
    home_env.parent.mkdir()
    original = "TIER_EASY_MODEL=saved-model\nUNRELATED=keep\n"
    home_env.write_text(original)
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO("/config extra\n/config\nsummarize this line\nexit\n"),
        output_stream=output_stream,
    )

    assert "/config requires an interactive terminal" in output_stream.getvalue()
    assert "/config takes no arguments" in output_stream.getvalue()
    assert "llm> the answer\n" in output_stream.getvalue()
    assert len(calls) == 1
    assert home_env.read_text() == original


def test_config_store_updates_only_the_selected_settings_and_preserves_unrelated_lines(tmp_path):
    home_env = tmp_path / ".personal_agent" / ".env"
    home_env.parent.mkdir()
    original = (
        "# existing settings\n"
        "UNRELATED=value=with-equals\n"
        "TIER_EASY_MODEL=old-model\n"
        "PA_MODEL=old-model\n"
        "OPENROUTER_API_KEY=old-key\n"
    )
    home_env.write_text(original)

    config_store.save_settings({"PA_MODEL": "new-model", "ANTHROPIC_API_KEY": "new-key"}, path=home_env)

    assert home_env.read_text() == original.replace("PA_MODEL=old-model", "PA_MODEL=new-model") + "ANTHROPIC_API_KEY=new-key\n"
    assert config_store.read_env_values(home_env) == {
        "UNRELATED": "value=with-equals", "TIER_EASY_MODEL": "old-model", "PA_MODEL": "new-model",
        "OPENROUTER_API_KEY": "old-key", "ANTHROPIC_API_KEY": "new-key"}


@pytest.mark.parametrize("variable", ["TIER_EASY_MODEL", "TIER_COMPLEX_PROVIDER", "UNRELATED"])
def test_config_store_never_writes_old_tier_or_unmanaged_settings(tmp_path, variable):
    home_env = tmp_path / ".personal_agent" / ".env"

    with pytest.raises(ValueError, match="unsupported configuration setting"):
        config_store.save_settings({variable: "value"}, path=home_env)

    assert not home_env.exists()


@pytest.mark.parametrize(("variable", "value"), [("PA_PROVIDER", "gemini"), ("OPENAI_API_KEY", "new-api-key")])
def test_config_store_creates_parent_and_owner_only_file_on_posix(tmp_path, variable, value):
    home_env = tmp_path / ".personal_agent" / ".env"

    config_store.save_settings({variable: value}, path=home_env)

    assert config_store.read_env_values(home_env) == {variable: value}
    if os.name == "posix":
        assert home_env.stat().st_mode & 0o777 == 0o600
        assert home_env.parent.stat().st_mode & 0o777 == 0o700


def test_config_menu_rejects_unknown_and_tier_options_without_saving(route_env, install_fake_urlopen, tmp_path):
    calls = install_fake_urlopen(["answer"])
    home_env = tmp_path / ".personal_agent" / ".env"
    home_env.parent.mkdir()
    home_env.write_text("UNRELATED=keep\n")
    box = _ScriptedInputBox(["/config", "task", "exit"], ["easy", "tier", "provider", "done"])
    output = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO(""), output_stream=output, input_box=box)

    text = output.getvalue()
    assert "Provider/model: openrouter vendor/test-model (change with model; search with models)" in text
    assert text.count("Error: choose model, models, context, key, or done.") == 3
    assert json.loads(calls[0]["request"].data)["model"] == "vendor/test-model"
    assert home_env.read_text() == "UNRELATED=keep\n"
    assert "test-key" not in text


@pytest.mark.parametrize(
    ("provider", "variable", "url", "header", "prefix"),
    [
        ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/chat/completions", "Authorization", "Bearer "),
        ("anthropic", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/messages", "X-api-key", ""),
        ("openai", "OPENAI_API_KEY", "https://api.openai.com/v1/chat/completions", "Authorization", "Bearer "),
        ("gemini", "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/models/vendor/test-model:streamGenerateContent?alt=sse", "X-goog-api-key", ""),
    ],
)
def test_standalone_key_update_for_each_provider_is_saved_and_used_in_this_run(
    route_env, install_fake_urlopen, tmp_path, caplog, monkeypatch, provider, variable, url, header, prefix
):
    monkeypatch.setenv("PA_PROVIDER", provider)
    calls = install_fake_urlopen(["the answer"])
    home_env = tmp_path / ".personal_agent" / ".env"
    home_env.parent.mkdir()
    home_env.write_text("UNRELATED=keep\n")
    secret = f"{provider}-runtime-secret"
    input_box = _ScriptedInputBox(
        ["/config", "summarize this line", "exit"],
        ["key", provider, "done"],
        [secret],
    )
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO(""), output_stream=output_stream, input_box=input_box)

    assert len(calls) == 1
    request = calls[0]["request"]
    assert request.full_url == url
    assert request.get_header(header) == f"{prefix}{secret}"
    assert config_store.read_env_values(home_env) == {"UNRELATED": "keep", variable: secret}
    log_text = Path(call_log.session_log_path()).read_text()
    assert secret not in output_stream.getvalue()
    assert secret not in caplog.text
    assert secret not in log_text
    assert f"{provider}: available (this Run)" in output_stream.getvalue()


def test_provider_errors_do_not_echo_the_entered_key_to_output_logs_or_call_log(
    route_env, install_fake_urlopen, tmp_path, caplog
):
    secret = "sensitive-provider-key"
    calls = install_fake_urlopen([ValueError(f"provider rejected {secret}")])
    home_env = tmp_path / ".personal_agent" / ".env"
    home_env.parent.mkdir()
    input_box = _ScriptedInputBox(
        ["/config", "summarize this line", "exit"],
        ["key", "openrouter", "done"],
        [secret],
    )
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO(""), output_stream=output_stream, input_box=input_box)

    log_text = Path(call_log.session_log_path()).read_text()
    assert len(calls) == 1
    assert "[redacted]" in output_stream.getvalue()
    assert secret not in output_stream.getvalue()
    assert secret not in caplog.text
    assert secret not in log_text


@pytest.mark.parametrize("secret", ["test-key", "openai-runtime-secret"])
def test_successful_provider_response_reflecting_an_active_key_is_redacted(
    route_env, install_fake_urlopen, monkeypatch, caplog, secret
):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-runtime-secret")
    install_fake_urlopen(secret)
    input_box = _ScriptedInputBox(["summarize this line", "exit"], [])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(""),
        output_stream=output_stream,
        input_box=input_box,
    )

    log_text = Path(call_log.session_log_path()).read_text()
    entries = [json.loads(line) for line in log_text.splitlines()]
    attempt = next(entry for entry in entries if entry["type"] == "attempt")
    turn_end = next(entry for entry in entries if entry["type"] == "turn_end")
    assistant_message = next(message for message in turn_end["messages"] if message["role"] == "assistant")
    assert "llm> [redacted]" in output_stream.getvalue()
    assert secret not in output_stream.getvalue()
    assert secret not in caplog.text
    assert secret not in log_text
    assert attempt["answer"] == "[redacted]"
    assert assistant_message["content"] == "[redacted]"


@pytest.mark.parametrize("is_error", [False, True])
def test_replaced_key_is_redacted_from_later_provider_response_and_logs(
    route_env, install_fake_urlopen, caplog, is_error
):
    previous = "previous-entered-SECRET"
    current = "current-entered-SECRET"
    response = f"provider reflected {previous}"
    calls = install_fake_urlopen([ValueError(response) if is_error else response])
    input_box = _ScriptedInputBox(
        ["/config", "/config", "summarize this line", "exit"],
        ["key", "openrouter", "done", "key", "openrouter", "done"],
        [previous, current],
    )
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO(""), output_stream=output_stream, input_box=input_box)

    entries = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    attempt = next(entry for entry in entries if entry["type"] == "attempt")
    turn_end = next(entry for entry in entries if entry["type"] == "turn_end")
    assert calls[0]["request"].get_header("Authorization") == f"Bearer {current}"
    assert "provider reflected [redacted]" in output_stream.getvalue()
    assert previous not in output_stream.getvalue()
    assert previous not in caplog.text
    assert previous not in Path(call_log.session_log_path()).read_text()
    if is_error:
        assert "[redacted]" in attempt["error"]
        assert "[redacted]" in turn_end["error"]
    else:
        assert attempt["answer"] == "provider reflected [redacted]"
        assert turn_end["messages"][-1]["content"] == "provider reflected [redacted]"


def test_replaced_key_is_redacted_from_later_compression_and_log(
    route_env, install_fake_urlopen, caplog
):
    previous = "previous-compression-SECRET"
    current = "current-compression-SECRET"
    calls = install_fake_urlopen(["one", "two", "three", f"summary reflected {previous}"])
    input_box = _ScriptedInputBox(
        [
            "/config", "summarize this line", "summarize this other line", "summarize one more line",
            "/config", "/compress", "exit",
        ],
        ["key", "openrouter", "done", "key", "openrouter", "done"],
        [previous, current],
    )
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO(""), output_stream=output_stream, input_box=input_box)

    log_text = Path(call_log.session_log_path()).read_text()
    entries = [json.loads(line) for line in log_text.splitlines()]
    compression_attempt = [entry for entry in entries if entry["type"] == "attempt"][-1]
    compressed = next(entry for entry in entries if entry["type"] == "conversation_compressed")
    assert calls[-1]["request"].get_header("Authorization") == f"Bearer {current}"
    assert compression_attempt["answer"] == "summary reflected [redacted]"
    assert compressed["summary"] == "summary reflected [redacted]"
    assert previous not in output_stream.getvalue()
    assert previous not in caplog.text
    assert previous not in log_text


def test_replaced_startup_key_is_still_redacted_in_the_same_run(route_env, install_fake_urlopen):
    install_fake_urlopen("test-key")
    input_box = _ScriptedInputBox(
        ["/config", "summarize this line", "exit"],
        ["key", "openrouter", "done"],
        ["new-entered-SECRET"],
    )
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO(""), output_stream=output_stream, input_box=input_box)

    assert "llm> [redacted]" in output_stream.getvalue()
    assert "test-key" not in output_stream.getvalue()
    assert "test-key" not in Path(call_log.session_log_path()).read_text()


@pytest.mark.parametrize(("secret_answer", "expected_message"), [("", "API key cannot be empty"), (None, "cancelled")])
def test_empty_or_cancelled_standalone_key_input_leaves_runtime_and_home_file_unchanged(
    route_env, install_fake_urlopen, tmp_path, secret_answer, expected_message
):
    calls = install_fake_urlopen(["the answer"])
    home_env = tmp_path / ".personal_agent" / ".env"
    home_env.parent.mkdir()
    original = "UNRELATED=keep\nOPENROUTER_API_KEY=saved-key\n"
    home_env.write_text(original)
    input_box = _ScriptedInputBox(
        ["/config", "summarize this line", "exit"],
        ["key", "openrouter", "done"],
        [secret_answer],
    )
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO(""), output_stream=output_stream, input_box=input_box)

    assert len(calls) == 1
    assert calls[0]["request"].get_header("Authorization") == "Bearer test-key"
    assert home_env.read_text() == original
    assert expected_message in output_stream.getvalue()


def test_failed_standalone_key_save_does_not_activate_the_new_key(
    route_env, install_fake_urlopen, monkeypatch, tmp_path
):
    calls = install_fake_urlopen(["the answer"])
    home_env = tmp_path / ".personal_agent" / ".env"
    home_env.parent.mkdir()
    original = "UNRELATED=keep\nOPENROUTER_API_KEY=saved-key\n"
    home_env.write_text(original)

    def fail_replace(*_args):
        raise OSError("disk full")

    monkeypatch.setattr("personal_agent.routing.config_store.os.replace", fail_replace)
    secret = "unsaved-runtime-key"
    input_box = _ScriptedInputBox(
        ["/config", "summarize this line", "exit"],
        ["key", "openrouter", "done"],
        [secret],
    )
    output_stream = StringIO()

    run_repl(runtime_config.load(), input_stream=StringIO(""), output_stream=output_stream, input_box=input_box)

    assert len(calls) == 1
    assert calls[0]["request"].get_header("Authorization") == "Bearer test-key"
    assert "could not save API key" in output_stream.getvalue()
    assert secret not in output_stream.getvalue()
    assert secret not in Path(call_log.session_log_path()).read_text()
    assert home_env.read_text() == original


def test_standalone_key_update_is_used_by_later_compression_calls(route_env, install_fake_urlopen):
    calls = install_fake_urlopen(["answer one", "answer two", "answer three", "summary"])
    secret = "new-openrouter-secret"
    input_box = _ScriptedInputBox(
        [
            "/config",
            "summarize this line",
            "summarize this other line",
            "summarize one more line",
            "/compress",
            "exit",
        ],
        ["key", "openrouter", "done"],
        [secret],
    )

    run_repl(runtime_config.load(), input_stream=StringIO(""), output_stream=StringIO(), input_box=input_box)

    assert len(calls) == 4
    assert [call["request"].get_header("Authorization") for call in calls] == [f"Bearer {secret}"] * 4


def test_config_menu_names_the_higher_precedence_source_overriding_saved_values(
    route_env, install_fake_urlopen, monkeypatch, tmp_path
):
    install_fake_urlopen([])
    monkeypatch.setenv("PA_MODEL", "exported-model")
    monkeypatch.setenv("PA_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-exported-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-cwd-secret")
    home_env = tmp_path / ".personal_agent" / ".env"
    home_env.parent.mkdir()
    home_env.write_text(
        "PA_MODEL=home-model\n"
        "PA_PROVIDER=gemini\n"
        "OPENAI_API_KEY=home-openai-secret\n"
        "ANTHROPIC_API_KEY=home-anthropic-secret\n"
    )
    input_box = _ScriptedInputBox(["/config", "exit"], ["done"])
    output_stream = StringIO()

    run_repl(
        runtime_config.load(),
        input_stream=StringIO(""),
        output_stream=output_stream,
        input_box=input_box,
        config_sources={
            "PA_MODEL": "exported environment",
            "PA_PROVIDER": "current-directory .env",
            "OPENAI_API_KEY": "exported environment",
            "ANTHROPIC_API_KEY": "current-directory .env",
        },
    )

    output = output_stream.getvalue()
    assert "PA_MODEL saved in home .env is overridden by exported environment." in output
    assert "PA_PROVIDER saved in home .env is overridden by current-directory .env." in output
    assert "Provider/model: openrouter exported-model" in output
    assert "openai: available (exported environment)" in output
    assert "OPENAI_API_KEY saved in home .env is overridden by exported environment." in output
    assert "anthropic: available (current-directory .env)" in output
    assert "ANTHROPIC_API_KEY saved in home .env is overridden by current-directory .env." in output
    assert "openai-exported-secret" not in output
    assert "home-openai-secret" not in output
    assert "anthropic-cwd-secret" not in output
    assert "home-anthropic-secret" not in output
