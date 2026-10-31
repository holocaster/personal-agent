import json
import os
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib import request as urllib_request

from pytest import MonkeyPatch

from personal_agent import call_log, memory, project_instructions
from personal_agent.providers import http, openrouter
from personal_agent.routing import router, runtime_config
from personal_agent.tools import builtins, registry, workspace
from personal_agent.tools.mcp_resources import ServerConfig
from personal_agent import workspace_skills
from tests.fakes import FakeOpenRouterResponse


FIXTURES = Path(__file__).parent / "fixtures" / "prompt-surface"
MODES = ("plan", "build", "auto")


def capture_request(directory, mode="build", provider="openrouter", *, changes=None,
                    clock="2001-02-03T04:05:06Z", ambient_key="synthetic-ambient-key"):
    root = directory / "workspace"
    home = directory / "home"
    root.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    requests, assessments = [], []

    def forbidden(*args, **kwargs):
        raise AssertionError("Prompt surfaces must remain offline and isolated")

    def fake_http(request, timeout=None):
        body = json.loads(request.data)
        if provider == "gemini":
            assert "/synthetic-surface-model:" in request.full_url
        else:
            assert body["model"] == "synthetic-surface-model"
        requests.append(body)
        if provider == "anthropic":
            payload = {"content": [{"type": "text", "text": "synthetic answer"}]}
        elif provider == "gemini":
            payload = {"candidates": [{"content": {"parts": [{"text": "synthetic answer"}]}}]}
        else:
            payload = {"choices": [{"message": {"content": "synthetic answer"}}]}
        return FakeOpenRouterResponse(payload)

    environment = {"HOME": str(home), "LITELLM_MODE": "PRODUCTION",
                   "LITELLM_LOCAL_MODEL_COST_MAP": "True", "HF_HUB_OFFLINE": "1",
                   **{name: ambient_key for name in runtime_config.API_KEY_ENV_VARS.values()}}
    with patch.dict(os.environ, environment, clear=True), MonkeyPatch.context() as mp:
        mp.chdir(root)
        mp.setattr(socket.socket, "connect", forbidden)
        mp.setattr(socket.socket, "connect_ex", forbidden)
        mp.setattr(socket, "create_connection", forbidden)
        mp.setattr(urllib_request, "urlopen", forbidden)
        mp.setattr(http, "urlopen", fake_http)
        mp.setattr(openrouter, "urlopen", forbidden)
        mp.setattr(builtins, "_clock", forbidden)
        mp.setattr(call_log, "_now_iso", lambda: clock)
        mp.setattr(memory, "_now_iso", lambda: clock)
        for name in ("_workspace_root", "_log_home", "_project_id", "_current_session_id",
                     "_current_run_id", "_detail_file"):
            mp.setattr(call_log, name, None)
        mp.setattr(call_log, "_total_cost", 0.0)
        mp.setattr(workspace, "_workspace", None)
        mp.setattr(registry, "_REGISTRY", registry._REGISTRY.copy())
        mp.setattr(registry, "TOOL_DEFS", registry.TOOL_DEFS)
        registry.reset_registry()
        workspace.configure_workspace(root)
        call_log.initialize_storage(root)
        registry.enable_shell_tool()
        registry.enable_websearch_tool("synthetic-search-key")
        registry.enable_mcp_resources(ServerConfig("synthetic", "never-launch", ()), root)
        (root / "AGENTS.md").write_text("Use the synthetic project conventions.\n", encoding="utf-8")
        for origin, name, description, body in (
            (home, "alpha", "Inspect synthetic examples.", "Keep synthetic evidence precise.\n"),
            (root, "beta", "Validate synthetic changes.", "Check the synthetic acceptance criteria.\n"),
        ):
            skill = origin / ".agents" / "skills" / name / "SKILL.md"
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}", encoding="utf-8")
        memory.remember("Prefer synthetic metric examples.")
        context = {
            "project_instructions": project_instructions.load(root).text,
            "memory_notes": memory.load(),
            "skills": (workspace_skills.load("beta"), workspace_skills.load("alpha")),
            "summary": "Earlier synthetic discussion selected a small change.",
            "todos": [{"content": "Inspect synthetic input", "status": "completed"},
                      {"content": "Validate synthetic output", "status": "in_progress"},
                      {"content": "Review synthetic result", "status": "pending"}],
        }
        context.update(changes or {})
        config = runtime_config.RuntimeConfig(
            provider, "synthetic-surface-model", {provider: "synthetic-provider-key"},
            capacity_overrides=({"provider": provider, "model": "synthetic-surface-model", "total_tokens": 250000},),
        )
        result = router.route("Inspect the synthetic task.", config, mode=mode,
                              on_assessment=lambda value: assessments.append(dict(value)), **context)
        assert result.ok, result.error
        assert len(requests) == 1
    return requests[0], assessments


def surface(body, provider="openrouter"):
    if provider == "anthropic":
        system = body["system"]
        tools = [{"name": tool["name"], "description": tool["description"], "parameters": tool["input_schema"]}
                 for tool in body["tools"]]
    elif provider == "gemini":
        system = body["systemInstruction"]["parts"][0]["text"]
        tools = body["tools"][0]["functionDeclarations"]
    else:
        system = body["messages"][0]["content"]
        tools = [tool["function"] for tool in body["tools"]]
    return system, tools


def render_surface(body, provider="openrouter"):
    system, tools = surface(body, provider)
    schemas = json.dumps(tools, ensure_ascii=False, indent=2, sort_keys=True)
    return f"# System text\n\n{system}\n\n# Ordered Tool schemas\n\n```json\n{schemas}\n```\n"


def write_surfaces(destination, **kwargs):
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="pa-prompt-surface-") as directory:
        for mode in MODES:
            body, _ = capture_request(Path(directory) / mode, mode, **kwargs)
            (destination / f"{mode}.md").write_text(render_surface(body), encoding="utf-8")


if __name__ == "__main__":
    write_surfaces(Path(sys.argv[1]))
