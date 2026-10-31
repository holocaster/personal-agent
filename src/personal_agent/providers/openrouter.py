import json
import os
from collections.abc import Callable
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from personal_agent.providers import chat_completions, http
from personal_agent.providers.contract import AssistantMessage, ToolDef, validate_output_allowance

API_URL = "https://openrouter.ai/api/v1/chat/completions"
COST_ESTIMATED = False
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
PROVIDER_LABEL = "openrouter"
PROVIDER_DIAGNOSTICS_ENV_VAR = "PA_OPENROUTER_PROVIDER_DIAGNOSTICS"
_sleep = time.sleep
UPSTREAM_LOOKUP_DELAYS = (0, 5, 10, 15, 15, 15)
prepare_input = chat_completions.prepare_input


def is_retryable(exc: BaseException) -> bool:
    return http.is_retryable(exc, RETRYABLE_HTTP_CODES)


def call(
    model: str,
    system: str,
    messages: list[dict],
    tools: tuple[ToolDef, ...] | None = None,
    replay: object = None,
    api_key: str | None = None,
    max_output_tokens: int = 16000,
    prepared_input: dict | None = None,
    on_text: Callable[[str], None] | None = None,
    session_id: str | None = None,
) -> tuple[AssistantMessage, dict]:
    validate_output_allowance(max_output_tokens)
    if session_id is not None and (not isinstance(session_id, str) or len(session_id) > 256):
        raise ValueError("session_id must be a string of at most 256 characters")
    prepared = prepared_input if prepared_input is not None else prepare_input(system, messages, tools, replay)
    payload = {"model": model, **prepared, "max_tokens": max_output_tokens,
               "provider": {"sort": "price", "preferred_min_throughput": 85, "require_parameters": True}}
    if session_id is not None:
        payload["session_id"] = session_id
    if model.startswith("anthropic/"):
        payload["cache_control"] = {"type": "ephemeral"}

    if on_text is not None:
        payload["stream"] = True
        assistant, usage, data = chat_completions.stream_response(
            API_URL, payload,
            {"Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '') if api_key is None else api_key}"},
            PROVIDER_LABEL, model, tools, on_text,
        )
        if os.environ.get(PROVIDER_DIAGNOSTICS_ENV_VAR) == "1":
            usage["generation_id"] = data.get("id")
        return assistant, usage

    usage = None
    try:
        data = http.post_json(
            API_URL,
            payload,
            {"Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '') if api_key is None else api_key}"},
        )
        usage = http.response_usage(data, PROVIDER_LABEL, model)
        http.raise_for_response_error(data, PROVIDER_LABEL, model, bool(tools), usage)
        assistant = chat_completions.parse_response(data)
    except Exception as exc:
        http.raise_for_provider_error(exc, PROVIDER_LABEL, model, bool(tools), usage)
        raise

    if os.environ.get(PROVIDER_DIAGNOSTICS_ENV_VAR) == "1":
        usage["generation_id"] = data.get("id")
    return assistant, usage


def _lookup_upstream_provider(generation_id: str, api_key: str | None) -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "") if api_key is None else api_key
    request = Request(
        f"https://openrouter.ai/api/v1/generation?id={quote(generation_id, safe='')}",
        headers={"Authorization": f"Bearer {key}"},
    )
    for delay in UPSTREAM_LOOKUP_DELAYS:
        if delay:
            _sleep(delay)
        try:
            with urlopen(request, timeout=3) as response:
                provider_name = json.loads(response.read()).get("data", {}).get("provider_name")
        except HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        if isinstance(provider_name, str) and provider_name:
            return provider_name
        raise ValueError("generation metadata has no provider_name")
    raise LookupError(f"generation still not found after {sum(UPSTREAM_LOOKUP_DELAYS)}s")
