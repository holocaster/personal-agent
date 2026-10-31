import json
import os
from pathlib import Path
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace

import pytest

from personal_agent.routing import router, runtime_config
from personal_agent.workspace_skills import Skill
from personal_agent.tools import registry as tools
from personal_agent.tools.mcp_resources import ServerConfig
from personal_agent import token_estimate
from tests.prompt_surface import FIXTURES, MODES, capture_request, render_surface, surface


def test_ordinary_request_orders_stable_rules_before_changing_context(route_env, install_fake_urlopen):
    calls = install_fake_urlopen("done")
    result = router.route(
        "synthetic task", runtime_config.load(),
        project_instructions="PROJECT_POLICY",
        memory_notes=[{"text": "MEMORY_NOTE"}],
        skills=(Skill("active", "Active skill", "SKILL_BODY", b"synthetic"),),
        summary="SUMMARY_CONTEXT",
        todos=[{"content": "TODO_TASK", "status": "pending"}],
    )
    assert result.ok, result.error
    system = json.loads(calls[0]["request"].data)["messages"][0]["content"]
    sections = ["You are a helpful assistant.", "For arithmetic", "Build mode",
                "Answer in the language", "PROJECT_POLICY", "MEMORY_NOTE", "SKILL_BODY",
                "SUMMARY_CONTEXT", "TODO_TASK"]
    positions = [system.index(section) for section in sections]
    assert positions == sorted(positions)


@pytest.mark.parametrize("mode", ["plan", "build", "auto"])
def test_effective_catalogue_order_does_not_depend_on_registration_or_skill_order(tmp_path, mode):
    skills = [Skill("zeta", "Last skill", "Last body", b"zeta"),
              Skill("alpha", "First skill", "First body", b"alpha")]
    server = ServerConfig("synthetic", "never-launch", ())
    tools.enable_shell_tool()
    tools.enable_mcp_resources(server, tmp_path)
    tools.enable_websearch_tool("synthetic-search-key")
    first = tools.definitions_for_mode(mode, skills)
    tools.reset_registry()
    tools.enable_websearch_tool("synthetic-search-key")
    tools.enable_mcp_resources(server, tmp_path)
    tools.enable_shell_tool()
    second = tools.definitions_for_mode(mode, list(reversed(skills)))
    assert first == second
    assert [tool.name for tool in first] == sorted(tool.name for tool in first)
    description = next(tool.description for tool in first if tool.name == "skill")
    assert description.index("alpha:") < description.index("zeta:")
    if mode == "plan":
        assert tools.PLAN_DENIED_NAMES.isdisjoint(tool.name for tool in first)


@pytest.mark.parametrize("mode", MODES)
def test_reviewed_production_surface(tmp_path, mode):
    body, _ = capture_request(tmp_path, mode)
    assert render_surface(body) == (FIXTURES / f"{mode}.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("provider", ["openrouter", "anthropic", "openai", "gemini"])
@pytest.mark.parametrize("changed", ["memory_notes", "skills", "summary", "todos"])
def test_variable_context_preserves_prepared_stable_prefix_and_complete_budget(tmp_path, provider, changed):
    changes = {
        "memory_notes": [{"text": "A changed synthetic preference."}],
        "skills": (Skill("active", "Active synthetic skill", "Changed active instructions.", b"synthetic"),),
        "summary": "A changed synthetic summary.",
        "todos": [{"content": "A changed synthetic todo", "status": "pending"}],
    }
    first, _ = capture_request(tmp_path / "first", provider=provider)
    second, assessments = capture_request(tmp_path / "second", provider=provider, changes={changed: changes[changed]})
    system, definitions = surface(first, provider)
    changed_system, changed_definitions = surface(second, provider)
    assert definitions == changed_definitions
    block = {"memory_notes": "Facts the user asked", "skills": "Skill (beta",
             "summary": "Conversation Summary", "todos": "Todo List:"}[changed]
    stable = system[:system.index(block)]
    assert changed_system.startswith(stable)
    assert "Use the synthetic project conventions." in stable
    assert system != changed_system
    prepared = [{key: value for key, value in body.items()
                 if key not in {"model", "max_tokens", "max_completion_tokens", "generationConfig", "provider", "session_id", "cache_control"}}
                for body in (first, second)]
    rendered = [token_estimate.render_input(value).encode("utf-8") for value in prepared]
    prefix = os.path.commonprefix(rendered)
    assert b"Use the synthetic project conventions." in prefix
    assert len(prefix) > 121
    assert rendered[0] != rendered[1]
    assert len(assessments) == 2
    assert all(value["estimate"] == token_estimate.estimate("synthetic-surface-model", prepared[1])
               for value in assessments)
    expected_tools = surface(capture_request(tmp_path / "canonical")[0])[1]
    assert definitions == expected_tools
    assert next(tool["parameters"]["required"] for tool in definitions if tool["name"] == "edit") == [
        "path", "old_string", "new_string"]


@pytest.mark.parametrize("change", ["prompt", "schema"])
def test_real_surface_changes_require_fixture_regeneration(tmp_path, monkeypatch, change):
    if change == "prompt":
        original = router._build_system_prompt
        monkeypatch.setattr(router, "_build_system_prompt", lambda *args, **kwargs: original(*args, **kwargs).replace(
            "You are a helpful assistant.", "You are a changed synthetic assistant."))
    else:
        entry = tools._REGISTRY["calculator"]
        parameters = deepcopy(entry.parameters)
        parameters["properties"]["expression"]["description"] = "Changed synthetic schema text."
        monkeypatch.setitem(tools._REGISTRY, "calculator", replace(entry, parameters=parameters))
    body, _ = capture_request(tmp_path)
    with pytest.raises(AssertionError):
        assert render_surface(body) == (FIXTURES / "build.md").read_text(encoding="utf-8")


def test_surfaces_ignore_clock_root_home_credentials_and_hash_seed(tmp_path):
    root = Path(__file__).resolve().parents[1]
    generated = []
    for seed, clock, key in [("1", "2001-02-03T04:05:06Z", "first-synthetic-key"),
                             ("991", "2099-12-31T23:59:59Z", "second-synthetic-key")]:
        destination = tmp_path / seed
        environment = {"PATH": os.defpath, "PYTHONHASHSEED": seed, "HOME": str(tmp_path / f"ambient-home-{seed}"),
                       "PYTHONPATH": str(root / "src"), "OPENROUTER_API_KEY": key,
                       "PA_MCP_SERVER": "invalid ambient config", "PA_MEMORY_PATH": "/nonexistent/ambient-memory",
                       "LITELLM_MODE": "PRODUCTION", "LITELLM_LOCAL_MODEL_COST_MAP": "True"}
        code = ("from pathlib import Path; from tests.prompt_surface import write_surfaces; "
                "import sys; write_surfaces(Path(sys.argv[1]), clock=sys.argv[2], ambient_key=sys.argv[3])")
        result = subprocess.run([sys.executable, "-c", code, str(destination), clock, key],
                                cwd=root, env=environment, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        generated.append({path.name: path.read_bytes() for path in destination.glob("*.md")})
    expected = {path.name: path.read_bytes() for path in FIXTURES.glob("*.md")}
    assert set(expected) == {"plan.md", "build.md", "auto.md"}
    assert generated[0] == generated[1] == expected
