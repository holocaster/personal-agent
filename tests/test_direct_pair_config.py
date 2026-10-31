from personal_agent.routing import runtime_config
import pytest
import json


def test_validate_returns_empty_for_the_configured_pair_and_key(route_env):
    config = runtime_config.load()

    assert runtime_config.validate(config) == []


def test_tool_round_limit_defaults_to_fifty():
    assert runtime_config.load({}).max_tool_rounds == 50


@pytest.mark.parametrize("value", ["1", "8", "75", "0050"])
def test_tool_round_limit_is_loaded_from_environment_and_preserved_in_snapshot(monkeypatch, value):
    monkeypatch.setenv("PA_MAX_TOOL_ROUNDS", value)

    config = runtime_config.load()

    assert config.max_tool_rounds == int(value)
    assert config.snapshot().max_tool_rounds == int(value)


@pytest.mark.parametrize("value", ["", "0", "-1", "1.5", "abc", " 50", "+50", "５０"])
def test_invalid_tool_round_limit_is_rejected(value):
    with pytest.raises(ValueError, match="PA_MAX_TOOL_ROUNDS must be a positive decimal integer"):
        runtime_config.load({"PA_MAX_TOOL_ROUNDS": value})


def test_context_configuration_defaults_and_copied_snapshot(route_env):
    config = runtime_config.load()
    assert config.context_budget_tokens == 250000
    assert config.capacity_overrides == ()
    record = {"provider": "openai", "model": "exact", "total_tokens": 300000}
    config = runtime_config.load({"PA_CONTEXT_BUDGET_TOKENS": "350000",
                               "PA_CONTEXT_CAPACITY_OVERRIDES": json.dumps([record])})
    snapshot = config.snapshot()
    config.capacity_overrides[0]["total_tokens"] = 1
    config.api_keys.clear()
    assert snapshot.context_budget_tokens == 350000
    assert snapshot.capacity_overrides[0]["total_tokens"] == 300000
    assert set(snapshot.api_keys) == {"openrouter", "anthropic", "openai", "gemini"}


@pytest.mark.parametrize("value", ["0", "-1", "1.2", "True", " 42", "+42", "", "１２"])
def test_invalid_context_budget_is_rejected(value):
    with pytest.raises(ValueError, match="PA_CONTEXT_BUDGET_TOKENS"):
        runtime_config.load({"PA_CONTEXT_BUDGET_TOKENS": value})


@pytest.mark.parametrize("records", [None, {}, [{"provider": "openai", "model": "x"}],
    [{"provider": "no", "model": "x", "total_tokens": 20}],
    [{"provider": "openai", "model": "", "total_tokens": 20}],
    [{"provider": "openai", "model": "x", "total_tokens": True}],
    [{"provider": "openai", "model": "x", "total_tokens": 20, "input_tokens": 21}],
    [{"provider": "openai", "model": "x", "total_tokens": 20, "unknown": 1}],
    [{"provider": "openai", "model": "x", "total_tokens": 20}]*2])
def test_invalid_capacity_overrides_are_rejected(records):
    with pytest.raises(ValueError, match="PA_CONTEXT_CAPACITY_OVERRIDES"):
        runtime_config.load({"PA_CONTEXT_CAPACITY_OVERRIDES": json.dumps(records)})


def test_missing_pair_is_required_without_a_default(monkeypatch, route_env):
    monkeypatch.delenv("PA_PROVIDER")
    monkeypatch.delenv("PA_MODEL")

    problems = runtime_config.validate(runtime_config.load())

    assert len(problems) == 2
    assert "PA_PROVIDER is required" in problems[0] and "openrouter, anthropic, openai, gemini" in problems[0]
    assert "PA_MODEL is required" in problems[1] and "--models <provider>" in problems[1]


def test_old_tier_settings_are_ignored_with_exact_new_setting_guidance(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    for tier in ("EASY", "MEDIUM", "COMPLEX"):
        monkeypatch.setenv(f"TIER_{tier}_MODEL", "vendor/old")
        monkeypatch.setenv(f"TIER_{tier}_PROVIDER", "openrouter")

    config = runtime_config.load()
    problems = runtime_config.validate(config)

    assert (config.provider, config.model) == ("", "")
    assert problems[-1] == "TIER_* settings are no longer read; set PA_PROVIDER and PA_MODEL instead"
    monkeypatch.setenv("PA_PROVIDER", "openrouter")
    monkeypatch.setenv("PA_MODEL", "vendor/new")
    assert runtime_config.validate(runtime_config.load()) == []


def test_provider_is_normalized_model_is_exact_and_api_keys_are_mapped(monkeypatch, route_env):
    monkeypatch.setenv("PA_PROVIDER", " OpenRouter ")
    monkeypatch.setenv("PA_MODEL", " Vendor/Case-Model ")

    config = runtime_config.load()

    assert (config.provider, config.model, config.api_key) == ("openrouter", "Vendor/Case-Model", "test-key")
    assert config.api_keys == {"openrouter": "test-key", "anthropic": "", "openai": "", "gemini": ""}


def test_validate_reports_an_unknown_provider_without_requiring_a_key(monkeypatch, route_env):
    monkeypatch.setenv("PA_PROVIDER", " unknown ")
    monkeypatch.delenv("OPENROUTER_API_KEY")

    problems = runtime_config.validate(runtime_config.load())

    assert problems == ["PA_PROVIDER has unrecognised provider 'unknown'; expected one of: "
                        "openrouter, anthropic, openai, gemini, chatgpt"]


@pytest.mark.parametrize("provider,variable", [("openrouter", "OPENROUTER_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"),
                                               ("openai", "OPENAI_API_KEY"), ("gemini", "GEMINI_API_KEY")])
def test_only_the_selected_provider_key_is_required(monkeypatch, route_env, provider, variable):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("PA_PROVIDER", provider)

    assert runtime_config.validate(runtime_config.load()) == [f"{variable} is required for provider {provider!r}"]
    monkeypatch.setenv(variable, "selected-key")
    config = runtime_config.load()
    assert runtime_config.validate(config) == []
    assert [key for key in config.api_keys.values() if key] == ["selected-key"]


def test_snapshot_is_immutable(route_env):
    config = runtime_config.load()
    snapshot = config.snapshot()

    with pytest.raises(TypeError):
        snapshot.api_keys["openrouter"] = "changed"
    assert (snapshot.provider, snapshot.model) == ("openrouter", "vendor/test-model")
