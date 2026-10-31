from dataclasses import dataclass, replace

from personal_agent.routing.runtime_config import RuntimeConfig
from personal_agent.token_estimate import local_library

DEFAULT_TOTAL = 128000
OUTPUT_RESERVE = 16000
MARGIN = 10000


@dataclass(frozen=True)
class ExchangeLimits:
    total_tokens: int
    total_source: str
    input_tokens: int | None
    input_source: str | None
    output_tokens: int | None
    output_source: str | None
    effective_total: int
    output_reserve: int
    input_ceiling: int


def model_info(provider: str, model: str) -> dict:
    prefixes = {"openrouter": "openrouter/", "gemini": "gemini/"}
    try:
        litellm, _ = local_library()
        if provider == "chatgpt":
            return litellm.model_cost.get(model, {})
        return litellm.get_model_info(prefixes.get(provider, "") + model, custom_llm_provider=provider)
    except Exception:
        return {}


def resolve(config: RuntimeConfig, provider: str, model: str, output_cap: int | None = None) -> ExchangeLimits:
    if config.capacity_snapshot is not None and (provider, model) == (config.provider, config.model):
        limits = ExchangeLimits(**config.capacity_snapshot)
        if output_cap is None:
            return limits
        if type(output_cap) is not int or output_cap <= 0:
            raise ValueError("output cap must be a positive integer")
        reserve = min(limits.output_reserve, output_cap)
        ceiling = min(limits.effective_total - reserve, limits.input_tokens or limits.effective_total) - MARGIN
        return replace(limits, output_reserve=reserve, input_ceiling=ceiling)
    info = model_info(provider, model)
    if not isinstance(info, dict):
        info = {}
    source = "LiteLLM" if provider == "chatgpt" else "published model-wide" if provider == "openrouter" else "published"
    values = {"total_tokens": None}
    sources = {"total_tokens": None}
    for field, metadata_field in (("input_tokens", "max_input_tokens"), ("output_tokens", "max_output_tokens")):
        value = info.get(metadata_field)
        values[field] = value if type(value) is int and value > 0 else None
        sources[field] = source if values[field] is not None else None
    if values["input_tokens"] is not None:
        values["total_tokens"], sources["total_tokens"] = values["input_tokens"], source
    offering = config.offering
    if offering is not None and (offering.provider, offering.id) == (provider, model):
        for field, value in (("total_tokens", offering.context), ("input_tokens", offering.input),
                             ("output_tokens", offering.output)):
            if value is not None:
                values[field], sources[field] = value, "Models.dev"
    for record in config.capacity_overrides:
        if (record["provider"], record["model"]) == (provider, model):
            for field in values:
                if field in record:
                    values[field], sources[field] = record[field], "manual"
            break
    total = values["total_tokens"] or DEFAULT_TOTAL
    total_source = sources["total_tokens"] if values["total_tokens"] else "unknown; assumed"
    effective = min(config.context_budget_tokens, total)
    reserve = min(OUTPUT_RESERVE, values["output_tokens"] or OUTPUT_RESERVE)
    if output_cap is not None:
        if type(output_cap) is not int or output_cap <= 0:
            raise ValueError("output cap must be a positive integer")
        reserve = min(reserve, output_cap)
    ceiling = min(effective - reserve, values["input_tokens"] or effective) - MARGIN
    return ExchangeLimits(total, total_source, values["input_tokens"], sources["input_tokens"],
                          values["output_tokens"], sources["output_tokens"],
                          effective, reserve, ceiling)
