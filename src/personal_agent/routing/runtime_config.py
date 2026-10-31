import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from types import MappingProxyType

from personal_agent.chatgpt_auth import Binding
from personal_agent.model_catalog import Offering
from personal_agent.providers.registry import PROVIDERS

PROVIDER_ENV_VAR = "PA_PROVIDER"
SUPPORTED_PROVIDERS = tuple(PROVIDERS)
MODEL_ENV_VAR = "PA_MODEL"
CHATGPT_REASONING_ENV_VAR = "PA_CHATGPT_REASONING_EFFORT"
MAX_TOOL_ROUNDS_ENV_VAR = "PA_MAX_TOOL_ROUNDS"
CONTEXT_BUDGET_ENV_VAR = "PA_CONTEXT_BUDGET_TOKENS"
CAPACITY_OVERRIDES_ENV_VAR = "PA_CONTEXT_CAPACITY_OVERRIDES"
CONTEXT_ENV_VARS = {CONTEXT_BUDGET_ENV_VAR, CAPACITY_OVERRIDES_ENV_VAR}
API_KEY_ENV_VARS = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
MANAGED_ENV_VARS = {PROVIDER_ENV_VAR, MODEL_ENV_VAR, CHATGPT_REASONING_ENV_VAR, *API_KEY_ENV_VARS.values(), *CONTEXT_ENV_VARS}


@dataclass(frozen=True)
class RuntimeConfig:
    provider: str
    model: str
    api_keys: Mapping[str, str]
    context_budget_tokens: int = 250000
    capacity_overrides: tuple[Mapping, ...] = ()
    max_tool_rounds: int = 50
    offering: Offering | None = None
    capacity_snapshot: Mapping | None = None
    chatgpt_binding: Binding | None = None
    readiness_error: str | None = None
    chatgpt_reasoning_effort: str = "auto"

    def snapshot(self) -> "RuntimeConfig":
        return RuntimeConfig(
            self.provider, self.model, MappingProxyType(dict(self.api_keys)), self.context_budget_tokens,
            tuple(MappingProxyType(dict(record)) for record in self.capacity_overrides),
            self.max_tool_rounds, self.offering,
            MappingProxyType(dict(self.capacity_snapshot)) if self.capacity_snapshot is not None else None,
            self.chatgpt_binding, self.readiness_error, self.chatgpt_reasoning_effort,
        )

    @property
    def api_key(self) -> str:
        return self.api_keys.get(self.provider, "")


def load(env: Mapping[str, str] | None = None) -> RuntimeConfig:
    env = env if env is not None else os.environ
    return RuntimeConfig(
        provider=env.get(PROVIDER_ENV_VAR, "").strip().lower(),
        model=env.get(MODEL_ENV_VAR, "").strip(),
        api_keys={provider: env.get(var_name, "") for provider, var_name in API_KEY_ENV_VARS.items()},
        context_budget_tokens=parse_context_budget(env.get(CONTEXT_BUDGET_ENV_VAR, "250000")),
        capacity_overrides=parse_capacity_overrides(env.get(CAPACITY_OVERRIDES_ENV_VAR, "[]")),
        max_tool_rounds=parse_max_tool_rounds(env.get(MAX_TOOL_ROUNDS_ENV_VAR, "50")),
        chatgpt_reasoning_effort=parse_reasoning_effort(env.get(CHATGPT_REASONING_ENV_VAR, "auto")),
    )


def parse_reasoning_effort(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", value):
        raise ValueError(f"{CHATGPT_REASONING_ENV_VAR} must be auto or an advertised reasoning level")
    return value


def validate_reasoning(config: RuntimeConfig) -> None:
    effort = parse_reasoning_effort(config.chatgpt_reasoning_effort)
    if config.provider != "chatgpt" or effort == "auto":
        return
    offering = config.offering
    if offering is None or (offering.provider, offering.id) != (config.provider, config.model) or not offering.reasoning_levels:
        raise ValueError("ChatGPT reasoning levels are unknown; use /reasoning auto")
    if effort not in offering.reasoning_levels:
        raise ValueError(f"ChatGPT model does not support reasoning {effort!r}; choose "
                         + ", ".join(offering.reasoning_levels) + " or use /reasoning auto")


def parse_max_tool_rounds(value: str) -> int:
    if not re.fullmatch(r"[0-9]+", value) or int(value) <= 0:
        raise ValueError(f"{MAX_TOOL_ROUNDS_ENV_VAR} must be a positive decimal integer")
    return int(value)


def parse_context_budget(value: str) -> int:
    if not re.fullmatch(r"[0-9]+", value) or int(value) <= 0:
        raise ValueError(f"{CONTEXT_BUDGET_ENV_VAR} must be a positive decimal integer")
    return int(value)


def parse_capacity_overrides(value: str) -> tuple[dict, ...]:
    message = f"{CAPACITY_OVERRIDES_ENV_VAR} must be a valid array of exact Provider/model capacity records"
    try:
        records = json.loads(value)
        if not isinstance(records, list):
            raise ValueError(message)
        identities = set()
        for record in records:
            if not isinstance(record, dict) or not {"provider", "model", "total_tokens"} <= record.keys():
                raise ValueError(message)
            if record.keys() - {"provider", "model", "total_tokens", "input_tokens", "output_tokens"}:
                raise ValueError(message)
            if record["provider"] not in SUPPORTED_PROVIDERS or not isinstance(record["model"], str) or not record["model"].strip():
                raise ValueError(message)
            identity = record["provider"], record["model"]
            if identity in identities:
                raise ValueError(message)
            identities.add(identity)
            for field in ("total_tokens", "input_tokens", "output_tokens"):
                if field in record and (type(record[field]) is not int or not 0 < record[field] <= record["total_tokens"]):
                    raise ValueError(message)
        return tuple(dict(record) for record in records)
    except (ValueError, TypeError) as exc:
        raise ValueError(message) from exc


def validate(config: RuntimeConfig, env: Mapping[str, str] | None = None) -> list[str]:
    env = env if env is not None else os.environ
    choices = ", ".join(SUPPORTED_PROVIDERS)
    problems = []
    if not config.provider:
        problems.append(f"{PROVIDER_ENV_VAR} is required; choose one of: {choices}")
    elif config.provider not in SUPPORTED_PROVIDERS:
        problems.append(f"{PROVIDER_ENV_VAR} has unrecognised provider {config.provider!r}; expected one of: {choices}")
    if not config.model:
        problems.append(f"{MODEL_ENV_VAR} is required: the exact model ID "
                        "(list them with personal-agent --models <provider>)")
    if config.provider in API_KEY_ENV_VARS and not config.api_key:
        problems.append(f"{API_KEY_ENV_VARS[config.provider]} is required for provider {config.provider!r}")
    if (not config.provider or not config.model) and any(name.startswith("TIER_") for name in env):
        problems.append(f"TIER_* settings are no longer read; set {PROVIDER_ENV_VAR} and {MODEL_ENV_VAR} instead")
    return problems


def admit_chatgpt(config: RuntimeConfig, catalog=None) -> RuntimeConfig:
    from personal_agent import chatgpt_auth, context_budget, model_catalog

    auth = chatgpt_auth.ChatGPTAuth()
    status = auth.status()
    binding = config.chatgpt_binding or status.binding
    if binding is None:
        raise chatgpt_auth.AuthError("ChatGPT disconnected; use /connect chatgpt")
    auth.resolve(binding)
    if status.selected_model != config.model:
        raise chatgpt_auth.AuthError("ChatGPT model must be explicitly selected for this account; use /model chatgpt <slug>")
    offering = next((item for item in auth.models(binding) if item.id == config.model), None)
    if offering is None:
        raise chatgpt_auth.AuthError("ChatGPT model is no longer available; use /models chatgpt then /model chatgpt <slug>")
    if catalog is None:
        try:
            catalog = model_catalog.cached()
        except model_catalog.CatalogError:
            pass
    metadata = catalog.offerings.get("openai", {}).get(config.model) if catalog is not None else None
    if metadata is not None:
        offering = replace(offering, context=metadata.context, input=metadata.input, output=metadata.output)
    admitted = replace(config, offering=offering, chatgpt_binding=binding, capacity_snapshot=None, readiness_error=None)
    try:
        validate_reasoning(admitted)
    except ValueError as exc:
        raise chatgpt_auth.AuthError(str(exc)) from None
    return replace(admitted, capacity_snapshot=asdict(context_budget.resolve(admitted, "chatgpt", config.model)))
