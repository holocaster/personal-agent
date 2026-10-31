import json

import pytest

from personal_agent import call_log, chatgpt_auth, memory, model_catalog
from personal_agent.routing import runtime_config
from personal_agent.providers import http, openrouter
from personal_agent.tools import registry as tools_registry
from personal_agent.tools import jobs, shell as shell_tool
from tests.fakes import FakeCatalogResponse, FakeOpenRouterResponse, Repeat, synthetic_models_dev

_PA_ENV_VARS = (
    runtime_config.MANAGED_ENV_VARS
    | {runtime_config.MAX_TOOL_ROUNDS_ENV_VAR}
    | {"TIER_EASY_MODEL", "TIER_MEDIUM_MODEL", "TIER_COMPLEX_MODEL"}
    | {"TIER_EASY_PROVIDER", "TIER_MEDIUM_PROVIDER", "TIER_COMPLEX_PROVIDER"}
    | {"PA_BUDGET_USD"}
    | {memory.MEMORY_PATH_ENV_VAR}
    | {"PA_MAX_READ_BYTES", "PA_MAX_WRITE_BYTES"}
    | {"PA_ENABLE_SHELL", "PA_SHELL_TIMEOUT_SECONDS", "PA_SHELL_MAX_OUTPUT_BYTES"}
    | {"TAVILY_API_KEY"}
    | {openrouter.PROVIDER_DIAGNOSTICS_ENV_VAR}
    | {"PA_DETAILED_AUDIT"}
    | {"CUSTOM_TIKTOKEN_CACHE_DIR", "TIKTOKEN_CACHE_DIR", "HF_HUB_OFFLINE"}
)


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """Run every test outside the repo root.

    personal_agent.dotenv.load_dotenv() reads a relative "./.env" by
    default, so main() would otherwise reload the repo's real .env off
    disk mid-test regardless of what env vars a test already cleared.
    This does not stop litellm's own import-time dotenv auto-load (see
    _isolate_router_env): that walks up from litellm's file inside
    .venv, which sits inside the repo, so it reaches the repo-root .env
    regardless of cwd. HOME is redirected too so main() never loads the
    real ~/.personal_agent/.env.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture(autouse=True)
def _isolate_router_env(monkeypatch):
    """Clear every ambient router env var before each test body runs.

    Derived from the names personal_agent itself declares, so a newly added
    var is covered automatically. A real repo-root .env must not leak
    values into test assertions; tests opt back in via route_env or
    monkeypatch.setenv as needed.

    LITELLM_MODE=PROD must be set first: litellm auto-loads the
    repo-root .env at import time (guarded on os.getenv("LITELLM_MODE",
    "DEV") == "DEV" in litellm/__init__.py) and writes real values into
    os.environ the first time cost.estimate() imports it, which can
    happen mid-test-body. Forcing PROD mode stops that load before it
    happens, independent of the relative-.env leak _isolate_cwd guards
    against.

    LITELLM_LOCAL_MODEL_COST_MAP=True must also be set here, before any
    test body can import litellm: without it, litellm prices models from
    its live remote cost map (checked via
    os.getenv("LITELLM_LOCAL_MODEL_COST_MAP", "").lower() == "true" in
    litellm_core_utils/get_model_cost_map.py), which drifts over time and
    can retire a model id a test relies on, making tests flaky against
    the network instead of deterministic against the litellm version
    pinned in uv.lock.
    """
    monkeypatch.setenv("LITELLM_MODE", "PROD")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    def unexpected_provider_request(*args, **kwargs):
        raise AssertionError("Unmocked Provider HTTP request")

    monkeypatch.setattr(http, "urlopen", unexpected_provider_request)
    monkeypatch.setattr(openrouter, "urlopen", unexpected_provider_request)
    monkeypatch.setattr(model_catalog, "_open", unexpected_provider_request)
    monkeypatch.setattr(chatgpt_auth, "_open", unexpected_provider_request)
    monkeypatch.setattr(chatgpt_auth, "KNOWN_SECRETS", set())
    for var in _PA_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


SYNTHETIC_MODELS = (
    "vendor/test-model", "vendor/other-model", "vendor/new", "vendor/changed-model", "vendor/Case-Model",
    "vendor/smaller-model", "claude-3-haiku-20240307", "claude-test", "gemini-2.5-flash", "new-model",
    "exported-model", "from-export", "from-cwd", "from-home", "home-model", "cache-fixture", "test-model",
)
_synthetic_cache: list[bytes] = []


@pytest.fixture(autouse=True)
def _synthetic_catalog(_isolate_router_env, tmp_path_factory, monkeypatch):
    """Admit synthetic exact offerings through the real catalog refresh path, cached outside the temporary home."""
    target = tmp_path_factory.mktemp("catalog") / "models-dev.json"
    monkeypatch.setattr(model_catalog, "cache_path", lambda: target)
    if _synthetic_cache:
        target.write_bytes(_synthetic_cache[0])
        return
    blocked = model_catalog._open
    monkeypatch.setattr(model_catalog, "_open", lambda request, timeout=None: FakeCatalogResponse(
        synthetic_models_dev(SYNTHETIC_MODELS)))
    model_catalog.refresh()
    monkeypatch.setattr(model_catalog, "_open", blocked)
    _synthetic_cache.append(target.read_bytes())


@pytest.fixture(autouse=True)
def _isolate_router_log(tmp_path, monkeypatch, _isolate_router_env):
    """Reset captured Session/storage state under the temporary home."""
    monkeypatch.setenv(memory.MEMORY_PATH_ENV_VAR, str(tmp_path / "memory.jsonl"))
    call_log.reset_session()


@pytest.fixture(autouse=True)
def _reset_shell_tool_registry():
    """Undo any enable_shell_tool()/configure_shell() a test called, so
    `shell` and its timeout/output-cap settings never leak into an
    unrelated later test."""
    yield
    jobs.reset()
    tools_registry.reset_registry()
    shell_tool.reset_shell_config()


@pytest.fixture
def route_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("PA_PROVIDER", "openrouter")
    monkeypatch.setenv("PA_MODEL", "vendor/test-model")


@pytest.fixture
def install_fake_urlopen(monkeypatch):
    """Patch the shared HTTP seam with a fake that returns `answers` in call order.

    Pass a single string for a one-call test, or a list of strings for a
    multi-call test. An item that is a BaseException instance is raised
    instead of returning a response, for testing failed/interrupted calls.
    An item that is a dict is treated as {"content": ..., "usage": {...}}
    so a test can script a response's reported cost/tokens. A trailing
    `Repeat(outcome)` is used for every call beyond the end of the list,
    instead of IndexError-ing.
    Returns the list of captured calls, each a dict with "request" and
    "timeout".
    """

    def _install(answers):
        if isinstance(answers, str):
            answers = [answers]
        calls = []

        def fake_urlopen(request, timeout=None):
            assert request.get_method() == "POST" and request.data is not None
            assert request.full_url in {
                "https://openrouter.ai/api/v1/chat/completions", "https://api.openai.com/v1/chat/completions",
                "https://api.anthropic.com/v1/messages",
            } or request.full_url.startswith("https://generativelanguage.googleapis.com/v1beta/models/")
            response = build_response(request, timeout)
            if (json.loads(request.data).get("stream") or ":streamGenerateContent" in request.full_url) and isinstance(response, FakeOpenRouterResponse):
                return response.stream()
            return response

        def build_response(request, timeout=None):
            calls.append({"request": request, "timeout": timeout})
            index = len(calls) - 1
            if index >= len(answers) and isinstance(answers[-1], Repeat):
                index = len(answers) - 1
            answer = answers[index]
            if isinstance(answer, Repeat):
                answer = answer.outcome
            if isinstance(answer, BaseException):
                raise answer
            if isinstance(answer, FakeOpenRouterResponse):
                return answer
            if isinstance(answer, dict):
                tool_calls = answer.get("tool_calls")
                content = answer.get("content")
                if request.full_url == "https://api.anthropic.com/v1/messages":
                    if tool_calls is not None:
                        blocks = ([{"type": "text", "text": content}] if content else []) + [
                            {"type": "tool_use", "id": call["id"], "name": call["name"], "input": call["arguments"]}
                            for call in tool_calls
                        ]
                        payload = {"content": blocks}
                    else:
                        payload = {"content": [{"type": "text", "text": content}]}
                    if "usage" in answer:
                        usage = answer["usage"]
                        fields = {"prompt_tokens": "input_tokens", "completion_tokens": "output_tokens",
                                  "cached_tokens": "cache_read_input_tokens", "cache_write_tokens": "cache_creation_input_tokens"}
                        payload["usage"] = {native: usage[field] for field, native in fields.items() if field in usage}
                elif request.full_url.startswith("https://generativelanguage.googleapis.com/"):
                    if tool_calls is not None:
                        parts = ([{"text": content}] if content else []) + [
                            {"functionCall": {"name": call["name"], "args": call["arguments"]}} for call in tool_calls
                        ]
                        payload = {"candidates": [{"content": {"parts": parts}}]}
                    else:
                        payload = {"candidates": [{"content": {"parts": [{"text": content}]}}]}
                    if "usage" in answer:
                        usage = answer["usage"]
                        fields = {"prompt_tokens": "promptTokenCount", "completion_tokens": "candidatesTokenCount",
                                  "cached_tokens": "cachedContentTokenCount"}
                        payload["usageMetadata"] = {native: usage[field] for field, native in fields.items() if field in usage}
                else:
                    if tool_calls is not None:
                        message = {
                            "content": content,
                            "tool_calls": [
                                {
                                    "id": call["id"],
                                    "type": "function",
                                    "function": {
                                        "name": call["name"],
                                        "arguments": call["arguments_raw"]
                                        if "arguments_raw" in call
                                        else json.dumps(call["arguments"]),
                                    },
                                }
                                for call in tool_calls
                            ],
                        }
                    else:
                        message = {"content": content}
                    payload = {"choices": [{"message": message}]}
                    if "usage" in answer:
                        payload["usage"] = answer["usage"]
                return FakeOpenRouterResponse(payload)
            if request.full_url == "https://api.anthropic.com/v1/messages":
                return FakeOpenRouterResponse({"content": [{"type": "text", "text": answer}]})
            if request.full_url.startswith("https://generativelanguage.googleapis.com/"):
                return FakeOpenRouterResponse({"candidates": [{"content": {"parts": [{"text": answer}]}}]})
            return FakeOpenRouterResponse({"choices": [{"message": {"content": answer}}]})

        monkeypatch.setattr(http, "urlopen", fake_urlopen)
        return calls

    return _install
