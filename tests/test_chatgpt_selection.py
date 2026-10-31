import json
from io import StringIO
from pathlib import Path

from personal_agent import call_log, chatgpt_auth
from personal_agent.routing import runtime_config
from personal_agent.terminal.repl import run_repl
from tests.test_chatgpt_auth import oauth


class Box:
    def __init__(self, commands, choices):
        self.commands = iter(commands)
        self.choices = iter(choices)
        self.prompts = []

    def read(self):
        return next(self.commands)

    def choose(self, title, choices):
        self.prompts.append((title, choices))
        return next(self.choices)


def run(monkeypatch, auth, box=None, text=""):
    monkeypatch.setattr(chatgpt_auth, "ChatGPTAuth", lambda: auth)
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO(text), input_box=box, output_stream=output)
    return output.getvalue()


def test_connect_requires_plan_notice_and_deliberate_model_selection(oauth, monkeypatch, route_env):
    auth, state = oauth
    box = Box(["/connect chatgpt", "/model", "/exit"], [0, 0])
    output = run(monkeypatch, auth, box)
    assert "Selected chatgpt exact-1" in output
    assert "Manage usage" in output and chatgpt_auth.USAGE_URL in output
    assert auth.status().acknowledged
    assert auth.status().selected_model == "exact-1"
    assert "PA_PROVIDER=chatgpt\nPA_MODEL=exact-1\n" in (Path.home() / ".personal_agent/.env").read_text()
    assert "access-fixture" not in output
    assert len(box.prompts) == 2


def test_cancelled_picker_keeps_api_pair_and_successful_signin(oauth, monkeypatch, route_env):
    auth, state = oauth
    box = Box(["/connect chatgpt", "/model", "/exit"], [0, None])
    output = run(monkeypatch, auth, box)
    assert "Provider/model: openrouter vendor/test-model" in output
    assert auth.status().connected
    assert not (Path.home() / ".personal_agent/.env").exists()


def test_noninteractive_connect_and_disconnected_selection_never_open_browser(oauth, monkeypatch, route_env):
    auth, state = oauth
    output = run(monkeypatch, auth, text="/connect chatgpt\n/model chatgpt exact-1\n/models chatgpt\n/exit\n")
    assert "interactive" in output
    assert not state["requests"] and "authorize" not in state


def test_unconfigured_repl_never_dispatches_or_fabricates_route(monkeypatch):
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("task\n/model\n/exit\n"), output_stream=output)
    assert "PA_PROVIDER is required" in output.getvalue()
    entries = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    assert entries[0]["provider"] is None and entries[0]["model"] is None
    assert not any(entry["type"] == "routed_task_submitted" for entry in entries)
    call_log.load_conversation(call_log.current_session_id())


def test_pair_save_failure_preserves_active_saved_pair_and_signin(oauth, monkeypatch, route_env):
    from personal_agent.routing import config_store
    auth, state = oauth
    saved = Path.home() / ".personal_agent/.env"
    saved.parent.mkdir(mode=0o700)
    before = "PA_PROVIDER=openrouter\nPA_MODEL=vendor/test-model\nOPENROUTER_API_KEY=api-kept\n"
    saved.write_text(before)
    monkeypatch.setattr(config_store, "save_settings", lambda settings: (_ for _ in ()).throw(OSError("disk full")))
    box = Box(["/connect chatgpt", "/model", "/exit"], [0, 0])
    output = run(monkeypatch, auth, box)
    assert "Provider/model: openrouter vendor/test-model" in output
    assert saved.read_text() == before
    assert auth.status().connected and auth.status().selected_model is None


def test_successful_signin_survives_model_list_failure(oauth, monkeypatch, route_env):
    auth, state = oauth
    original = auth.transport
    def failing(url, **kwargs):
        if url == chatgpt_auth.MODELS:
            raise chatgpt_auth.TemporaryError("models unavailable")
        return original(url, **kwargs)
    auth.transport = failing
    box = Box(["/connect chatgpt", "/model", "/exit"], [0])
    output = run(monkeypatch, auth, box)
    assert "models unavailable" in output and "Provider/model: openrouter vendor/test-model" in output
    assert auth.status().connected and auth.status().acknowledged
    assert not (Path.home() / ".personal_agent/.env").exists()


def test_exact_noninteractive_selection_reuses_acknowledged_authorization(oauth, monkeypatch, route_env):
    auth, state = oauth
    binding = auth.connect()
    auth.acknowledge(binding)
    auth.browser = lambda url: (_ for _ in ()).throw(AssertionError("unexpected browser"))
    from tests.test_chatgpt_provider import completed, message
    from tests.test_streaming import install_stream
    response, requests = install_stream(monkeypatch, [completed([message("account answer")])])
    output = run(monkeypatch, auth, text="/model chatgpt exact-1\ntask\n/disconnect chatgpt\n/model\n/exit\n")
    assert "Selected chatgpt exact-1" in output
    assert "account answer" in output and len(requests) == 1 and response.closed
    assert "Provider/model: chatgpt exact-1" in output
    assert not auth.status().connected


def test_first_notice_blocks_noninteractive_exact_selection(oauth, monkeypatch, route_env):
    auth, state = oauth
    auth.connect()
    output = run(monkeypatch, auth, text="/model chatgpt exact-1\n/exit\n")
    assert "interactive" in output
    assert not auth.status().acknowledged and auth.status().selected_model is None


def test_api_route_echo_of_current_and_retired_oauth_tokens_is_redacted(oauth, monkeypatch, route_env, install_fake_urlopen):
    auth, state = oauth
    auth.connect()
    record = json.loads(auth.path.read_bytes())
    record["session"]["expires_at"] = 0
    auth.path.write_text(json.dumps(record))
    original = auth.transport
    def rotating(url, **kwargs):
        data = original(url, **kwargs)
        if url == chatgpt_auth.TOKEN:
            data.update(access_token="new-access-fixture", refresh_token="new-refresh-fixture")
        return data
    auth.transport = rotating
    calls = install_fake_urlopen(["access-fixture refresh-fixture new-access-fixture new-refresh-fixture"])
    box = Box(["/connect chatgpt", "/model openrouter vendor/test-model", "task", "/exit"], [0, None])
    output = run(monkeypatch, auth, box)
    assert len(calls) == 1 and "[redacted]" in output
    log = Path(call_log.session_log_path()).read_text()
    for secret in ("access-fixture", "refresh-fixture", "new-access-fixture", "new-refresh-fixture"):
        assert secret not in output and secret not in log


def test_connect_now_cancellation_never_launches_browser(oauth, monkeypatch, route_env):
    auth, state = oauth
    box = Box(["/model chatgpt exact-1", "/exit"], [None])
    run(monkeypatch, auth, box)
    assert "authorize" not in state
    assert not auth.status().connected


def test_listing_cli_uses_only_account_catalog_and_never_launches_browser(oauth, monkeypatch, capsys):
    from personal_agent.__main__ import main
    auth, state = oauth
    binding = auth.connect()
    auth.acknowledge(binding)
    auth.browser = lambda url: (_ for _ in ()).throw(AssertionError("unexpected browser"))
    monkeypatch.setattr(chatgpt_auth, "ChatGPTAuth", lambda: auth)
    main(["--models", "chatgpt", "--search", "One"])
    assert "exact-1  Model One" in capsys.readouterr().out


def test_unconfigured_repl_usage_report_and_model_commands_are_local():
    output = StringIO()
    run_repl(runtime_config.load(), input_stream=StringIO("/usage\n/report\n/model\n/exit\n"), output_stream=output)
    assert "Route unready" in output.getvalue()
