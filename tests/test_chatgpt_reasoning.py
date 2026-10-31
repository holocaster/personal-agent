import json
import pickle
from io import StringIO
from collections import deque
from pathlib import Path
from dataclasses import replace

import pytest

from personal_agent import chatgpt_auth
from personal_agent.routing import config_store, runtime_config
from tests.test_chatgpt_auth import oauth
from tests.test_chatgpt_provider import completed, function, message
from tests.test_streaming import StreamResponse, install_stream


@pytest.fixture
def plan(oauth, monkeypatch):
    auth, state = oauth
    transport = auth.transport
    state["reasoning"] = {"supported_reasoning_levels": [{"effort": "medium"}, {"effort": "high"}, {"effort": "xhigh"}],
                          "default_reasoning_level": "medium"}

    def models(url, **kwargs):
        data = transport(url, **kwargs)
        if url == chatgpt_auth.MODELS:
            data["models"][0].update(state["reasoning"])
            data["models"].extend(state.get("extra_models", []))
        return data

    auth.transport = models
    binding = auth.connect()
    auth.acknowledge(binding)
    auth.activate(binding, "exact-1", lambda: None)
    monkeypatch.setattr(chatgpt_auth, "ChatGPTAuth", lambda: auth)
    return auth, state, binding


def test_account_reasoning_capabilities_and_persisted_snapshot(plan):
    auth, _, binding = plan
    offering = auth.models(binding)[0]
    assert offering.reasoning_levels == ("medium", "high", "xhigh")
    assert offering.default_reasoning == "medium"
    config_store.save_settings({"PA_CHATGPT_REASONING_EFFORT": "xhigh"})
    config = runtime_config.load(config_store.read_env_values())
    assert config.chatgpt_reasoning_effort == "xhigh"
    snapshot = config.snapshot()
    assert snapshot.chatgpt_reasoning_effort == "xhigh"
    assert pickle.loads(pickle.dumps(config)).chatgpt_reasoning_effort == "xhigh"
    assert runtime_config.load({}).chatgpt_reasoning_effort == "auto"


@pytest.mark.parametrize("metadata", [
    {"supported_reasoning_levels": None}, {"supported_reasoning_levels": ["high"]},
    {"supported_reasoning_levels": [{"effort": "high\n"}]},
    {"supported_reasoning_levels": [{"effort": "high"}] * 2},
    {"supported_reasoning_levels": [{"effort": "x" * 33}]},
    {"supported_reasoning_levels": [{"effort": "auto"}]},
    {"supported_reasoning_levels": [{"effort": f"level{i}"} for i in range(33)]},
    {"default_reasoning_level": None},
    {"default_reasoning_level": "x" * 33},
    {"supported_reasoning_levels": [{"effort": "low"}], "default_reasoning_level": "high"},
])
def test_malformed_account_reasoning_metadata_is_rejected(plan, metadata):
    auth, state, binding = plan
    state["reasoning"] = metadata
    with pytest.raises(chatgpt_auth.AuthError, match="invalid account model list"):
        auth.models(binding)


def test_unknown_capabilities_allow_auto_but_reject_explicit_effort(plan):
    _, state, _ = plan
    state["reasoning"] = {}
    config = runtime_config.admit_chatgpt(runtime_config.RuntimeConfig("chatgpt", "exact-1", {}))
    assert config.offering.reasoning_levels == ()
    with pytest.raises(chatgpt_auth.AuthError, match="unknown.*reasoning auto"):
        runtime_config.admit_chatgpt(replace(config, chatgpt_reasoning_effort="high"))


@pytest.mark.parametrize("effort", ["auto", "high", "xhigh"])
def test_chatgpt_wire_effort_is_explicit_or_omitted(monkeypatch, effort):
    from personal_agent.providers import chatgpt
    _, requests = install_stream(monkeypatch, [completed([message()])])
    assistant, _ = chatgpt.call("exact-1", "", [], api_key="synthetic-bearer", reasoning_effort=effort)
    assert assistant.text == "hello"
    payload = json.loads(requests[0].data)
    if effort == "auto":
        assert "reasoning" not in payload
    else:
        assert payload["reasoning"] == {"effort": effort}


def test_reasoning_command_saves_supported_selection_and_restores_auto(plan):
    from personal_agent.terminal.repl import run_repl
    output = StringIO()
    run_repl(runtime_config.RuntimeConfig("chatgpt", "exact-1", {}),
             input_stream=["/reasoning", "/reasoning high", "/reasoning ultra", "/reasoning", "/exit"],
             output_stream=output)
    text = output.getvalue()
    assert "Supported: medium, high, xhigh" in text
    assert "Model default: medium" in text
    assert "Reasoning: high" in text
    assert "does not support" in text
    assert config_store.read_env_values()["PA_CHATGPT_REASONING_EFFORT"] == "high"
    output = StringIO()
    plan[0].disconnect()
    run_repl(runtime_config.RuntimeConfig("chatgpt", "exact-1", {}, chatgpt_reasoning_effort="high"),
             input_stream=["/reasoning auto", "/exit"], output_stream=output)
    assert config_store.read_env_values()["PA_CHATGPT_REASONING_EFFORT"] == "auto"
    assert "Reasoning: auto" in output.getvalue()


@pytest.mark.parametrize("value", ["", " high", "HIGH", "high\n", "x" * 33, "high;echo"])
def test_invalid_reasoning_environment_is_rejected(value):
    with pytest.raises(ValueError, match="PA_CHATGPT_REASONING_EFFORT"):
        runtime_config.load({"PA_CHATGPT_REASONING_EFFORT": value})


def test_catalog_levels_are_not_limited_to_common_efforts(plan):
    auth, state, binding = plan
    state["reasoning"] = {"supported_reasoning_levels": [{"effort": "max"}, {"effort": "ultra"}],
                          "default_reasoning_level": "max"}
    offering = auth.models(binding)[0]
    assert offering.reasoning_levels == ("max", "ultra")
    config = runtime_config.RuntimeConfig("chatgpt", "exact-1", {}, chatgpt_reasoning_effort="ultra")
    assert runtime_config.admit_chatgpt(config).chatgpt_reasoning_effort == "ultra"


def test_catalog_change_blocks_incompatible_reasoning_before_dispatch(plan, monkeypatch):
    from personal_agent.routing import router
    from personal_agent.providers import chatgpt
    config = runtime_config.admit_chatgpt(runtime_config.RuntimeConfig("chatgpt", "exact-1", {},
                                                                            chatgpt_reasoning_effort="xhigh"))
    plan[1]["reasoning"] = {"supported_reasoning_levels": [{"effort": "medium"}]}
    with pytest.raises(chatgpt_auth.AuthError, match="does not support.*reasoning auto"):
        runtime_config.admit_chatgpt(config)
    monkeypatch.setattr(chatgpt.http, "urlopen", lambda *args, **kwargs: pytest.fail("inference dispatched"))
    result = router.route("task", replace(config, chatgpt_reasoning_effort="ultra"))
    assert not result.ok and "does not support" in result.error


def test_config_reasoning_edit_cancel_failure_and_override_warning(plan, monkeypatch):
    from personal_agent import call_log
    from personal_agent.terminal.repl import run_repl
    from tests.test_runtime_config import _ScriptedInputBox
    box = _ScriptedInputBox(["/config", "/reasoning", "/exit"],
                            ["reasoning", "high", "reasoning", "cancel", "done"])
    output = StringIO()
    run_repl(runtime_config.RuntimeConfig("chatgpt", "exact-1", {}), input_box=box, output_stream=output,
             config_sources={"PA_CHATGPT_REASONING_EFFORT": "exported environment"})
    assert "Reasoning: high" in output.getvalue()
    assert "PA_CHATGPT_REASONING_EFFORT from exported environment overrides" in output.getvalue()
    assert config_store.read_env_values()["PA_CHATGPT_REASONING_EFFORT"] == "high"
    events = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    assert any(event.get("setting") == "reasoning" and event.get("outcome") == "cancelled" for event in events)

    def fail(settings):
        raise OSError("save failed")

    monkeypatch.setattr(config_store, "save_settings", fail)
    output = StringIO()
    run_repl(runtime_config.RuntimeConfig("chatgpt", "exact-1", {}, chatgpt_reasoning_effort="high"),
             input_stream=["/reasoning xhigh", "/reasoning", "/exit"], output_stream=output)
    assert "Active and saved reasoning unchanged" in output.getvalue()
    assert output.getvalue().endswith("Supported: medium, high, xhigh\nModel default: medium\n")
    assert config_store.read_env_values()["PA_CHATGPT_REASONING_EFFORT"] == "high"


def test_reasoning_flows_through_tools_retries_and_manual_compression(plan, monkeypatch):
    from personal_agent.providers import chatgpt
    from personal_agent.routing import router
    config = runtime_config.admit_chatgpt(runtime_config.RuntimeConfig("chatgpt", "exact-1", {},
                                                                            chatgpt_reasoning_effort="xhigh"))
    responses = deque([StreamResponse([completed([function()])]), StreamResponse([TimeoutError("temporary")]),
                       StreamResponse([completed([message("done")])]), StreamResponse([completed([message("summary")])])])
    requests = []

    def respond(request, timeout):
        requests.append(json.loads(request.data))
        return responses.popleft()

    monkeypatch.setattr(chatgpt.http, "urlopen", respond)
    monkeypatch.setattr(router, "_sleep", lambda _: None)
    result = router.route("calculate", config,
                          on_tool_result=lambda _: monkeypatch.setenv("PA_CHATGPT_REASONING_EFFORT", "medium"))
    assert result.ok and result.answer == "done" and len(requests) == 3
    history = [({"role": "user", "content": "older text " * 100}, {"role": "assistant", "content": "answer"})]
    summary, error = router.compress(history, None, config)
    assert summary == "summary" and error is None
    assert len(requests) == 4 and all(request["reasoning"] == {"effort": "xhigh"} for request in requests)
    assert requests[1] == requests[2]


def test_preventive_compression_keeps_reasoning(plan, monkeypatch):
    from personal_agent import token_estimate
    from personal_agent.routing import router
    from tests.test_chatgpt_provider import exhaustion
    config = runtime_config.admit_chatgpt(runtime_config.RuntimeConfig("chatgpt", "exact-1", {},
                                                                            chatgpt_reasoning_effort="high"))

    def estimate(model, prepared):
        return token_estimate.TokenEstimate(103000 if "tools" in prepared else max(1, len(json.dumps(prepared)) // 4),
                                            "synthetic", True)

    monkeypatch.setattr(token_estimate, "estimate", estimate)
    _, requests = install_stream(monkeypatch, exhaustion())
    history = [({"role": "user", "content": "older context " * 100}, {"role": "assistant", "content": "answer"})] * 3
    result = router.route("pending", config, history_turns=history, on_compression=lambda _: None)
    assert not result.ok and "Cota atingida" in result.error
    assert len(requests) == 1 and json.loads(requests[0].data)["reasoning"] == {"effort": "high"}


def test_explicit_retry_uses_the_new_reasoning_preference(plan, monkeypatch):
    from personal_agent.providers import chatgpt
    from personal_agent.terminal.repl import run_repl
    from tests.test_chatgpt_provider import event
    config = runtime_config.RuntimeConfig("chatgpt", "exact-1", {}, chatgpt_reasoning_effort="xhigh")
    responses = deque([StreamResponse([event("response.future_event")]), StreamResponse([completed([message("retried")])])])
    requests = []

    def respond(request, timeout):
        requests.append(json.loads(request.data))
        return responses.popleft()

    monkeypatch.setattr(chatgpt.http, "urlopen", respond)
    output = StringIO()
    run_repl(config, input_stream=["task", "/reasoning high", "/retry", "/exit"], output_stream=output)
    assert "llm> retried" in output.getvalue()
    assert [request["reasoning"] for request in requests] == [{"effort": "xhigh"}, {"effort": "high"}]


@pytest.mark.parametrize("source", ["home", "cwd", "exported"])
def test_reasoning_setting_preserves_environment_precedence(route_env, tmp_path, monkeypatch, source):
    from personal_agent.__main__ import main
    home = tmp_path / ".personal_agent" / ".env"
    home.parent.mkdir()
    home.write_text("PA_CHATGPT_REASONING_EFFORT=medium\n")
    if source in {"cwd", "exported"}:
        (tmp_path / ".env").write_text("PA_CHATGPT_REASONING_EFFORT=high\n")
    if source == "exported":
        monkeypatch.setenv("PA_CHATGPT_REASONING_EFFORT", "xhigh")
    captured = {}
    monkeypatch.setattr("personal_agent.__main__.run_repl", lambda config, **kwargs: captured.update(config=config, **kwargs))
    monkeypatch.setattr("sys.stdin", StringIO())
    main([])
    assert captured["config"].chatgpt_reasoning_effort == {"home": "medium", "cwd": "high", "exported": "xhigh"}[source]
    assert captured["config_sources"]["PA_CHATGPT_REASONING_EFFORT"] == {
        "home": "home .env", "cwd": "current-directory .env", "exported": "exported environment"}[source]


def test_model_change_does_not_silently_replace_incompatible_reasoning(plan):
    from personal_agent.terminal.repl import run_repl
    auth, state, _ = plan
    state["extra_models"] = [{"slug": "exact-2", "display_name": "Model Two", "visibility": "list",
                              "supported_reasoning_levels": [{"effort": "medium"}]}]
    output = StringIO()
    run_repl(runtime_config.RuntimeConfig("chatgpt", "exact-1", {}, chatgpt_reasoning_effort="high"),
             input_stream=["/model chatgpt exact-2", "/reasoning", "/exit"], output_stream=output)
    assert "does not support reasoning 'high'" in output.getvalue()
    assert auth.status().selected_model == "exact-1"
    assert config_store.read_env_values() == {}


def test_footer_shows_preference_and_api_route_ignores_it():
    from personal_agent.terminal.repl import render_footer
    assert "reasoning xhigh" in render_footer("chatgpt", "exact-1", 0, reasoning="xhigh")
    assert "reasoning auto" in render_footer("chatgpt", "exact-1", 0, reasoning="auto")
    assert "reasoning" not in render_footer("openai", "gpt-x", 0, reasoning="xhigh")
