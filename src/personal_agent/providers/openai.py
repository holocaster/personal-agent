import os
from collections.abc import Callable

from personal_agent.providers import chat_completions, http
from personal_agent.providers.contract import AssistantMessage, ToolDef, validate_output_allowance

API_URL = "https://api.openai.com/v1/chat/completions"
COST_ESTIMATED = True
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
PROVIDER_LABEL = "openai"
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
    prepared = prepared_input if prepared_input is not None else prepare_input(system, messages, tools, replay)
    payload = {"model": model, **prepared, "max_completion_tokens": max_output_tokens}

    if on_text is not None:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        assistant, usage, data = chat_completions.stream_response(
            API_URL, payload,
            {"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '') if api_key is None else api_key}"},
            PROVIDER_LABEL, model, tools, on_text,
        )
        return assistant, usage

    usage = None
    try:
        data = http.post_json(
            API_URL,
            payload,
            {"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '') if api_key is None else api_key}"},
        )
        usage = http.response_usage(data, PROVIDER_LABEL, model)
        http.raise_for_response_error(data, PROVIDER_LABEL, model, bool(tools), usage)
        assistant = chat_completions.parse_response(data)
    except Exception as exc:
        http.raise_for_provider_error(exc, PROVIDER_LABEL, model, bool(tools), usage)
        raise

    return assistant, usage
