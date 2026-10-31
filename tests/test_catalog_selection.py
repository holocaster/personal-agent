import json
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from personal_agent import call_log, model_catalog
from personal_agent.__main__ import main
from personal_agent.routing import config_store, runtime_config
from personal_agent.terminal.repl import run_repl
from tests.fakes import FakeCatalogResponse, synthetic_models_dev


class Box:
    def __init__(self, reads, answers=(), secrets=()):
        self.reads = iter(reads)
        self.answers = iter(answers)
        self.secrets = iter(secrets)
        self.footer = None

    def read(self):
        return next(self.reads)

    def ask(self, question):
        answer = next(self.answers)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def ask_secret(self, question):
        return next(self.secrets)


def _run(text=None, box=None, config=None):
    output = StringIO()
    run_repl(config or runtime_config.load(), input_stream=StringIO(text or ""), input_box=box, output_stream=output)
    return output.getvalue()


def _entries():
    return [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]


def _routes(calls):
    return [(call["request"].full_url, json.loads(call["request"].data)["model"]) for call in calls]


def _saved():
    return config_store.read_env_values()


def _home_env():
    return Path.home() / ".personal_agent" / ".env"


OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
OPENAI = "https://api.openai.com/v1/chat/completions"


@pytest.fixture
def openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")


@pytest.fixture
def refresh_with(monkeypatch):
    def install(*outcomes):
        requests = []

        def fake_open(request, timeout=None):
            requests.append(request)
            outcome = outcomes[len(requests) - 1]
            if isinstance(outcome, BaseException):
                raise outcome
            return FakeCatalogResponse(outcome)

        monkeypatch.setattr(model_catalog, "_open", fake_open)
        return requests

    return install


def test_model_selection_saves_the_pair_atomically_and_applies_from_the_next_task(
    route_env, openai_key, install_fake_urlopen
):
    _home_env().parent.mkdir(mode=0o700, exist_ok=True)
    _home_env().write_text("# keep\nOTHER=1\nPA_MODEL=old\n")
    calls = install_fake_urlopen(["first", "second"])

    output = _run("first\n/model OpenAI vendor/new\nsecond\nexit\n")

    assert _routes(calls) == [(OPENROUTER, "vendor/test-model"), (OPENAI, "vendor/new")]
    assert "Selected openai vendor/new; saved for later Runs and used from the next task or /retry." in output
    assert "Catalog metadata does not prove account access" in output
    assert _home_env().read_text() == "# keep\nOTHER=1\nPA_MODEL=vendor/new\nPA_PROVIDER=openai\n"
    openings = [entry for entry in _entries() if entry["type"] == "routed_task_submitted"]
    assert [(entry["provider"], entry["model"]) for entry in openings] == [
        ("openrouter", "vendor/test-model"), ("openai", "vendor/new")]
    audit = [entry for entry in _entries() if entry.get("name") == "/model"]
    assert audit[-1]["old"] == "openrouter vendor/test-model" and audit[-1]["new"] == "openai vendor/new"
    assert "openai-key" not in json.dumps(_entries())


@pytest.mark.parametrize("starting_provider", ["chatgpt", "openrouter"])
@pytest.mark.parametrize("via_config", [False, True])
def test_api_selection_admits_next_task_after_loading_catalog(
    route_env, refresh_with, install_fake_urlopen, monkeypatch, starting_provider, via_config
):
    monkeypatch.setenv("PA_PROVIDER", starting_provider)
    model_catalog.cache_path().unlink()
    document = synthetic_models_dev(["vendor/test-model"])
    outcomes = [document] if starting_provider == "chatgpt" else [
        HTTPError(model_catalog.URL, 503, "down", None, None), document]
    refresh_with(*outcomes)
    calls = install_fake_urlopen(["answer"])

    if via_config:
        output = _run(box=Box(["/config", "task", "exit"], ["model", "openrouter vendor/test-model", "done"]))
    else:
        output = _run("/model openrouter vendor/test-model\ntask\nexit\n")

    assert "Selected openrouter vendor/test-model" in output
    assert _routes(calls) == [(OPENROUTER, "vendor/test-model")]
    assert "llm> answer" in output
    opening = next(entry for entry in _entries() if entry["type"] == "routed_task_submitted")
    assert (opening["provider"], opening["model"]) == ("openrouter", "vendor/test-model")


@pytest.mark.parametrize("via_config", [False, True])
def test_listing_restores_catalog_admission_after_initial_fetch_failure(
    route_env, refresh_with, install_fake_urlopen, via_config
):
    model_catalog.cache_path().unlink()
    refresh_with(HTTPError(model_catalog.URL, 503, "down", None, None),
                 synthetic_models_dev(["vendor/test-model"]))
    calls = install_fake_urlopen(["answer"])

    if via_config:
        output = _run(box=Box(["/config", "task", "exit"], ["models", "openrouter", "done"]))
    else:
        output = _run("/models openrouter\ntask\nexit\n")

    assert "Models.dev openrouter catalog fetched" in output
    assert _routes(calls) == [(OPENROUTER, "vendor/test-model")]
    assert not _home_env().exists()


@pytest.mark.parametrize("command,message", [
    ("/model google vendor/new", "Unknown Provider 'google'; choose one of: openrouter, openai, anthropic, gemini"),
    ("/model openrouter vendor/absent", "Model 'vendor/absent' is not in the Models.dev catalog for openrouter"),
    ("/model openrouter VENDOR/NEW", "Model 'VENDOR/NEW' is not in the Models.dev catalog for openrouter"),
    ("/model anthropic vendor/new", "ANTHROPIC_API_KEY is required for provider 'anthropic'; set it with /config key."),
])
def test_invalid_selection_keeps_active_and_saved_pair(route_env, install_fake_urlopen, command, message):
    calls = install_fake_urlopen(["answer"])

    output = _run(f"{command}\ntask\nexit\n")

    assert f"Error: {message}" in output and "Active and saved pair unchanged." in output
    assert _routes(calls) == [(OPENROUTER, "vendor/test-model")]
    assert not _home_env().exists()


def test_locally_unsupported_offering_is_rejected_with_its_reason(route_env, refresh_with, install_fake_urlopen):
    document = synthetic_models_dev(["vendor/test-model"])
    document["openrouter"]["models"]["vendor/no-tools"] = {
        "id": "vendor/no-tools", "name": "No Tools", "tool_call": False,
        "modalities": {"input": ["text"], "output": ["text"]}, "limit": {"context": 1000, "output": 100}}
    refresh_with(document)
    calls = install_fake_urlopen(["answer"])

    output = _run("/models refresh\n/model openrouter vendor/no-tools\ntask\nexit\n")

    assert "locally unsupported: does not support Tool calling." in output
    assert _routes(calls) == [(OPENROUTER, "vendor/test-model")]


def test_save_failure_keeps_active_and_saved_pair(route_env, openai_key, install_fake_urlopen, monkeypatch):
    calls = install_fake_urlopen(["answer"])

    def broken(settings, path=None):
        raise OSError("disk full")

    monkeypatch.setattr(config_store, "save_settings", broken)
    output = _run("/model openai vendor/new\ntask\nexit\n")

    assert "Error: could not save the pair: disk full. Active and saved pair unchanged." in output
    assert _routes(calls) == [(OPENROUTER, "vendor/test-model")]
    assert not _home_env().exists()


def test_config_menu_selects_lists_and_cancels_through_the_same_validation(
    route_env, openai_key, install_fake_urlopen
):
    calls = install_fake_urlopen(["answer"])
    box = Box(["/config", "/config", "task", "exit"], [
        "models", "openai test", "model", "openai vendor/absent", "model", "cancel", "done",
        "model", "openai vendor/new", "done"])

    output = _run(box=box)

    assert "Models.dev openai catalog fetched" in output and "  vendor/test-model  vendor/test-model" in output
    assert "Model 'vendor/absent' is not in the Models.dev catalog for openai" in output
    assert "Pair selection cancelled; active and saved pair unchanged." in output
    assert _routes(calls) == [(OPENAI, "vendor/new")]
    assert _saved()["PA_PROVIDER"] == "openai" and _saved()["PA_MODEL"] == "vendor/new"
    pair_events = [(entry["outcome"], entry.get("new")) for entry in _entries() if entry.get("setting") == "pair"]
    assert pair_events == [("error", None), ("cancelled", None), ("ok", "openai vendor/new")]


def test_config_pair_entry_end_of_input_cancels_without_saving(route_env, install_fake_urlopen):
    install_fake_urlopen([])

    output = _run(box=Box(["/config", "exit"], ["model", EOFError()]))

    assert "Pair selection cancelled" in output
    assert not _home_env().exists()
    assert [entry["outcome"] for entry in _entries() if entry.get("name") == "/config"] == ["cancelled"]


def test_models_searches_current_or_named_provider_literally(route_env, install_fake_urlopen):
    install_fake_urlopen([])

    output = _run("/models\n/models gemini CASE\n/models other\nexit\n")

    assert "Models.dev openrouter catalog fetched" in output
    assert "Models.dev gemini catalog fetched" in output
    assert "  vendor/Case-Model  vendor/Case-Model" in output
    assert "1 eligible model(s) matching 'CASE':" in output
    assert "1 eligible model(s) matching 'other':" in output


def test_failed_refresh_keeps_cache_bytes_catalog_and_pair(route_env, refresh_with, install_fake_urlopen):
    before = model_catalog.cache_path().read_bytes()
    refresh_with(HTTPError(model_catalog.URL, 503, "down", None, None))
    calls = install_fake_urlopen(["answer"])

    output = _run("/models refresh\ntask\nexit\n")

    assert "Error: Models.dev catalog refresh failed:" in output
    assert "Existing catalog, settings and pair kept." in output
    assert model_catalog.cache_path().read_bytes() == before
    assert _routes(calls) == [(OPENROUTER, "vendor/test-model")]
    assert [entry["outcome"] for entry in _entries() if entry.get("name") == "/models"] == ["error"]


def test_refresh_removing_the_pair_blocks_task_retry_and_compression_until_reselection(
    route_env, openai_key, refresh_with, install_fake_urlopen
):
    refresh_with(synthetic_models_dev(["vendor/new"]))
    calls = install_fake_urlopen(["one", "two", "three", HTTPError(OPENROUTER, 400, "bad", None, None), "retried"])

    output = _run("one\ntwo\nthree\nfailing\n/models refresh\nblocked\n/retry\n/compress\n/model\n"
                  "/model openai vendor/new\n/retry\nexit\n")

    assert "Pair unchanged." in output
    assert ("Warning: Model 'vendor/test-model' is not in the Models.dev catalog for openrouter" in output
            and "tasks, /retry and /compress are blocked" in output)
    assert output.count("Nothing was sent; choose an eligible pair with /model <provider> <model-id>.") == 3
    assert "Not admitted: Model 'vendor/test-model'" in output
    assert _routes(calls) == [(OPENROUTER, "vendor/test-model")] * 4 + [(OPENAI, "vendor/new")]
    assert _saved() == {"PA_PROVIDER": "openai", "PA_MODEL": "vendor/new"}
    openings = [(entry["type"], entry["ordinal"], entry["provider"], entry["model"]) for entry in _entries()
                if entry["type"] in {"routed_task_submitted", "routed_task_retried"}]
    assert openings == [("routed_task_submitted", ordinal, "openrouter", "vendor/test-model") for ordinal in (1, 2, 3, 4)] + [
        ("routed_task_retried", 4, "openai", "vendor/new")]
    assert [entry["outcome"] for entry in _entries() if entry.get("name") in {"/retry", "/compress"}] == [
        "error", "error", "ok"]


def test_refresh_that_keeps_the_pair_resizes_only_later_snapshots(route_env, refresh_with, install_fake_urlopen):
    refresh_with(synthetic_models_dev(["vendor/test-model"], context=64000, output=4000))
    calls = install_fake_urlopen(["first", "second"])

    output = _run("first\n/usage\n/models refresh\nsecond\n/usage\nexit\n")

    assert [json.loads(call["request"].data)["max_tokens"] for call in calls] == [16000, 4000]
    assert "capacity: Models.dev 128000" in output and "capacity: Models.dev 64000" in output
    assert "output limit: 16000 (Models.dev)" in output and "output limit: 4000 (Models.dev)" in output


def test_manual_total_override_keeps_models_dev_output_with_labels(route_env, install_fake_urlopen, monkeypatch):
    monkeypatch.setenv(runtime_config.CAPACITY_OVERRIDES_ENV_VAR, json.dumps(
        [{"provider": "openrouter", "model": "vendor/test-model", "total_tokens": 90000}]))
    calls = install_fake_urlopen(["answer"])

    output = _run("task\n/usage\nexit\n")

    assert "capacity: manual 90000" in output and "output limit: 16000 (Models.dev)" in output
    assert json.loads(calls[0]["request"].data)["max_tokens"] == 16000


def test_eligible_model_without_local_pricing_runs_with_unknown_cost(
    monkeypatch, openai_key, install_fake_urlopen
):
    monkeypatch.setenv("PA_PROVIDER", "openai")
    monkeypatch.setenv("PA_MODEL", "vendor/new")
    calls = install_fake_urlopen([{"content": "answer", "usage": {"prompt_tokens": 10, "completion_tokens": 2}}])

    output = _run("task\nexit\n")

    assert "llm> answer" in output and len(calls) == 1
    attempt = next(entry for entry in _entries() if entry["type"] == "attempt")
    assert attempt["cost"] is None and attempt["ok"] is True


def test_startup_opens_setup_for_a_pair_the_cache_does_not_admit(monkeypatch, capsys):
    monkeypatch.setenv("PA_PROVIDER", "openrouter")
    monkeypatch.setenv("PA_MODEL", "vendor/absent")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")

    monkeypatch.setattr("sys.stdin", StringIO("task\n/exit\n"))
    main([])

    err = capsys.readouterr().err
    assert "Model 'vendor/absent' is not in the Models.dev catalog for openrouter" in err
    assert "personal-agent --models openrouter" in err and model_catalog.REFRESH_COMMAND in err
    assert not any(entry["type"] == "routed_task_submitted" for entry in _entries())


def test_startup_without_usable_catalog_fetches_once_then_opens_setup_with_refresh_guidance(
    monkeypatch, capsys, refresh_with
):
    model_catalog.cache_path().write_bytes(b"{corrupt")
    requests = refresh_with(HTTPError(model_catalog.URL, 503, "down", None, None))
    monkeypatch.setenv("PA_PROVIDER", "openrouter")
    monkeypatch.setenv("PA_MODEL", "vendor/test-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")

    monkeypatch.setattr("sys.stdin", StringIO("task\n/exit\n"))
    main([])

    assert len(requests) == 1
    assert f"Retry with {model_catalog.REFRESH_COMMAND}." in capsys.readouterr().err
    assert model_catalog.cache_path().read_bytes() == b"{corrupt"
