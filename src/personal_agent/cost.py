import math

from personal_agent.token_estimate import local_library


def _count(value):
    return type(value) is int and value >= 0


def estimate(model: str, prompt_tokens: int | None, completion_tokens: int | None, *,
             provider: str | None = None, cached_tokens=0, cache_write_tokens=0,
             cache_creation_token_details=None) -> float | None:
    counts = (prompt_tokens, completion_tokens, cached_tokens, cache_write_tokens)
    if not all(_count(value) for value in counts) or cached_tokens + cache_write_tokens > prompt_tokens:
        return None
    if cache_creation_token_details is not None:
        if not isinstance(cache_creation_token_details, dict):
            return None
        ttl_counts = [cache_creation_token_details.get(key) for key in
                      ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")]
        if not all(_count(value) for value in ttl_counts) or sum(ttl_counts) != cache_write_tokens:
            return None
    try:
        litellm, _ = local_library()
        info = litellm.get_model_info(model, custom_llm_provider=provider)
        prices = litellm.model_cost.get(info.get("key"), {})
        required = ["input_cost_per_token", "output_cost_per_token"]
        if cached_tokens:
            required.append("cache_read_input_token_cost")
        if cache_write_tokens:
            required.append("cache_creation_input_token_cost")
        if cache_creation_token_details and cache_creation_token_details["ephemeral_1h_input_tokens"]:
            required.append("cache_creation_input_token_cost_above_1hr")
        if any(type(prices.get(key)) not in (int, float) or not math.isfinite(prices[key]) or prices[key] < 0
               for key in required):
            return None
        details = {"cached_tokens": cached_tokens, "cache_write_tokens": cache_write_tokens}
        if cache_creation_token_details is not None:
            details["cache_creation_token_details"] = cache_creation_token_details
        usage = litellm.Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                              total_tokens=prompt_tokens + completion_tokens, prompt_tokens_details=details)
        prompt_cost, completion_cost = litellm.cost_per_token(
            model, prompt_tokens, completion_tokens, custom_llm_provider=provider, usage_object=usage)
        result = float(prompt_cost + completion_cost)
        return result if math.isfinite(result) and result >= 0 else None
    except Exception:
        return None
