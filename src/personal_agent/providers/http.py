import json
import codecs
import re
import ssl
from collections.abc import Collection
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from personal_agent import cost
from personal_agent.providers.contract import ContextOverflowError, ToolsUnsupportedError


class _RedirectGuard(HTTPRedirectHandler):
    def redirect_request(self, request, *args, **kwargs):
        if getattr(request, "no_redirect", False):
            return None
        return super().redirect_request(request, *args, **kwargs)


urlopen = build_opener(_RedirectGuard).open
TIMEOUT_SECONDS = 60
TOOLS_REJECTED_HTTP_CODES = {400, 404, 422}
MAX_EVENT_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read())


@contextmanager
def post_sse(url: str, payload: dict, headers: dict[str, str], *, no_redirect: bool = False, response_info: dict | None = None):
    request = Request(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json", "Accept": "text/event-stream", **headers},
                      method="POST")
    request.no_redirect = no_redirect
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if response_info is not None:
            response_headers = getattr(response, "headers", None) or {}
            response_info.update(status=getattr(response, "status", 200),
                                 request_id=response_headers.get("x-request-id") or response_headers.get("x-oai-request-id"))
        yield _sse_events(response)


def _sse_events(response):
    decoder = codecs.getincrementaldecoder("utf-8")()
    read = response.read1 if hasattr(response, "read1") else response.read
    line, data, event = [], [], ""
    event_bytes = 0
    after_cr = False
    pending = False
    while True:
        raw = read(4096)
        text = decoder.decode(raw, final=not raw)
        for character in text:
            if after_cr:
                after_cr = False
                if character == "\n":
                    continue
            event_bytes += len(character.encode("utf-8"))
            if event_bytes > MAX_EVENT_BYTES:
                raise ValueError("SSE event exceeds 256 KiB limit")
            if character not in "\r\n":
                line.append(character)
                continue
            after_cr = character == "\r"
            value = "".join(line)
            line.clear()
            if not value:
                if data:
                    yield event, "\n".join(data)
                data, event, pending, event_bytes = [], "", False, 0
                continue
            pending = True
            field, separator, value = value.partition(":")
            if separator and value.startswith(" "):
                value = value[1:]
            if field == "data":
                data.append(value)
            elif field == "event":
                event = value
        if not raw:
            if line or pending:
                raise ValueError("Incomplete SSE event at EOF")
            return


def is_retryable(exc: BaseException, retryable_http_codes: Collection[int]) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in retryable_http_codes
    if isinstance(exc, URLError):
        exc = exc.reason
    if isinstance(exc, ssl.SSLError):
        return getattr(exc, "reason", None) in {"SSLV3_ALERT_BAD_RECORD_MAC", "DECRYPTION_FAILED_OR_BAD_RECORD_MAC"}
    return isinstance(exc, TimeoutError)


def response_usage(data: dict, provider: str, model: str) -> dict:
    usage = data.get("usageMetadata" if provider == "gemini" else "usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    if provider in {"openrouter", "openai"}:
        cache = usage.get("prompt_tokens_details", {})
        if not isinstance(cache, dict):
            cache = {"cached_tokens": "invalid details", "cache_write_tokens": "invalid details"}
        normalized = {"prompt_tokens": usage.get("prompt_tokens"),
                      "completion_tokens": usage.get("completion_tokens"),
                      "cached_tokens": cache.get("cached_tokens"),
                      "cache_write_tokens": cache.get("cache_write_tokens")}
    elif provider == "anthropic":
        counts = [usage.get("input_tokens"), usage.get("cache_read_input_tokens", 0),
                  usage.get("cache_creation_input_tokens", 0)]
        normalized = {"prompt_tokens": sum(counts) if all(type(n) is int and n >= 0 for n in counts) else None,
                      "completion_tokens": usage.get("output_tokens"),
                      "cached_tokens": usage.get("cache_read_input_tokens"),
                      "cache_write_tokens": usage.get("cache_creation_input_tokens")}
        if "cache_creation" in usage:
            normalized["cache_creation_token_details"] = (usage["cache_creation"] if isinstance(usage["cache_creation"], dict)
                                                           else "invalid details")
    else:
        normalized = {"prompt_tokens": usage.get("promptTokenCount"),
                      "completion_tokens": usage.get("candidatesTokenCount"),
                      "cached_tokens": usage.get("cachedContentTokenCount"), "cache_write_tokens": None}
    if provider == "openrouter":
        return {**normalized, "cost": usage.get("cost")}
    read, write = normalized["cached_tokens"], normalized["cache_write_tokens"]
    if provider == "anthropic" and "cache_read_input_tokens" not in usage:
        read = 0
    if provider == "gemini" and "cachedContentTokenCount" not in usage:
        read = 0
    if write is None:
        if provider == "gemini" or (provider == "anthropic" and "cache_creation_input_tokens" not in usage):
            write = 0
    normalized["cost"] = cost.estimate(
        f"gemini/{model}" if provider == "gemini" else model, normalized["prompt_tokens"],
        normalized["completion_tokens"], provider=provider, cached_tokens=read, cache_write_tokens=write,
        cache_creation_token_details=normalized.get("cache_creation_token_details"))
    normalized["cost_estimated"] = True
    for key in ("cached_tokens", "cache_write_tokens"):
        if normalized[key] is None:
            del normalized[key]
    return normalized


def native_stream_usage(snapshot, raw_usage: dict, usage: dict, provider: str, model: str) -> None:
    if not isinstance(snapshot, dict):
        raise ValueError("Malformed stream usage")
    cache_fields = ({"cache_read_input_tokens": "cached_tokens", "cache_creation_input_tokens": "cache_write_tokens"}
                    if provider == "anthropic" else {"cachedContentTokenCount": "cached_tokens"})
    fields = ({"input_tokens", "output_tokens", *cache_fields} if provider == "anthropic" else
              {"promptTokenCount", "candidatesTokenCount", "totalTokenCount", "thoughtsTokenCount",
               "toolUsePromptTokenCount", *cache_fields})
    invalid = []
    for field in fields & snapshot.keys():
        value = snapshot[field]
        if type(value) is int and value >= 0:
            raw_usage[field] = value
        else:
            raw_usage.setdefault(field, value)
            invalid.append(field)
    if provider == "anthropic" and "cache_creation" in snapshot:
        details = snapshot["cache_creation"]
        if isinstance(details, dict):
            saved = raw_usage.setdefault("cache_creation", {})
            for key in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"):
                if key in details:
                    value = details[key]
                    if type(value) is int and value >= 0:
                        saved[key] = value
                    else:
                        saved.setdefault(key, value)
                        invalid.append(key)
        else:
            raw_usage.setdefault("cache_creation", details)
            invalid.append("cache_creation")
    key = "usage" if provider == "anthropic" else "usageMetadata"
    usage.update(response_usage({key: raw_usage}, provider, model))
    usage.update({normalized: raw_usage[field] for field, normalized in cache_fields.items() if field in raw_usage})
    if invalid:
        usage["cost"] = None
        raise ValueError("Invalid stream usage fields: " + ", ".join(sorted(invalid)))


def _error_evidence(exc: HTTPError) -> tuple[str, dict]:
    if hasattr(exc, "_pa_evidence"):
        return exc._pa_evidence
    try:
        detail = exc.read().decode("utf-8", errors="replace")
    except Exception:
        detail = ""
    finally:
        exc.close()
    try:
        data = json.loads(detail)
    except (ValueError, TypeError):
        data = {"message": detail}
    exc._pa_evidence = (detail, data if isinstance(data, dict) else {})
    if detail.strip():
        exc.msg = f"{exc.msg}: {detail.strip()[:1000]}"
    return exc._pa_evidence


def _context_overflow(provider: str, error: dict) -> bool:
    message = error.get("message", "")
    message = message.lower() if isinstance(message, str) else ""
    if provider in {"openai", "openrouter"}:
        if error.get("code") == "context_length_exceeded" or error.get("type") == "context_length_exceeded":
            return True
        if re.search(r"this model's maximum context length is [\d,]+ tokens[.,\s].*however,? you requested [\d,]+ tokens", message):
            return True
    if provider == "anthropic" and re.match(r"prompt is too long\b", message):
        return True
    if provider == "gemini" and re.search(
        r"input token count.*exceeds the maximum number of tokens allowed", message
    ):
        return True
    if provider == "openrouter":
        metadata = error.get("metadata")
        if isinstance(metadata, dict):
            if metadata.get("error_type") == "context_length_exceeded" or metadata.get("provider_code") == "context_length_exceeded":
                return True
            raw = metadata.get("raw")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except ValueError:
                    raw = {"message": raw}
            if isinstance(raw, dict):
                upstream = raw.get("error", raw)
                if isinstance(upstream, dict):
                    return any(_context_overflow(vendor, upstream) for vendor in ("openai", "anthropic", "gemini"))
    return False


def raise_for_provider_error(exc: BaseException, provider_label: str, model: str, tools_requested: bool,
                             usage: dict | None = None) -> None:
    if usage is not None:
        exc.usage = usage
    if not isinstance(exc, HTTPError):
        return
    detail, data = _error_evidence(exc)
    if usage is None and not hasattr(exc, "usage"):
        exc.usage = response_usage(data, provider_label, model)
    error = data.get("error", data)
    if (exc.code in {400, 413, 422} or provider_label == "openrouter" and exc.code == 502):
        if isinstance(error, dict) and _context_overflow(provider_label, error):
            failure = ContextOverflowError(
                f"{provider_label} model {model!r} context overflow (HTTP {exc.code}): {detail.strip()[:1000]}"
            )
            failure.usage = exc.usage
            raise failure from exc
    raise_if_tools_unsupported(exc, provider_label, model, tools_requested)


def raise_for_response_error(data: dict, provider_label: str, model: str, tools_requested: bool,
                            usage: dict | None = None) -> None:
    envelopes = [data]
    if provider_label == "openrouter":
        envelopes.extend(data.get("choices") or [])
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            continue
        error = envelope.get("error")
        if not isinstance(error, dict):
            continue
        evidence = {"error": error}
        detail = json.dumps(evidence)
        status = error.get("code")
        if type(status) is not int and provider_label == "anthropic":
            status = {"invalid_request_error": 400, "authentication_error": 401, "billing_error": 402,
                      "permission_error": 403, "not_found_error": 404, "conflict_error": 409,
                      "request_too_large": 413, "rate_limit_error": 429, "api_error": 500,
                      "timeout_error": 504, "overloaded_error": 529}.get(error.get("type"), 502)
        exc = HTTPError("", status if type(status) is int else 502, detail[:1000], None, None)
        exc._pa_evidence = (detail, evidence)
        raise_for_provider_error(exc, provider_label, model, tools_requested,
                                 response_usage(data, provider_label, model) if usage is None else usage)
        raise exc


def raise_if_tools_unsupported(exc: BaseException, provider_label: str, model: str, tools_requested: bool) -> None:
    """Re-raise a readable, non-retryable ToolsUnsupportedError (R09) when the
    HTTP error body indicates the Provider's API rejected Tool support for this
    model. Any other error is left untouched for the caller to re-raise as-is.
    """
    if not tools_requested or not isinstance(exc, HTTPError) or exc.code not in TOOLS_REJECTED_HTTP_CODES:
        return
    detail, data = _error_evidence(exc)
    error = data.get("error", data)
    message = error.get("message", "") if isinstance(error, dict) else ""
    tool_kind = r"(?:tools?|tool use|tool calling|function calling)"
    unsupported = (
        rf"\b{tool_kind}\s+(?:(?:is|are)\s+)?(?:not supported|unsupported|not available|unavailable)\b|"
        rf"\b(?:does not|doesn't|do not|cannot)\s+support\s+{tool_kind}\b|"
        rf"\bno endpoints?(?: found)?(?: that)? support\s+{tool_kind}\b"
    )
    if not isinstance(message, str) or not re.search(unsupported, message, re.IGNORECASE):
        return
    failure = ToolsUnsupportedError(
        f"{provider_label} model {model!r} does not support Tools (HTTP {exc.code}): {detail.strip()[:300]}"
    )
    failure.usage = getattr(exc, "usage", {})
    raise failure from exc


class StreamText:
    def __init__(self, secrets):
        self.secrets = secrets
        self.pending = ""

    def feed(self, text):
        self.pending += text
        return self._drain(False)

    def finish(self):
        return self._drain(True)

    def _drain(self, final):
        secrets = self.secrets() if callable(self.secrets) else self.secrets
        secrets = sorted({secret for secret in secrets if secret}, key=len, reverse=True)
        output = []
        offset = 0
        while offset < len(self.pending):
            remaining = len(self.pending) - offset
            if not final and any(len(secret) > remaining and secret.startswith(self.pending[offset:]) for secret in secrets):
                break
            match = next((secret for secret in secrets if self.pending.startswith(secret, offset)), None)
            if match is not None:
                output.append("[redacted]")
                offset += len(match)
            else:
                output.append(self.pending[offset])
                offset += 1
        self.pending = self.pending[offset:]
        return "".join(output)
